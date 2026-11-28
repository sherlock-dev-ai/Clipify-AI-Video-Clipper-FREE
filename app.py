from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import warnings
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit
from windows_process import clear_ffmpeg_report_environment, install_hidden_subprocess_defaults

def _ensure_cuda_dlls():
    """Ensure CUDA 12 and cuDNN dynamic libraries are discoverable on Windows."""
    if sys.platform != "win32":
        return
    import site
    search_dirs = []
    try:
        for base in site.getsitepackages():
            nv_dir = Path(base) / "nvidia"
            if nv_dir.is_dir():
                for sub in nv_dir.iterdir():
                    bin_dir = sub / "bin"
                    if bin_dir.is_dir():
                        search_dirs.append(str(bin_dir))
            ct2_dir = Path(base) / "ctranslate2"
            if ct2_dir.is_dir():
                search_dirs.append(str(ct2_dir))
    except Exception:
        pass
    app_data = os.environ.get("LOCALAPPDATA", "")
    if app_data:
        runtime_nv = Path(app_data) / "Programs" / "ClipifyAI" / "runtime" / "Lib" / "site-packages" / "nvidia"
        if runtime_nv.is_dir():
            for sub in runtime_nv.iterdir():
                b = sub / "bin"
                if b.is_dir():
                    search_dirs.append(str(b))
    for d in search_dirs:
        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
            if d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass

_ensure_cuda_dlls()

# Early application root fallback for unhandled exceptions during bootstrap
ROOT = Path(__file__).resolve().parent

def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
    try:
        log_dir = str(ROOT) if "ROOT" in globals() else str(Path(__file__).resolve().parent)
        with open(os.path.join(log_dir, "app_crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n--- CRASH AT {datetime.now()} ---\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass
sys.excepthook = _log_unhandled_exception

# Safeguard against headless GUI runs where stdio handles may be None or invalid
try:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    else:
        sys.stdout.write("")
        sys.stdout.flush()
except Exception:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    else:
        sys.stderr.write("")
        sys.stderr.flush()
except Exception:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

warnings.filterwarnings("ignore", message=".*libtorchcodec.*")
warnings.filterwarnings("ignore", message=".*torchcodec.*")
warnings.filterwarnings("ignore", module="torchcodec")
warnings.filterwarnings("ignore", category=UserWarning, module="torchcodec")
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote.audio.core.io")

PRODUCT_APP_USER_MODEL_ID = "dev.sherlock.clipifyai"
if os.name == "nt":
    try:
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(PRODUCT_APP_USER_MODEL_ID)
        if result:
            raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: 0x{result & 0xFFFFFFFF:08X}")
    except (AttributeError, OSError):
        # Keep launch available if a restricted Windows shell cannot assign a
        # taskbar identity; the executable resource still carries the logo.
        pass

clear_ffmpeg_report_environment()
install_hidden_subprocess_defaults()

# Note: main.py is executed as a subprocess by run_job(); avoid importing it at
# web-server startup because it eagerly loads heavy ML libraries (torch/whisperx).

import logging
logger = logging.getLogger("clipify")

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, send_file
from werkzeug.utils import secure_filename

def _hidden_creationflags():
    """Keep command-line tools and worker processes from opening console windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _run_hidden(*args, **kwargs):
    if os.name == "nt":
        kwargs.setdefault("creationflags", _hidden_creationflags())
    return subprocess.run(*args, **kwargs)



# Runtime + user-data locations. In a compiled build the install directory is
# read-only application code; everything the user creates lives under
# %LOCALAPPDATA%\ClippedAI so that uninstalling never destroys their work.
from clippedai_runtime import (
    APP_DIR as ROOT,
    USER_DATA_DIR,
    bootstrap as bootstrap_runtime,
    ensure_data_dirs,
    frozen as FROZEN,
    runtime_status,
    runtime_python,
)
from server_config import configured_port

ensure_data_dirs()
bootstrap_runtime()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from narrate.pipeline import NarratePipeline
from narrate.tts import TTSUnavailable, available_voices, create_tts

JOBS = USER_DATA_DIR / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
NARRATE_THUMBS = USER_DATA_DIR / "cache" / "narrate_thumbs"
NARRATE_THUMBS.mkdir(parents=True, exist_ok=True)
_STORAGE_CONFIG_PATH = USER_DATA_DIR / "settings" / "storage_config.json"


def _default_storage_paths() -> dict[str, Path]:
    return {
        "jobs_dir": USER_DATA_DIR / "jobs",
        "ollama_models_dir": Path.home() / ".ollama" / "models",
        "cache_dir": USER_DATA_DIR / "cache",
    }


def _load_storage_config() -> dict[str, str]:
    defaults = {k: str(v) for k, v in _default_storage_paths().items()}
    try:
        if _STORAGE_CONFIG_PATH.is_file():
            saved = json.loads(_STORAGE_CONFIG_PATH.read_text(encoding="utf-8"))
            for k in defaults:
                val = str(saved.get(k, "")).strip()
                if val:
                    defaults[k] = val
    except Exception:
        pass
    return defaults


def _apply_storage_config(cfg: dict[str, str]) -> None:
    global JOBS, NARRATE_THUMBS
    try:
        j = Path(cfg["jobs_dir"])
        j.mkdir(parents=True, exist_ok=True)
        JOBS = j
    except Exception:
        pass
    try:
        o = Path(cfg["ollama_models_dir"])
        o.mkdir(parents=True, exist_ok=True)
        os.environ["OLLAMA_MODELS"] = str(o)
    except Exception:
        pass
    try:
        c = Path(cfg["cache_dir"])
        c.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(c)
        NARRATE_THUMBS = c / "narrate_thumbs"
        NARRATE_THUMBS.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


_apply_storage_config(_load_storage_config())

# main.py already reads .env, but this web process also discovers Ollama before
# it starts the pipeline. Keep the two entry points on the same configuration.
# The install directory copy is read-only defaults; the user copy wins.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(USER_DATA_DIR / ".env", override=True)
except ImportError:
    # The UI can still start with localhost defaults in a minimal web-only setup.
    pass

clear_ffmpeg_report_environment()

APP_HOST = os.environ.get("CLIPIFY_HOST", "0.0.0.0")
APP_PORT = configured_port()

ALLOWED_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "avi", "m4v"}
ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
BRANDING_POSITIONS = {
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
    "custom",
}
UPSCALE_PROFILES = {
    "ultra": {
        "scale_flags": "lanczos+accurate_rnd",
        "unsharp": "unsharp=5:5:0.5:5:5:0.0",
        "crf": "17",
        "preset": "fast",
        "video_bitrate": "10M",
        "maxrate": "15M",
        "bufsize": "20M",
        "label": "Ultra HD (Crisp Lanczos & Anti-Burst)",
    },
    "high": {
        "scale_flags": "lanczos",
        "unsharp": "unsharp=3:3:0.3:3:3:0.0",
        "crf": "19",
        "preset": "fast",
        "video_bitrate": "8M",
        "maxrate": "12M",
        "bufsize": "16M",
        "label": "High Quality (Recommended · Lanczos)",
    },
    "balanced": {
        "scale_flags": "bicubic",
        "unsharp": None,
        "crf": "22",
        "preset": "fast",
        "video_bitrate": "5M",
        "maxrate": "8M",
        "bufsize": "10M",
        "label": "Balanced (Standard 1080p)",
    },
    "fast": {
        "scale_flags": "fast_bilinear",
        "unsharp": None,
        "crf": "25",
        "preset": "veryfast",
        "video_bitrate": "3M",
        "maxrate": "5M",
        "bufsize": "6M",
        "label": "Fast (Compact File)",
    },
}

def get_upscale_profile(quality_override: str | None = None) -> dict[str, Any]:
    key = (quality_override or os.getenv("CLIPPEDAI_UPSCALE_QUALITY", "high")).strip().lower()
    return UPSCALE_PROFILES.get(key, UPSCALE_PROFILES["high"])
MODES = {
    "gaming": {"name": "Gaming", "icon": "🎮", "description": "Gameplay + facecam reactions with stable smart framing"},
    "viral": {"name": "Viral", "icon": "✦", "description": "Hooks, curiosity, surprise & payoff"},
    "funny": {"name": "Funny", "icon": "😂", "description": "Punchlines, reactions & comedic timing"},
    "dramatic": {"name": "Dramatic", "icon": "⚡", "description": "Tension, reveals & emotional moments"},
    "educational": {"name": "Educational", "icon": "◈", "description": "Facts, explanations & takeaways"},
    "story": {"name": "Story", "icon": "◉", "description": "Setup → escalation → payoff"},
    "meme": {"name": "Meme", "icon": "💀", "description": "Chaotic, absurd & reaction-heavy"},
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None  # Unlimited local video upload size


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
@app.errorhandler(500)
def handle_http_error(e):
    if request.path.startswith("/api/"):
        desc = getattr(e, "description", str(e))
        code = getattr(e, "code", 500)
        return jsonify({"error": desc, "status": "error"}), code
    return e


@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    if request.path.startswith("/api/"):
        logger.exception("Unhandled API error on %s: %s", request.path, e)
        return jsonify({"error": f"Internal server error: {str(e)}", "status": "error"}), 500
    raise e


@app.before_request
def _validate_local_request_authority():
    """Reject DNS-rebinding hosts and cross-origin browser requests.

    The server is deliberately loopback-only. Without validating Host, a local
    browser request addressed through an attacker-controlled DNS name could
    expose local health data or reach state-changing routes.
    """
    try:
        request_authority = urlsplit(f"//{request.host}")
        request_host = (request_authority.hostname or "").lower()
        request_port = request_authority.port or (80 if request.scheme == "http" else 443)
    except ValueError:
        return jsonify({"error": "Invalid local request host."}), 400

    def _is_private_or_local(host: str) -> bool:
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_private or ip.is_loopback
        except ValueError:
            return False

    if (request_authority.username or request_authority.password
            or not _is_private_or_local(request_host)
            or (request_port != APP_PORT and not app.config.get("TESTING"))):
        return jsonify({"error": "Use the local Clipify AI address to access this application."}), 400

    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            parsed_origin = urlsplit(origin)
            origin_host = (parsed_origin.hostname or "").lower()
            origin_port = parsed_origin.port or (80 if parsed_origin.scheme == "http" else 443)
        except ValueError:
            return jsonify({"error": "Invalid request origin."}), 403
        if (parsed_origin.scheme != "http"
                or parsed_origin.username or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query or parsed_origin.fragment
                or origin_host not in {"127.0.0.1", "localhost"}
                or origin_host != request_host
                or origin_port != APP_PORT):
            return jsonify({"error": "Cross-origin requests are not allowed."}), 403

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
OLLAMA_RUNTIME_BASE_URL: str | None = None
_OLLAMA_AUTOSTART_ATTEMPTED = False
_STARTED_OLLAMA_PIDS: list[int] = []
_CLEANUP_DONE = False
NARRATE = NarratePipeline(ROOT, USER_DATA_DIR)
narrate_jobs: dict[str, dict[str, Any]] = {}
narrate_jobs_lock = threading.Lock()


def is_allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_allowed_logo(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS


def emit(job_id: str, kind: str, message: Any, **extra: Any) -> None:
    event = {"kind": kind, "message": message, **extra}
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["events"].append(event)
        job["last_message"] = message if isinstance(message, str) else json.dumps(message)
    error = _persist_job_event(job_id, event)
    if error:
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job["event_persistence_error"] = error
        print(f"[EventJournal] Could not persist event for job {job_id}: {error}", file=sys.stderr)


def _safe_job_directory(job_id: str) -> Path | None:
    """Resolve a single job directory only when it remains directly under JOBS."""
    if not isinstance(job_id, str) or not job_id or job_id in {".", ".."}:
        return None
    if any(char in job_id for char in ("/", "\\", ":", "\x00")):
        return None
    try:
        root = JOBS.resolve()
        candidate = (root / job_id).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if candidate.parent != root:
        return None
    return candidate


_event_journal_lock = threading.Lock()
_DIAGNOSTIC_SECRET_PATTERNS = (
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)([\"']?(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)[\"']?\s*[:=]\s*[\"']?)([^\"'\\s,;}]+)"),
)


def _redact_diagnostic_value(value: Any) -> Any:
    """Redact credential-shaped strings before writing local diagnostic records."""
    if isinstance(value, str):
        for pattern in _DIAGNOSTIC_SECRET_PATTERNS:
            value = pattern.sub(r"\1[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [_redact_diagnostic_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_diagnostic_value(item) for key, item in value.items()}
    return value


def _persist_job_event(job_id: str, event: dict[str, Any]) -> str | None:
    """Append one event to its job-local JSONL journal for post-run diagnosis."""
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return "job directory is unavailable"
    journal = job_dir / "events.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": _redact_diagnostic_value(event),
    }
    try:
        with _event_journal_lock:
            with journal.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                stream.flush()
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _pipeline_failure_detail(return_code: int, outputs: list[str], recent_lines: list[str]) -> str:
    """Prefer the worker's concrete failure over the old generic no-output text."""
    if return_code == 0 and outputs:
        return f"Created {len(outputs)} Short(s)."
    failure_line = next(
        (line for line in reversed(recent_lines)
         if any(k in line.lower() for k in ("[fatal]", "[error]", "exception:", "traceback", "failed:", "error:"))),
        "",
    )
    if failure_line:
        clean = failure_line.strip()
        for prefix in ("[FATAL]", "[ERROR]", "[fatal]", "[error]"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
        return clean[:1000]
    if return_code != 0:
        return f"Pipeline worker exited with code {return_code} without reporting a specific failure."
    return "Pipeline worker exited with code 0 but created no final captioned Shorts."


# Third-party libraries print banners and advisories on stdout. Those lines
# used to fall through to the generic branch and become the visible stage, so
# the progress panel filled up with raw warnings instead of what the pipeline
# was actually doing.
_NOISE_MARKERS = (
    "xet storage is enabled",
    "hf_xet",
    "huggingface_hub[hf_xet]",
    "futurewarning",
    "deprecationwarning",
    "userwarning",
    "warnings.warn",
    "resume_download",
    "you should probably upgrade",
    "synchronously installed",
    "requirement already satisfied",
    "collecting ",
    "downloading wheels",
)


def _is_pipeline_noise(text: str) -> bool:
    """True for banner rules and third-party chatter that is not a pipeline stage."""
    stripped = text.strip()
    if not stripped:
        return True
    # Banner rules such as "=====" or "-----" from library output.
    if len(stripped) >= 4 and set(stripped) <= set("=-_~*#"):
        return True
    low = stripped.lower()
    return any(marker in low for marker in _NOISE_MARKERS)


_PROGRESS_CLIP_CONTEXT: dict[str, int] = {"cur": 1, "total": 1}


def _get_hardware_status_lines() -> list[str]:
    """Returns diagnostic log lines describing active GPU and hardware acceleration."""
    lines = []
    gpu_found = False
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            tot = mem.total / (1024**3)
            free = mem.free / (1024**3)
            used = mem.used / (1024**3)
            lines.append(f"[Hardware] GPU {i}: {name} ({tot:.1f} GB VRAM | {free:.1f} GB free | {used:.1f} GB in use)")
            gpu_found = True
    except Exception:
        pass

    if not gpu_found:
        try:
            smi = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=gpu_name,memory.total,memory.free,memory.used", "--format=csv,noheader,nounits"],
                text=True, creationflags=_hidden_creationflags() if sys.platform == "win32" else 0
            ).strip()
            for i, l in enumerate(smi.splitlines()):
                parts = [p.strip() for p in l.split(',')]
                if len(parts) >= 4:
                    name, tot, free, used = parts[0], float(parts[1])/1024, float(parts[2])/1024, float(parts[3])/1024
                    lines.append(f"[Hardware] GPU {i}: {name} ({tot:.1f} GB VRAM | {free:.1f} GB free | {used:.1f} GB in use)")
                    gpu_found = True
        except Exception:
            pass

    if not gpu_found:
        lines.append("[Hardware] GPU: Integrated Graphics / CPU Compute Mode")

    has_ct2_cuda = False
    try:
        _ensure_cuda_dlls()
        import ctranslate2
        has_ct2_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass

    if has_ct2_cuda:
        lines.append("[Hardware] CUDA Acceleration: ACTIVE (WhisperX & CTranslate2 running on GPU 0 float16)")
    else:
        lines.append("[Hardware] Acceleration: Standard CPU Engine")

    lines.append("[Hardware] Alignment Stage: Phoneme matcher (Wav2Vec2) runs with multi-threaded CPU to reserve VRAM for Ollama LLM")
    return lines


def progress_for_line(line: str, current: int, current_stage: str = "") -> tuple[int, str, str]:
    """Translate real pipeline log lines into smooth stage progress.

    ``current_stage`` is echoed back for lines that are not a real stage, so
    third-party noise never replaces what the UI is showing. The raw line is
    still streamed to the activity log by the caller.
    """
    text = line.strip()
    low = text.lower()
    if not text:
        return current, current_stage or "Working…", "Waiting for pipeline output"
    if _is_pipeline_noise(text):
        return current, current_stage or "Working…", ""
    if "model.bin:" in low or "downloading" in low and "model" in low:
        return max(current, 7), "Downloading Whisper model", "First run can download a large model; this is expected."
    if "[start]" in low:
        return max(current, 4), "Preparing video", text
    if "processing video" in low:
        return max(current, 5), "Preparing video", text
    if "loading cached transcription" in low or "existing transcription" in low:
        return max(current, 25), "Loading cached transcription", "Using the saved WhisperX transcript."
    if "transcription completed" in low or "successfully loaded existing transcription" in low:
        return max(current, 30), "Transcription ready", "Transcript loaded successfully."
    if "alignment progress" in low:
        m = re.search(r"progress:\s*([\d\.]+)%", low)
        if m:
            pct = float(m.group(1))
            scaled = 30 + int((pct / 100.0) * 4)
            return max(current, min(34, scaled)), "Aligning word timestamps", f"Aligning word timestamps: {pct:.0f}% (phoneme matching)"
        return max(current, 30), "Aligning word timestamps", text
    if "[align]" in low or "aligning word" in low:
        return max(current, 30), "Aligning word timestamps", "Aligning word timestamps with speech (phoneme matching)…"
    if "speech recognition in progress" in low or "transcription progress" in low:
        m = re.search(r"approx (\d+)%", low) or re.search(r"progress:\s*([\d\.]+)%", low)
        if m:
            pct = float(m.group(1))
            if pct >= 99.5:
                return max(current, 30), "Aligning word timestamps", "Aligning word timestamps with speech (phoneme matching)…"
            scaled = 10 + int((pct / 100.0) * 19)
            return max(current, min(29, scaled)), "Transcribing audio", f"Transcribing audio: {pct:.0f}% of speech processed"
        return max(current, 10), "Transcribing audio", text
    if "transcribing video" in low or "starting transcription" in low:
        return max(current, 10), "Transcribing audio", text
    if "[clipsai] detecting" in low:
        return max(current, 34), "Finding candidate moments", "ClipsAI is scanning the transcript."
    if "candidate clip(s) detected" in low:
        return max(current, 38), "Candidate moments found", text
    if "[ai] analyzing top" in low:
        return max(current, 40), "Qwen is analyzing clips", text
    m = re.search(r"\[ai\]\s+batch\s+(\d+)\s*/\s*(\d+)", low)
    if m:
        b, total = int(m.group(1)), max(1, int(m.group(2)))
        pct = 40 + int((b - 1) / total * 22)
        return max(current, min(62, pct)), f"Qwen is evaluating Batch {b}/{total}", "Local Ollama analysis can take a while on 8B/14B models."
    if "[ollama] calling" in low:
        return max(current, 41), "Qwen is generating the editorial decision", "Ollama request is in progress…"
    if "[ollama] ok" in low:
        return max(current, 45), "Qwen response received", text
    if "[ai] retry" in low or "retry candidate" in low:
        return max(current, 50), "Qwen is refining a candidate", text
    if "[ok] selected candidate" in low:
        return max(current, 64), "Selecting final moments", text
    if "rejected by qwen" in low or "checking candidate" in low:
        return max(current, 63), "Validating selected moments", text

    global _PROGRESS_CLIP_CONTEXT
    if "[start]" in low or "processing video" in low:
        _PROGRESS_CLIP_CONTEXT = {"cur": 1, "total": 1}

    m_clip = re.search(r"\[(\d+)/(\d+)\]\s+rendering short\s+#(\d+)", low)
    if m_clip:
        c_cur = int(m_clip.group(1))
        c_tot = max(1, int(m_clip.group(2)))
        _PROGRESS_CLIP_CONTEXT = {"cur": c_cur, "total": c_tot}
        base_pct = 65 + int((c_cur - 1) / c_tot * 33)
        return max(current, base_pct), f"Rendering Short {c_cur} of {c_tot}", f"Starting render for Short #{m_clip.group(3)}"

    ctx = _PROGRESS_CLIP_CONTEXT
    cur_c, tot_c = ctx.get("cur", 1), ctx.get("total", 1)
    clip_base = 65 + (cur_c - 1) / tot_c * 33.0
    clip_step = 33.0 / tot_c

    if "[1/5] trim" in low:
        pct = int(clip_base + 0.15 * clip_step)
        return max(current, pct), f"Rendering Short {cur_c} of {tot_c} (1/5: Trim)", text
    if "[2/5] resize" in low:
        pct = int(clip_base + 0.35 * clip_step)
        return max(current, pct), f"Rendering Short {cur_c} of {tot_c} (2/5: Vertical Reframe)", text
    if "[3/5] render dynamic" in low or "[captions]" in low:
        pct = int(clip_base + 0.60 * clip_step)
        return max(current, pct), f"Rendering Short {cur_c} of {tot_c} (3/5: Dynamic Captions)", text
    if "[4/5] generating" in low or "[title]" in low:
        pct = int(clip_base + 0.85 * clip_step)
        return max(current, pct), f"Rendering Short {cur_c} of {tot_c} (4/5: AI Title)", text
    if "[5/5] saved" in low or "metadata" in low:
        pct = int(clip_base + 0.95 * clip_step)
        return max(current, pct), f"Rendering Short {cur_c} of {tot_c} (5/5: Metadata)", text
    if "[done]" in low:
        pct = int(clip_base + 1.00 * clip_step)
        stage_name = f"Short {cur_c} of {tot_c} complete" if cur_c < tot_c else "All Shorts rendered"
        return max(current, pct), stage_name, text
    if "success!" in low:
        return 100, "All Shorts completed", text
    if "[fatal]" in low or "[error]" in low:
        return current, "Pipeline error", text
    # An unrecognised line is not a stage. Keep whatever stage we were on and
    # let the log carry the detail, rather than flashing a library message.
    return current, current_stage or "Working…", text[:240]


def _ollama_base_url() -> str:
    """Normalize OLLAMA_URL to the Ollama server root.

    The pipeline itself uses /api/chat, so users sometimes have
    OLLAMA_URL set to http://localhost:11434/api/chat.  The UI model
    discovery needs the server root before appending /api/tags.
    """
    value = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
    if not value:
        return "http://localhost:11434"

    # OLLAMA_URL is commonly configured as the generation endpoint. Parse it
    # rather than appending to it, so /api/tags never becomes /api/chat/api/tags.
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    for suffix in ("/api/chat", "/api/generate", "/api/tags"):
        if path.lower().endswith(suffix):
            path = path[:-len(suffix)].rstrip("/")
            break
    normalized = urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")
    return normalized or "http://localhost:11434"


def _ollama_candidates() -> list[str]:
    """Return local Ollama server candidates, preferring configured values."""
    candidates: list[str] = []
    for raw in (os.getenv("OLLAMA_URL", ""), os.getenv("OLLAMA_HOST", ""), os.getenv("OLLAMA_API_BASE", "")):
        raw = (raw or "").strip()
        if raw:
            try:
                base = _ollama_base_url() if raw == os.getenv("OLLAMA_URL", "") else raw.rstrip("/")
                if base and base not in candidates:
                    candidates.append(base)
            except Exception:
                pass
    for base in ("http://127.0.0.1:11434", "http://localhost:11434"):
        if base not in candidates:
            candidates.append(base)
    return candidates


def _find_ollama_exe() -> str | None:
    """Find ollama executable across PATH, standard Windows install locations, user profiles, and registry."""
    # 1. PATH lookup
    binary = shutil.which("ollama") or shutil.which("ollama.exe")
    if binary and os.path.isfile(binary):
        return binary

    # 2. Well-known Windows paths
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("SystemDrive", "C:"), r"\Program Files\Ollama\ollama.exe"),
        os.path.join(os.environ.get("SystemDrive", "C:"), r"\Program Files (x86)\Ollama\ollama.exe"),
        str(ROOT / "ollama.exe"),
        str(ROOT / "tools" / "ollama.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c

    # 3. Windows Registry lookup
    try:
        import winreg
        for root_key in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in (
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Ollama",
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Ollama",
                r"Software\Ollama",
            ):
                try:
                    with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ) as k:
                        for val_name in ("InstallLocation", "Path", "InstallDir", "DisplayIcon"):
                            try:
                                val, _ = winreg.QueryValueEx(k, val_name)
                                if val:
                                    p = str(val).strip('"')
                                    if p.lower().endswith(".exe") and os.path.isfile(p):
                                        return p
                                    exe_p = os.path.join(p, "ollama.exe")
                                    if os.path.isfile(exe_p):
                                        return exe_p
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        pass

    # 4. Search all user profiles under SystemDrive:\Users
    try:
        users_dir = os.path.join(os.environ.get("SystemDrive", "C:"), r"\Users")
        if os.path.isdir(users_dir):
            for u in os.listdir(users_dir):
                cand = os.path.join(users_dir, u, "AppData", "Local", "Programs", "Ollama", "ollama.exe")
                if os.path.isfile(cand):
                    return cand
    except Exception:
        pass

    return None


def _scan_store_manifests(store_dir: str) -> list[dict]:
    """Inspect an Ollama store directory directly on disk and parse all installed models with sizes."""
    models = []
    seen = set()
    for sub in ("manifests", "manifests-v2"):
        base = os.path.join(store_dir, sub)
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                mf = os.path.join(root, f)
                rel = os.path.relpath(mf, base).replace("\\", "/")
                parts = [p for p in rel.split("/") if p]
                if len(parts) >= 2:
                    tag = parts[-1]
                    model = parts[-2]
                    if len(parts) >= 3 and parts[-3] not in ("library", "registry.ollama.ai", "ollama.com"):
                        full_name = f"{parts[-3]}/{model}:{tag}"
                    else:
                        full_name = f"{model}:{tag}"

                    if full_name in seen:
                        continue
                    seen.add(full_name)

                    size_bytes = 0
                    try:
                        with open(mf, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                            layers = data.get("layers", [])
                            size_bytes = sum(l.get("size", 0) for l in layers if isinstance(l, dict))
                    except Exception:
                        pass

                    size_str = f"{size_bytes / (1024**3):.1f} GB" if size_bytes > 0 else ""
                    models.append({"name": full_name, "size": size_str, "bytes": size_bytes, "store": store_dir})
    return models


def _read_models_from_all_stores() -> list[dict]:
    """Scan all local stores and return a unified list of detected installed models."""
    stores = _scan_for_local_ollama_model_stores()
    all_models: list[dict] = []
    seen_names = set()
    for s in stores:
        for m in _scan_store_manifests(s):
            if m["name"] not in seen_names:
                seen_names.add(m["name"])
                all_models.append(m)
    return all_models


def _try_start_ollama(models_dir: str | None = None, force: bool = False) -> bool:
    """Best-effort local Ollama startup; never blocks the web app."""
    global _OLLAMA_AUTOSTART_ATTEMPTED
    if _OLLAMA_AUTOSTART_ATTEMPTED and not force:
        return False
    _OLLAMA_AUTOSTART_ATTEMPTED = True

    binary = _find_ollama_exe()
    if not binary:
        print("[Ollama] Auto-start skipped: ollama executable not found on PC.")
        return False

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()

    if not models_dir:
        models_dir = env.get("OLLAMA_MODELS")
        if not models_dir:
            stores = _scan_for_local_ollama_model_stores()
            if stores:
                models_dir = stores[0]

    if models_dir:
        env["OLLAMA_MODELS"] = models_dir
        os.environ["OLLAMA_MODELS"] = models_dir

    try:
        ol_proc = subprocess.Popen(
            [binary, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=creationflags, start_new_session=True
        )
        if ol_proc and ol_proc.pid:
            _STARTED_OLLAMA_PIDS.append(ol_proc.pid)
        print(f"[Ollama] Auto-started 'ollama serve' via {binary} (pid={getattr(ol_proc, 'pid', '?')}, models: {models_dir or 'default'})")
        return True
    except Exception as exc:
        print(f"[Ollama] Auto-start failed: {type(exc).__name__}: {exc}")
        return False


def _discover_ollama_models() -> tuple[list[str], str | None]:
    """Discover Ollama models with localhost/127.0.0.1 fallback, disk inspection fallback, and auto-start."""
    global OLLAMA_RUNTIME_BASE_URL
    last_error = "Ollama is not reachable."

    for attempt in range(2):
        for base in _ollama_candidates():
            try:
                version_req = urllib.request.Request(f"{base}/api/version", headers={"Accept": "application/json"})
                with urllib.request.urlopen(version_req, timeout=2.0) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                tags_req = urllib.request.Request(f"{base}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(tags_req, timeout=4.0) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
                if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                    last_error = f"Ollama at {base} returned an unexpected /api/tags response."
                    continue
                models = [str(x.get("name")) for x in data["models"] if isinstance(x, dict) and x.get("name")]
                if models:
                    OLLAMA_RUNTIME_BASE_URL = base
                    return models, None

                # HTTP connected but returned 0 models: check disk manifests before giving up!
                disk_models = [m["name"] for m in _read_models_from_all_stores()]
                if disk_models:
                    OLLAMA_RUNTIME_BASE_URL = base
                    return disk_models, None

                OLLAMA_RUNTIME_BASE_URL = base
                return [], f"Ollama is running at {base}, but no models are installed."
            except Exception as exc:
                last_error = f"{base}: {type(exc).__name__}: {exc}"

        if attempt == 0:
            _try_start_ollama(force=True)
            import time
            time.sleep(1.2)

    # Fallback when HTTP fails: check local disk stores directly!
    disk_models = [m["name"] for m in _read_models_from_all_stores()]
    if disk_models:
        # We found models on disk! Try to ensure Ollama server is starting up in background
        _try_start_ollama(force=True)
        return disk_models, None

    print(f"[Ollama] Model discovery failed: {last_error}")
    return [], f"Ollama unavailable. Tried localhost:11434 and 127.0.0.1:11434. {last_error}"


def _ollama_models() -> list[str]:
    """Compatibility wrapper for callers that only need the model names."""
    models, _error = _discover_ollama_models()
    return models


def _default_model(models: list[str]) -> str:
    for preferred in ("qwen3:8b", "qwen3:4b", "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:latest", "qwen:latest", "qwen3:14b"):
        if preferred in models:
            return preferred
    qwen = [m for m in models if m.lower().startswith("qwen")]
    return qwen[0] if qwen else (models[0] if models else "")


def _scan_for_local_ollama_model_stores() -> list[str]:
    """Scan common locations, environment variables, registry, and local drives for Ollama model stores."""
    found: list[str] = []

    def check_candidate(cand: str | None) -> None:
        if not cand:
            return
        try:
            cand_str = cand.strip()
            clean = os.path.abspath(os.path.expanduser(cand_str))
        except Exception:
            return
        if clean in found or not os.path.isdir(clean):
            return
        blobs = os.path.join(clean, "blobs")
        manifests = os.path.join(clean, "manifests")
        manifests_v2 = os.path.join(clean, "manifests-v2")
        if (os.path.isdir(blobs) and os.listdir(blobs)) or os.path.isdir(manifests) or os.path.isdir(manifests_v2):
            found.append(clean)

    # 1. Environment variable & .env
    check_candidate(os.environ.get("OLLAMA_MODELS"))

    # 2. Windows registry
    try:
        import winreg
        for rk in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (r"Environment", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"):
                try:
                    with winreg.OpenKey(rk, sub, 0, winreg.KEY_READ) as k:
                        val, _ = winreg.QueryValueEx(k, "OLLAMA_MODELS")
                        check_candidate(val)
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Known paths (Dynamic user home & localappdata across all users)
    known_paths = [
        os.path.expanduser(r"~/.ollama/models"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".ollama", "models"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Ollama", "models"),
        os.path.join(os.environ.get("APPDATA", ""), "Ollama", "models"),
        str(ROOT / "models"),
        str(ROOT / ".ollama" / "models"),
        str(USER_DATA_DIR / "models"),
    ]
    for kp in known_paths:
        check_candidate(kp)

    # Search all users under SystemDrive:\Users
    try:
        users_dir = os.path.join(os.environ.get("SystemDrive", "C:"), r"\Users")
        if os.path.isdir(users_dir):
            for u in os.listdir(users_dir):
                check_candidate(os.path.join(users_dir, u, ".ollama", "models"))
                check_candidate(os.path.join(users_dir, u, "AppData", "Local", "Ollama", "models"))
    except Exception:
        pass

    # 4. Drive scan across all available drives
    import string
    for letter in string.ascii_uppercase:
        drive_root = f"{letter}:\\"
        if not os.path.exists(drive_root):
            continue
        subpaths = [
            r"models llma\Ollama\models",
            r"models llma\models",
            r"Ollama\models",
            r".ollama\models",
            r"ollama_models",
            r"models\Ollama",
            r"models",
        ]
        for sub in subpaths:
            cand = os.path.join(drive_root, sub)
            check_candidate(cand)

    return found


def _restart_ollama_with_models_dir(models_dir: str) -> bool:
    """Safely restart local Ollama pointing directly to the given models directory."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=5)
    except Exception:
        pass
    import time
    time.sleep(1)

    binary = _find_ollama_exe()
    if not binary or not os.path.exists(binary):
        return False

    env = os.environ.copy()
    env["OLLAMA_MODELS"] = models_dir
    os.environ["OLLAMA_MODELS"] = models_dir
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen([binary, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, creationflags=creationflags, start_new_session=True)
        return True
    except Exception as exc:
        print(f"[Ollama] Failed to restart serve: {exc}")
        return False


def _scan_and_recover_ollama_models() -> tuple[list[str], str | None, str | None]:
    """Scan local storage for Ollama models, activate the store, start Ollama, and refresh."""
    models, _ = _discover_ollama_models()
    if models:
        return models, os.environ.get("OLLAMA_MODELS"), None

    stores = _scan_for_local_ollama_model_stores()
    if not stores:
        # Check if ollama binary exists anyway
        exe = _find_ollama_exe()
        if exe:
            _try_start_ollama(force=True)
            return [], None, "Ollama is installed and running, but no models were downloaded yet."
        return [], None, "No Ollama models or executable found on your computer."

    for store in stores:
        resolved = store
        try:
            resolved = os.path.realpath(store)
        except Exception:
            pass

        blobs_dir = os.path.join(resolved, "blobs")
        manifests_dir = os.path.join(resolved, "manifests")
        manifests_v2 = os.path.join(resolved, "manifests-v2")
        if not os.path.isdir(blobs_dir) and not os.path.isdir(manifests_dir) and not os.path.isdir(manifests_v2):
            continue

        os.environ["OLLAMA_MODELS"] = resolved
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, "OLLAMA_MODELS", 0, winreg.REG_SZ, resolved)
        except Exception:
            pass

        # Update local .env
        try:
            env_file = ROOT / ".env"
            content = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
            if "OLLAMA_MODELS=" in content:
                content = re.sub(r"OLLAMA_MODELS=.*", f"OLLAMA_MODELS={resolved}", content)
            else:
                content += f"\nOLLAMA_MODELS={resolved}\n"
            env_file.write_text(content.strip() + "\n", encoding="utf-8")
        except Exception:
            pass

        _restart_ollama_with_models_dir(resolved)
        import time
        for _ in range(6):
            time.sleep(1)
            models, _ = _discover_ollama_models()
            if models:
                return models, resolved, None

        # Even if HTTP tags hasn't caught up, read manifests from this store!
        disk_mods = [m["name"] for m in _scan_store_manifests(resolved)]
        if disk_mods:
            return disk_mods, resolved, None

    return [], None, "Scanned local drives but could not find working Ollama model manifests."


_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _normalize_youtube_url(value: str) -> str | None:
    """Validate a supported YouTube video URL and return its canonical watch URL."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None

    if (parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc
            or parsed.username is not None or parsed.password is not None or port is not None):
        return None

    youtube_hosts = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
    short_hosts = {"youtu.be", "www.youtu.be"}
    if host in short_hosts:
        parts = [part for part in parsed.path.split("/") if part]
        video_id = parts[0] if len(parts) == 1 else ""
    elif host in youtube_hosts and parsed.path.rstrip("/") == "/watch":
        ids = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        video_id = ids[0] if len(ids) == 1 else ""
    elif host in youtube_hosts:
        parts = [part for part in parsed.path.split("/") if part]
        video_id = parts[1] if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"} else ""
    else:
        return None

    if not _YOUTUBE_VIDEO_ID.fullmatch(video_id):
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _is_youtube_url(value: str) -> bool:
    """Compatibility predicate for supported YouTube video URLs."""
    return _normalize_youtube_url(value) is not None


def _normalize_import_url(value: str, platform: str = "") -> tuple[str, str] | None:
    """Validate YouTube, Twitch, or Kick video/clip URLs and return (url, platform)."""
    yt_url = _normalize_youtube_url(value)
    if yt_url is not None:
        return yt_url, "youtube"
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None

    if (parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc
            or parsed.username is not None or parsed.password is not None or port is not None):
        return None

    twitch_hosts = {"twitch.tv", "www.twitch.tv", "m.twitch.tv", "clips.twitch.tv"}
    kick_hosts = {"kick.com", "www.kick.com"}
    path_parts = [p for p in parsed.path.split("/") if p]
    if host in twitch_hosts and path_parts:
        return raw, "twitch"
    if host in kick_hosts and path_parts:
        return raw, "kick"
    return None


def _yt_dlp_command() -> list[str] | None:
    """Locate yt-dlp without tying the video pipeline to a global Python."""
    runtime = runtime_python()
    if runtime is not None:
        return [str(runtime), "-m", "yt_dlp"]
    try:
        import yt_dlp  # type: ignore # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass
    binary = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if binary:
        return [binary]
    bundled = ROOT / "yt-dlp.exe"
    if bundled.is_file():
        return [str(bundled)]
    return None



def _ffmpeg_path() -> str:
    bundled = ROOT / "tools" / "ffmpeg" / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    from shutil import which
    found = which("ffmpeg")
    if found:
        return found
    raise RuntimeError("FFmpeg was not found.")


def _ensure_video_has_audio(target: Path) -> Path:
    """Ensure video has an audio track; if silent/video-only, mux a silent audio track so ClipsAI never fails."""
    if not target or not target.is_file():
        return target
    try:
        ffmpeg_bin = _ffmpeg_path()
        ffprobe_bin = str(Path(ffmpeg_bin).with_name("ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"))
        probe = _run_hidden(
            [ffprobe_bin, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(target)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False
        )
        if probe.returncode == 0 and "audio" in probe.stdout.lower():
            return target
        # Video is missing audio track. Mux silent audio stream.
        temp_out = target.with_name(f"{target.stem}_audio_fixed{target.suffix}")
        mux = _run_hidden(
            [
                ffmpeg_bin, "-hide_banner", "-y",
                "-i", str(target),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
                str(temp_out),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False
        )
        if mux.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 0:
            target.unlink(missing_ok=True)
            temp_out.rename(target)
    except Exception as e:
        logger.warning("Failed ensuring audio stream for %s: %s", target.name, e)
    return target


def _media_duration_seconds(path_value: str) -> float:
    """Return the duration of a media file in seconds, or 0.0 when unknown."""
    p = Path(path_value or "")
    if not p.name or not p.exists():
        return 0.0
    try:
        proc = _run_hidden(
            [_ffmpeg_path(), "-i", str(p)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _hex6(value: str, default: str = "#FFFFFF") -> str:
    v = (value or default).strip().lstrip("#")
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        v = default.lstrip("#")
    return v.upper()


def _ffmpeg_color(value: str, opacity: int = 100) -> str:
    alpha = max(0, min(255, round(max(0, min(100, opacity)) * 2.55)))
    return f"0x{_hex6(value)}@{alpha/255:.3f}"


def _position_expr(position: str, margin: int, item_w: str = "w", item_h: str = "h") -> tuple[str, str]:
    m = str(max(0, margin))
    if position == "top-left": return m, m
    if position == "top-center": return f"(W-{item_w})/2", m
    if position == "top-right": return f"W-{item_w}-{m}", m
    if position == "center-left": return m, f"(H-{item_h})/2"
    if position == "center": return f"(W-{item_w})/2", f"(H-{item_h})/2"
    if position == "center-right": return f"W-{item_w}-{m}", f"(H-{item_h})/2"
    if position == "bottom-left": return m, f"H-{item_h}-{m}"
    if position == "bottom-center": return f"(W-{item_w})/2", f"H-{item_h}-{m}"
    return f"W-{item_w}-{m}", f"H-{item_h}-{m}"


def _resolve_logo(path_value: str, job_dir: Path | None = None) -> str | None:
    val = (path_value or "").strip().strip('"')
    if val.startswith("data:image/") and job_dir:
        try:
            branding_dir = job_dir / "branding"
            branding_dir.mkdir(parents=True, exist_ok=True)
            import base64
            _, encoded = val.split(",", 1)
            target = branding_dir / "logo.png"
            target.write_bytes(base64.b64decode(encoded))
            return str(target)
        except Exception:
            pass

    if job_dir:
        branding_dir = job_dir / "branding"
        if branding_dir.is_dir():
            for ext in ("*.png", "*.webp", "*.jpg", "*.jpeg"):
                found = sorted(branding_dir.glob(ext))
                if found:
                    return str(found[0])

    if not val:
        return None

    p = Path(val)
    if p.is_file():
        return str(p)
    if (ROOT / p).is_file():
        return str(ROOT / p)
    if (USER_DATA_DIR / p).is_file():
        return str(USER_DATA_DIR / p)
    if p.is_dir():
        for ext in ("*.png", "*.webp", "*.jpg", "*.jpeg"):
            found = sorted(p.glob(ext))
            if found:
                return str(found[0])
    return None


def _font_path_for_editor(font_name: str) -> str | None:
    mapping = {
        "Arial": r"C:\Windows\Fonts\arial.ttf",
        "Arial Black": r"C:\Windows\Fonts\ariblk.ttf",
        "Segoe UI": r"C:\Windows\Fonts\segoeui.ttf",
        "Segoe UI Black": r"C:\Windows\Fonts\seguibl.ttf",
        "Impact": r"C:\Windows\Fonts\impact.ttf",
        "Tahoma": r"C:\Windows\Fonts\tahoma.ttf",
        "Trebuchet MS": r"C:\Windows\Fonts\trebuc.ttf",
        "Verdana": r"C:\Windows\Fonts\verdana.ttf",
        "Calibri": r"C:\Windows\Fonts\calibri.ttf",
        "Aptos": r"C:\Windows\Fonts\aptos.ttf",
    }
    p = mapping.get(font_name)
    if p and Path(p).exists():
        return p
    p = r"C:\Windows\Fonts\arialbd.ttf"
    return p if Path(p).exists() else None


def _ffmpeg_filter_path(path_value: str) -> str:
    """Escape a Windows path for use inside an FFmpeg filter option."""
    value = os.path.abspath(path_value).replace("\\", "/")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def _render_transparent_watermark_image(
    text: str,
    output_png_path: str,
    opacity_pct: int = 35,
    pos_preset: str = "center",
    x_pct: float = 50.0,
    y_pct: float = 50.0,
    font_size_pct: int = 6,
    angle: int = -20,
    color: str = "#FFFFFF",
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> str:
    """Generate a 1080x1920 RGBA transparent image with rotated, styled watermark text."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return ""

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    font_size = max(24, round(canvas_w * font_size_pct / 100))

    font = None
    for font_name in ["Montserrat-ExtraBold.ttf", "Montserrat Extra Bold.ttf", "arialbd.ttf", "arial.ttf", "seguiemb.ttf", "segoeui.ttf"]:
        try:
            for root in [str(ROOT / "fonts"), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]:
                fp = os.path.join(root, font_name)
                if os.path.isfile(fp):
                    font = ImageFont.truetype(fp, font_size)
                    break
            if font:
                break
        except Exception:
            pass
    if not font:
        try:
            font = ImageFont.load_default()
        except Exception:
            pass

    c = color.lstrip('#')
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    else:
        r, g, b = 255, 255, 255
    alpha = max(0, min(255, int(255 * (opacity_pct / 100.0))))
    fill_color = (r, g, b, alpha)

    dummy_draw = ImageDraw.Draw(img)
    try:
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw = len(text) * font_size * 0.6
        th = font_size
        bbox = (0, 0, tw, th)

    margin = 50
    preset_positions = {
        "top-left": (margin, margin),
        "top-center": ((canvas_w - tw) // 2, margin),
        "top-right": (canvas_w - tw - margin, margin),
        "center-left": (margin, (canvas_h - th) // 2),
        "center": ((canvas_w - tw) // 2, (canvas_h - th) // 2),
        "center-right": (canvas_w - tw - margin, (canvas_h - th) // 2),
        "lower-middle": ((canvas_w - tw) // 2, int(canvas_h * 0.75)),
        "bottom-left": (margin, canvas_h - th - margin - 100),
        "bottom-center": ((canvas_w - tw) // 2, canvas_h - th - margin - 100),
        "bottom-right": (canvas_w - tw - margin, canvas_h - th - margin - 100),
        "custom": (int((canvas_w - tw) * (x_pct / 100.0)), int((canvas_h - th) * (y_pct / 100.0))),
    }
    target_pos = preset_positions.get(pos_preset, preset_positions["center"])

    if angle != 0:
        pad = 24
        txt_img = Image.new("RGBA", (int(tw) + pad * 2, int(th) + pad * 2), (0, 0, 0, 0))
        txt_draw = ImageDraw.Draw(txt_img)
        txt_draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill_color)
        resample_filter = getattr(Image, "Resampling", Image)
        resample_mode = getattr(resample_filter, "BICUBIC", 3)
        rotate_fn: Any = getattr(txt_img, "rotate")
        rotated_txt = rotate_fn(angle, expand=True, resample=resample_mode)
        rw, rh = rotated_txt.size
        cx = target_pos[0] + tw // 2
        cy = target_pos[1] + th // 2
        img.paste(rotated_txt, (int(cx - rw // 2), int(cy - rh // 2)), rotated_txt)
    else:
        dummy_draw.text((target_pos[0] - bbox[0], target_pos[1] - bbox[1]), text, font=font, fill=fill_color)

    os.makedirs(os.path.dirname(os.path.abspath(output_png_path)), exist_ok=True)
    img.save(output_png_path, "PNG")
    return output_png_path


def apply_branding_to_file(input_video: str, output_video: str, branding: dict[str, Any], font_name: str = "Arial") -> None:
    """Apply logo/watermark text/custom text branding and camera/framing adjustments to an already-rendered Short without rerunning AI."""
    ffmpeg = _ffmpeg_path()
    video_parent_job = Path(input_video).parent.parent if Path(input_video).parent.name == "output" else Path(input_video).parent
    logo = _resolve_logo(str(branding.get("logo_path", "")), video_parent_job) if branding.get("logo_enabled") else None
    text = str(branding.get("text", "")).strip() if branding.get("text_enabled") else ""
    wm_text = str(branding.get("watermark_text", "")).strip() if branding.get("watermark_text_enabled") else ""
    raw_framing = branding.get("framing")
    framing: dict[str, Any] = raw_framing if isinstance(raw_framing, dict) else {}
    pan_x = max(-50.0, min(50.0, float(framing.get("pan_x", 0.0))))
    pan_y = max(-50.0, min(50.0, float(framing.get("pan_y", 0.0))))
    zoom = max(1.0, min(2.5, float(framing.get("zoom", 1.0))))
    has_framing = (abs(pan_x) > 0.01 or abs(pan_y) > 0.01 or zoom > 1.01)

    prof = get_upscale_profile(str(branding.get("upscale_quality", "high")))
    scale_flags = prof["scale_flags"]
    unsharp = f",{prof['unsharp']}" if prof.get("unsharp") else ""

    if not logo and not text and not wm_text and not has_framing:
        shutil.copy2(input_video, output_video)
        return

    filters: list[str] = []
    inputs = ["-i", input_video]
    current = "0:v"

    if has_framing:
        crop_w = max(320, min(1080, int(1080 / zoom)))
        crop_h = max(568, min(1920, int(1920 / zoom)))
        # Make dimensions even
        crop_w -= (crop_w % 2)
        crop_h -= (crop_h % 2)
        center_x = (1080 - crop_w) / 2.0
        center_y = (1920 - crop_h) / 2.0
        offset_x = (pan_x / 50.0) * center_x
        offset_y = (pan_y / 50.0) * center_y
        x_pos = max(0, min(1080 - crop_w, int(center_x + offset_x)))
        y_pos = max(0, min(1920 - crop_h, int(center_y + offset_y)))
        filters.append(f"[{current}]crop={crop_w}:{crop_h}:{x_pos}:{y_pos},scale=1080:1920:flags={scale_flags}{unsharp}[vframed]")
        current = "vframed"
    if logo:
        inputs += ["-i", logo]
        size = max(1, min(50, int(branding.get("logo_size", 8))))
        opacity = max(0, min(100, int(branding.get("logo_opacity", 80))))
        pos = str(branding.get("logo_position", "top-right"))
        margin = max(0, min(500, int(branding.get("logo_margin", 40))))
        if pos == "custom":
            x = f"(W-w)*{max(0,min(100,float(branding.get('logo_x',92))))/100:.6f}"
            y = f"(H-h)*{max(0,min(100,float(branding.get('logo_y',8))))/100:.6f}"
        else:
            x, y = _position_expr(pos, margin)
        logo_w = max(32, round(1080 * size / 100))
        chain = "[1:v]format=rgba"
        if branding.get("logo_bg_remove"):
            bg = _hex6(str(branding.get("logo_bg_color", "#9B5CFF")))
            sim = max(0.01, min(1.0, float(branding.get("logo_bg_similarity", 0.22))))
            blend = max(0.0, min(1.0, float(branding.get("logo_bg_blend", 0.05))))
            chain += f",colorkey=0x{bg}:{sim:.3f}:{blend:.3f}"
        chain += f",colorchannelmixer=aa={opacity/100:.3f},scale={logo_w}:-1[wm]"
        filters.append(chain)
        filters.append(f"[{current}][wm]overlay=x={x}:y={y}:format=auto[vlogo]")
        current = "vlogo"

    wm_png_file = None
    if wm_text:
        wm_png_file = str(Path(output_video).with_name(f"_wm_text_{int(time.time()*1000)}.png"))
        _render_transparent_watermark_image(
            text=wm_text,
            output_png_path=wm_png_file,
            opacity_pct=max(0, min(100, int(branding.get("watermark_text_opacity", 35)))),
            pos_preset=str(branding.get("watermark_text_position", "center")),
            x_pct=max(0, min(100, float(branding.get("watermark_text_x", 50)))),
            y_pct=max(0, min(100, float(branding.get("watermark_text_y", 50)))),
            font_size_pct=max(3, min(20, int(branding.get("watermark_text_size", 6)))),
            angle=max(-45, min(45, int(branding.get("watermark_text_angle", -20)))),
            color=str(branding.get("watermark_text_color", "#FFFFFF")),
        )
        wm_idx = len(inputs) // 2
        inputs += ["-i", wm_png_file]
        filters.append(f"[{current}][{wm_idx}:v]overlay=0:0:format=auto[v_wm]")
        current = "v_wm"

    temp_text = None
    if text:
        temp_text = str(Path(output_video).with_name("_editor_text.txt"))
        Path(temp_text).write_text(text, encoding="utf-8")
        pos = str(branding.get("text_position", "bottom-center"))
        margin = max(20, min(500, int(branding.get("text_margin", 110))))
        if pos == "custom":
            x = f"(w-tw)*{max(0,min(100,float(branding.get('text_x',50))))/100:.6f}"
            y = f"(h-th)*{max(0,min(100,float(branding.get('text_y',75))))/100:.6f}"
        else:
            x, y = _position_expr(pos, margin, "tw", "th")
        size = max(2, min(25, int(branding.get("text_size", 6))))
        fs = max(34, round(1080 * size / 100))
        font_path = _font_path_for_editor(font_name)
        font_expr = f":fontfile='{_ffmpeg_filter_path(font_path)}'" if font_path else ""
        box = 1 if branding.get("text_bg_enabled") else 0
        boxcolor = _ffmpeg_color(str(branding.get("text_bg_color", "#000000")), int(branding.get("text_bg_opacity", 65)))
        color = _hex6(str(branding.get("text_color", "#FFFFFF")))
        tf = _ffmpeg_filter_path(temp_text)
        t_start = max(0.0, float(branding.get("text_start_time", 0.0)))
        t_end = float(branding.get("text_end_time", 0.0))
        enable_expr = f":enable='between(t,{t_start:.3f},{t_end:.3f})'" if (t_end > t_start) else ""
        filters.append(f"[{current}]drawtext=textfile='{tf}':fontsize={fs}:fontcolor=0x{color}{font_expr}:x={x}:y={y}:box={box}:boxcolor={boxcolor}:boxborderw=18:fix_bounds=true{enable_expr}[vtext]")
        current = "vtext"

    fc = ";".join(filters)
    try:
        from clipify.platform.gpu_manager import get_ffmpeg_video_encoder_flags
        enc_flags = get_ffmpeg_video_encoder_flags(bitrate=prof.get("video_bitrate", "12M"), preset=prof.get("preset", "fast"), crf=int(prof.get("crf", 18)))
    except Exception:
        enc_flags = [
            "-c:v", "libx264", "-preset", prof["preset"], "-crf", prof["crf"],
            "-b:v", prof["video_bitrate"], "-maxrate", prof["maxrate"], "-bufsize", prof["bufsize"],
            "-pix_fmt", "yuv420p"
        ]

    cmd = [
        ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", f"[{current}]", "-map", "0:a?",
        *enc_flags,
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", output_video
    ]
    proc = _run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if temp_text:
        try: Path(temp_text).unlink()
        except OSError: pass
    if wm_png_file:
        try: Path(wm_png_file).unlink()
        except OSError: pass
    if proc.returncode != 0 or not Path(output_video).exists() or Path(output_video).stat().st_size < 1024:
        raise RuntimeError(f"Branding render failed: {proc.stderr[-1800:]}")


def _is_cuda_available() -> bool:
    try:
        _ensure_cuda_dlls()
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return True
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _pipeline_command(input_dir: Path) -> list[str]:
    """Build the command that runs the pipeline for one job.

    Prefers running main.py with the local AI runtime python environment if available,
    falling back to compiled main.exe if main.py is absent.
    """
    python_bin = sys.executable
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    runtime_env = os.environ.get("CLIPPEDAI_RUNTIME")
    if runtime_env and (Path(runtime_env) / "Scripts" / "python.exe").is_file():
        python_bin = str(Path(runtime_env) / "Scripts" / "python.exe")
    elif (ROOT / "runtime" / "Scripts" / "python.exe").is_file():
        python_bin = str(ROOT / "runtime" / "Scripts" / "python.exe")
    elif venv_python.is_file():
        python_bin = str(venv_python)
    elif Path(r"L:\tester\runtime\Scripts\python.exe").is_file():
        python_bin = str(Path(r"L:\tester\runtime\Scripts\python.exe"))

    main_py = ROOT / "main.py"
    if main_py.is_file():
        return [python_bin, "-u", str(main_py)]

    compiled_main = ROOT / "main.exe"
    if compiled_main.is_file():
        return [str(compiled_main)]
    return [python_bin, "-u", "main.py"]


def run_job(
job_id: str, mode: str, clips: int, model: str, font: str, min_duration: int, max_duration: int, branding: dict[str, Any], split_screen: bool = False, fast_whisper: bool = True, gaming_split: bool = True, split_ratio: int = 50, upscale_quality: str = "high", language: str = "auto", disable_captions: bool = False, use_existing_transcription: bool = True) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job["status"] = "running"
        job["progress"] = 2
        job["stage"] = "Starting Clipify AI"
        job["detail"] = "Launching the local pipeline…"
        job["stage_started"] = __import__("time").time()
        job["events"] = []
        job["outputs"] = []

    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    env = os.environ.copy()
    ffmpeg_dir = str(Path(_ffmpeg_path()).parent)
    current_path = env.get("PATH", "")
    if ffmpeg_dir not in current_path:
        env["PATH"] = f"{ffmpeg_dir};{current_path}"
    env.update({
        "PYTHONUNBUFFERED": "1",
        "CLIPPEDAI_INPUT_DIR": str(input_dir),
        "CLIPPEDAI_OUTPUT_DIR": str(output_dir),
        "CLIPPEDAI_MODE": mode,
        "CLIPPEDAI_UPSCALE_QUALITY": upscale_quality,
        "OLLAMA_MODEL": model,
        "OLLAMA_URL": OLLAMA_RUNTIME_BASE_URL or _ollama_base_url(),
        "CLIPPEDAI_FONT": font,
        "MIN_CLIP_DURATION": str(min_duration),
        "MAX_CLIP_DURATION": str(max_duration),
        "PREFERRED_MIN_CLIP_DURATION": str(min_duration),
        "PREFERRED_MAX_CLIP_DURATION": str(max_duration),
        "CLIPPEDAI_WATERMARK_ENABLED": "1" if branding.get("logo_enabled") else "0",
        "CLIPPEDAI_WATERMARK_PATH": str(branding.get("logo_path", "")),
        "CLIPPEDAI_WATERMARK_POSITION": str(branding.get("logo_position", "top-right")),
        "CLIPPEDAI_WATERMARK_SIZE": str(branding.get("logo_size", 8)),
        "CLIPPEDAI_WATERMARK_OPACITY": str(branding.get("logo_opacity", 80)),
        "CLIPPEDAI_WATERMARK_MARGIN": str(branding.get("logo_margin", 40)),
        "CLIPPEDAI_WATERMARK_X": str(branding.get("logo_x", 92)),
        "CLIPPEDAI_WATERMARK_Y": str(branding.get("logo_y", 8)),
        "CLIPPEDAI_WATERMARK_BG_REMOVE": "1" if branding.get("logo_bg_remove") else "0",
        "CLIPPEDAI_WATERMARK_BG_COLOR": str(branding.get("logo_bg_color", "#9B5CFF")),
        "CLIPPEDAI_WATERMARK_BG_SIMILARITY": str(branding.get("logo_bg_similarity", 0.22)),
        "CLIPPEDAI_WATERMARK_BG_BLEND": str(branding.get("logo_bg_blend", 0.05)),
        "CLIPPEDAI_TEXT_ENABLED": "1" if branding.get("text_enabled") else "0",
        "CLIPPEDAI_TEXT": str(branding.get("text", "")),
        "CLIPPEDAI_TEXT_POSITION": str(branding.get("text_position", "bottom-center")),
        "CLIPPEDAI_TEXT_SIZE": str(branding.get("text_size", 6)),
        "CLIPPEDAI_TEXT_COLOR": str(branding.get("text_color", "#FFFFFF")),
        "CLIPPEDAI_TEXT_BG_ENABLED": "1" if branding.get("text_bg_enabled") else "0",
        "CLIPPEDAI_TEXT_BG_COLOR": str(branding.get("text_bg_color", "#000000")),
        "CLIPPEDAI_TEXT_BG_OPACITY": str(branding.get("text_bg_opacity", 65)),
        "CLIPPEDAI_TEXT_MARGIN": str(branding.get("text_margin", 110)),
        "CLIPPEDAI_TEXT_X": str(branding.get("text_x", 50)),
        "CLIPPEDAI_TEXT_Y": str(branding.get("text_y", 75)),
        "CLIPPEDAI_PREMIUM_CAPTIONS": "1" if branding.get("premium_captions", True) else "0",
        "CLIPPEDAI_SITUATIONAL_CUES": "1" if branding.get("situational_cues", True) else "0",
        "CLIPPEDAI_CAPTION_PRESET": str(branding.get("caption_preset", "center_seam" if (gaming_split or split_screen) else "lower_safe")),
        "CLIPPEDAI_CAPTION_ACCENT": str(branding.get("caption_accent", "gold_yellow")),
        "CLIPPEDAI_CAPTION_MARGIN_V": str(branding.get("caption_margin_v", "920" if (gaming_split or split_screen) else "300")),
        "CLIPPEDAI_CAPTION_FONT_SIZE": str(branding.get("caption_font_size", "48")),
        "CLIPPEDAI_CAPTION_Y_PCT": str(branding.get("caption_y_pct", "0")),
        "CLIPPEDAI_WATERMARK_TEXT_ENABLED": "1" if branding.get("watermark_text_enabled") else "0",
        "CLIPPEDAI_WATERMARK_TEXT": str(branding.get("watermark_text", "")),
        "CLIPPEDAI_WATERMARK_TEXT_POSITION": str(branding.get("watermark_text_position", "center")),
        "CLIPPEDAI_WATERMARK_TEXT_SIZE": str(branding.get("watermark_text_size", 6)),
        "CLIPPEDAI_WATERMARK_TEXT_OPACITY": str(branding.get("watermark_text_opacity", 35)),
        "CLIPPEDAI_WATERMARK_TEXT_ANGLE": str(branding.get("watermark_text_angle", -20)),
        "CLIPPEDAI_WATERMARK_TEXT_COLOR": str(branding.get("watermark_text_color", "#FFFFFF")),
        "CLIPPEDAI_WATERMARK_TEXT_X": str(branding.get("watermark_text_x", 50)),
        "CLIPPEDAI_WATERMARK_TEXT_Y": str(branding.get("watermark_text_y", 50)),
        "CLIPPEDAI_SPLIT_SCREEN": "1" if split_screen else "0",
        "CLIPPEDAI_GAMING_SPLIT": "1" if gaming_split else "0",
        "CLIPPEDAI_SPLIT_RATIO": str(split_ratio),
        "CLIPPEDAI_FAST_WHISPER": "1" if fast_whisper else "0",
        "CLIPPEDAI_USE_EXISTING_TRANSCRIPTION": "1" if use_existing_transcription else "0",
        "TRANSCRIPTION_MODEL": os.getenv("TRANSCRIPTION_MODEL", "tiny" if fast_whisper else ("medium" if _is_cuda_available() else "base")),
        "CLIPPEDAI_ALLOW_FALLBACK": "1",
        "HF_HUB_OFFLINE": os.getenv("HF_HUB_OFFLINE", "0"),
        "KMP_DUPLICATE_LIB_OK": "TRUE",
        "OMP_STACKSIZE": "64M",
        "KMP_STACKSIZE": "64M",
        "DISABLE_CAPTIONS": "1" if (disable_captions or font == "none" or branding.get("disable_captions") or not branding.get("captions_enabled", True)) else "0",
        "WHISPERX_THREADS": os.getenv("WHISPERX_THREADS", str(max(4, os.cpu_count() or 4)) if fast_whisper else "4"),
        "WHISPERX_LANGUAGE": ("hi" if str(language if (language and language != "auto") else (branding.get("language") if (branding.get("language") and branding.get("language") != "auto") else (os.getenv("WHISPERX_LANGUAGE") or "auto"))).strip().lower() in ("hinglish", "hi-en") else str(language if (language and language != "auto") else (branding.get("language") if (branding.get("language") and branding.get("language") != "auto") else (os.getenv("WHISPERX_LANGUAGE") or "auto"))).strip().lower()),
        "OMP_NUM_THREADS": str(max(4, os.cpu_count() or 4)) if fast_whisper else "4",
        "MKL_NUM_THREADS": str(max(4, os.cpu_count() or 4)) if fast_whisper else "4",
        "OPENBLAS_NUM_THREADS": str(max(4, os.cpu_count() or 4)) if fast_whisper else "4",
        "VECLIB_MAXIMUM_THREADS": str(max(4, os.cpu_count() or 4)) if fast_whisper else "4",
        "NUMEXPR_NUM_THREADS": str(max(4, os.cpu_count() or 4)) if fast_whisper else "4",
        "PYTHONWARNINGS": "ignore::UserWarning:pyannote.audio.core.io,ignore:.*torchcodec.*",
    })
    diagnostic_log = job_dir / "diagnostics" / "qwen-decisions.jsonl"
    diagnostic_log.parent.mkdir(parents=True, exist_ok=True)
    env["CLIPPEDAI_QWEN_DIAGNOSTIC_LOG"] = str(diagnostic_log)
    input_videos: list[Path] = []
    if input_dir.is_dir():
        input_videos = [
            p for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
        ]
    if input_videos and all(p.stat().st_size < 1024 for p in input_videos):
        msg = (
            "The input video file is incomplete or empty (< 1 KB). "
            "The download may still be running, was interrupted, or disk space was exhausted. Please wait for the download to finish or re-import the video."
        )
        with jobs_lock:
            job["status"] = "error"
            job["stage"] = "Corrupted or Empty Video"
            job["detail"] = msg
            job["events"].append({"kind": "error", "message": msg})
        emit(job_id, "error", msg)
        return

    cmd = [*_pipeline_command(input_dir), "--auto", "--clips", str(clips),
           "--min-duration", str(min_duration), "--max-duration", str(max_duration)]
    emit(job_id, "log", f"Starting {mode} mode with {model or 'built-in heuristic AI'}; captions: {font}…")
    for hw_msg in _get_hardware_status_lines():
        emit(job_id, "log", hw_msg)

    heartbeat_stop = threading.Event()
    def heartbeat() -> None:
        import time
        while not heartbeat_stop.wait(2.0):
            with jobs_lock:
                job = jobs.get(job_id)
                if not job or job.get("status") != "running":
                    continue
                elapsed = max(0, int(time.time() - float(job.get("stage_started", time.time()))))
                stage = job.get("stage", "Working…")
                detail = job.get("detail", "")
                cur_prog = job.get("progress", 0)
                if elapsed >= 3:
                    detail = f"{detail.split(' · ')[0]} · stage time {elapsed}s"
                if stage == "Transcribing audio" and cur_prog >= 10 and cur_prog < 30:
                    m, s = divmod(elapsed, 60)
                    dur = float(job.get("video_duration") or 0.0)
                    dm, ds = divmod(int(dur), 60) if dur > 0 else (0, 0)
                    dur_str = f" · {dm}m {ds}s video" if dur > 0 else ""
                    speech_pct = job.get("speech_progress")
                    if speech_pct is not None:
                        speech_pct = float(speech_pct)
                        if speech_pct >= 99.5:
                            step_prog = 30
                            cur_prog = max(cur_prog, step_prog)
                            job["progress"] = cur_prog
                            job["stage"] = "Aligning word timestamps"
                            detail = f"Aligning word timestamps with speech ({m}m {s}s elapsed · phoneme matching)"
                        else:
                            step_prog = min(29, 10 + int((speech_pct / 100.0) * 19))
                            cur_prog = max(cur_prog, step_prog)
                            job["progress"] = cur_prog
                            if elapsed > 4 and speech_pct > 1.0:
                                rate = speech_pct / max(1, elapsed)
                                rem_s = int((100.0 - speech_pct) / max(0.01, rate))
                                rm, rs = divmod(rem_s, 60)
                                eta_str = f" · ~{rm}m {rs}s remaining" if rm > 0 else f" · ~{rs}s remaining"
                            else:
                                eta_str = ""
                            detail = f"Transcribing audio: {speech_pct:.0f}% of speech processed ({m}m {s}s elapsed{dur_str}{eta_str})"
                    elif dur > 0:
                        est_total = max(30, int(dur * 0.40))
                        pct_chunk = min(99, max(1, int((elapsed / max(1, est_total)) * 100)))
                        rem_s = max(5, est_total - elapsed)
                        rm, rs = divmod(rem_s, 60)
                        step_prog = min(28, 10 + int((pct_chunk / 100.0) * 18))
                        cur_prog = max(cur_prog, step_prog)
                        job["progress"] = cur_prog
                        detail = f"Transcribing audio: ~{pct_chunk}% ({m}m {s}s elapsed{dur_str} · ~{rm}m remaining)"
                    else:
                        step_prog = min(28, 10 + int(elapsed / 25))
                        cur_prog = max(cur_prog, step_prog)
                        job["progress"] = cur_prog
                        last_detail = job.get("detail", "")
                        if "%" in last_detail:
                            detail = f"{last_detail.split(' · ')[0]} · {m}m {s}s elapsed"
                        else:
                            detail = f"Transcribing audio ({m}m {s}s elapsed · analyzing speech)"
                elif stage == "Aligning word timestamps":
                    align_pct = job.get("alignment_progress")
                    m, s = divmod(elapsed, 60)
                    if align_pct is not None:
                        align_pct = float(align_pct)
                        step_prog = min(34, 30 + int((align_pct / 100.0) * 4))
                        cur_prog = max(cur_prog, step_prog)
                        job["progress"] = cur_prog
                        detail = f"Aligning word timestamps: {align_pct:.0f}% (phoneme matching · stage time {elapsed}s)"
                    else:
                        detail = f"Aligning word timestamps with speech ({m}m {s}s elapsed · phoneme matching)"
                job["detail"] = detail
            emit(job_id, "progress", {
                "progress": job.get("progress", 0),
                "stage": job.get("stage", "Working…"),
                "detail": job.get("detail", ""),
            })

    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_hidden_creationflags(),
        )
        with jobs_lock:
            jobs[job_id]["pid"] = proc.pid
        threading.Thread(target=heartbeat, daemon=True).start()

        progress = 2
        stage = "Starting Clipify AI"
        prev_stage = stage
        recent_lines: list[str] = []
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if line:
                recent_lines.append(line)
                if len(recent_lines) > 200:
                    recent_lines.pop(0)
            if "video duration:" in line.lower():
                m_dur = re.search(r"video duration:\s*([\d\.]+)", line.lower())
                if m_dur:
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]["video_duration"] = float(m_dur.group(1))
            if "transcription progress:" in line.lower():
                m_prog = re.search(r"transcription progress:\s*([\d\.]+)%", line.lower())
                if m_prog:
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]["speech_progress"] = float(m_prog.group(1))
            if "alignment progress:" in line.lower():
                m_align = re.search(r"alignment progress:\s*([\d\.]+)%", line.lower())
                if m_align:
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]["alignment_progress"] = float(m_align.group(1))
            progress, stage, detail = progress_for_line(line, progress, stage)
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["progress"] = progress
                    jobs[job_id]["stage"] = stage
                    jobs[job_id]["detail"] = detail
                    if stage != prev_stage or "stage_started" not in jobs[job_id]:
                        jobs[job_id]["stage_started"] = __import__("time").time()
                        prev_stage = stage
            if line:
                emit(job_id, "log", line)

        return_code = proc.wait()
        outputs = []
        if output_dir.exists():
            video_files = [p for p in sorted(output_dir.iterdir()) if p.is_file() and p.suffix.lower() == ".mp4" and p.stat().st_size >= 1024]
            outputs = [p.name for p in video_files if not p.name.startswith("_tmp_") and not p.name.endswith("_with_subtitles.mp4") and not p.stem.endswith("_clean")]
            if not outputs:
                outputs = [p.name for p in video_files if p.name.endswith("_with_subtitles.mp4")]
        with jobs_lock:
            job = jobs[job_id]
            job["return_code"] = return_code
            job["outputs"] = outputs
            job["status"] = "done" if return_code == 0 and outputs else "error"
            job["progress"] = 100 if return_code == 0 and outputs else job["progress"]
            job["stage"] = "Finished" if return_code == 0 and outputs else "Pipeline stopped"
            job["detail"] = _pipeline_failure_detail(return_code, outputs, recent_lines)
        emit(job_id, "worker_exit", "Pipeline worker exited.",
             return_code=return_code, output_count=len(outputs), status=job["status"])
        if return_code == 0 and outputs:
            emit(job_id, "complete", f"Created {len(outputs)} professional Short(s).", progress=100, pipeline=True)
        else:
            emit(job_id, "error", job["detail"], return_code=return_code)
    except Exception as exc:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["stage"] = "Application error"
            jobs[job_id]["detail"] = str(exc)
            jobs[job_id]["error"] = str(exc)
        emit(job_id, "error", f"{type(exc).__name__}: {exc}")
    finally:
        heartbeat_stop.set()


@app.get("/")
def index():
    return render_template("index.html", modes=MODES)


@app.get("/narrate")
def narrate_page():
    return render_template("narrate.html")


@app.get("/live")
def live_studio_page():
    return render_template("live.html")


@app.get("/api/trending/<platform>")
def api_trending(platform: str):
    """
    Fetch trending live broadcasts and gameplay videos for YouTube, Twitch, and Kick.
    Supports ?q=<query> for live search across streams and gaming content.
    """
    q = request.args.get("q", "").strip()
    force_refresh = request.args.get("refresh", "").strip().lower() in ("1", "true", "yes")
    try:
        import trending_service
        plat = platform.lower().strip()
        if plat == "youtube":
            data = trending_service.get_youtube_trending(q, force_refresh=force_refresh)
        elif plat == "twitch":
            data = trending_service.get_twitch_trending(q, force_refresh=force_refresh)
        elif plat == "kick":
            data = trending_service.get_kick_trending(q, force_refresh=force_refresh)
        else:
            return jsonify({"error": f"Unknown platform '{platform}'", "live_streams": [], "gameplay_videos": []}), 400
        return jsonify(data)
    except Exception as ex:
        logger.exception("Error in /api/trending/%s: %s", platform, ex)
        return jsonify({
            "platform": platform,
            "error": str(ex),
            "live_streams": [],
            "gameplay_videos": []
        }), 500



def _get_live_studio_mgr():
    from live.studio_manager import get_live_manager
    python_bin = sys.executable
    try:
        pipeline_cmd = _pipeline_command(USER_DATA_DIR)
        if pipeline_cmd:
            python_bin = pipeline_cmd[0]
    except Exception:
        pass
    return get_live_manager(
        data_dir=USER_DATA_DIR,
        ffmpeg_bin=_ffmpeg_path(),
        python_bin=python_bin,
    )


@app.get("/api/live/status")
def live_status():
    mgr = _get_live_studio_mgr()
    return jsonify(mgr.get_status())


@app.post("/api/live/connect")
def live_connect():
    data = request.get_json(silent=True) or {}
    source_type = data.get("source_type", "youtube")
    source_url = data.get("source_url", "")
    auto_clip = bool(data.get("auto_clip", False))
    sensitivity = int(data.get("sensitivity", 5))
    buffer_minutes = int(data.get("buffer_minutes", 10))
    model_name = str(data.get("model_name", "qwen2.5:3b"))
    stream_quality = str(data.get("stream_quality", "1080p"))
    editing_prefs = {
        "auto_edit": bool(data.get("auto_edit", True)),
        "face_tracking": bool(data.get("face_tracking", True)),
        "gaming_layout": bool(data.get("gaming_layout", True)),
        "auto_captions": bool(data.get("auto_captions", True)),
        "auto_clip_interval": int(data.get("auto_clip_interval", 5)),
        "caption_style": str(data.get("caption_style", "highlight")),
        "caption_font": str(data.get("caption_font", "Montserrat Extra Bold")),
        "caption_language": str(data.get("caption_language", "en")),
        "background_style": str(data.get("background_style", "soft_blur")),
        "background_color": str(data.get("background_color", "#000000")),
        "custom_text": str(data.get("custom_text", "")),
        "custom_text_pos": str(data.get("custom_text_pos", "top-center")),
        "custom_text_color": str(data.get("custom_text_color", "#FFFFFF")),
        "ai_provider": str(data.get("ai_provider", os.getenv("CLIPPEDAI_AI_PROVIDER", "ollama"))),
        "hf_model": str(data.get("hf_model", os.getenv("CLIPPEDAI_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct"))),
    }

    mgr = _get_live_studio_mgr()
    ok, msg = mgr.start_session(
        source_type=source_type,
        source_url=source_url,
        auto_clip=auto_clip,
        sensitivity=sensitivity,
        buffer_minutes=buffer_minutes,
        model_name=model_name,
        stream_quality=stream_quality,
        editing_prefs=editing_prefs,
    )
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "message": msg, "status": mgr.get_status()})


@app.post("/api/live/preferences")
def live_preferences():
    data = request.get_json(silent=True) or {}
    mgr = _get_live_studio_mgr()
    updated = mgr.update_editing_prefs(data)
    return jsonify({"success": True, "editing_prefs": updated})


@app.post("/api/live/disconnect")
def live_disconnect():
    mgr = _get_live_studio_mgr()
    mgr.stop_session()
    return jsonify({"success": True, "status": mgr.get_status()})


@app.get("/api/live/clips")
def live_clips():
    mgr = _get_live_studio_mgr()
    mgr._load_saved_clips()
    return jsonify({"clips": mgr.get_clips()})


@app.post("/api/live/instant-clip")
def live_instant_clip():
    data = request.get_json(silent=True) or {}
    duration = int(data.get("duration", 30))
    mgr = _get_live_studio_mgr()
    clip = mgr.instant_clip(duration_sec=duration)
    if not clip:
        err_msg = getattr(mgr, "last_instant_clip_error", "") or "Failed generating instant clip. Ensure the stream is actively recording."
        return jsonify({"error": err_msg}), 400
    return jsonify({"success": True, "clip": clip})


@app.post("/api/live/batch-clip")
def live_batch_clip():
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 4))
    duration = int(data.get("duration", 30))
    mgr = _get_live_studio_mgr()
    if not mgr.session_active or not mgr.buffer:
        return jsonify({"error": "Failed generating batch clips. Ensure the stream is actively recording."}), 400

    threading.Thread(
        target=mgr.batch_clip,
        kwargs={"count": count, "duration_sec": duration},
        daemon=True,
    ).start()

    return jsonify({
        "success": True,
        "status": "started",
        "message": f"Started generating {count} Shorts ({duration}s each) in background. They will populate the gallery as rendered.",
    })


@app.delete("/api/live/clips/<clip_id>")
def live_delete_clip(clip_id: str):
    mgr = _get_live_studio_mgr()
    ok = mgr.delete_clip(clip_id)
    return jsonify({"success": ok})


@app.post("/api/live/clips/batch-delete")
def live_batch_delete_clips():
    data = request.get_json(silent=True) or {}
    clip_ids = data.get("clip_ids", [])
    if not isinstance(clip_ids, list) or not clip_ids:
        return jsonify({"error": "No clip IDs provided for batch deletion"}), 400
    mgr = _get_live_studio_mgr()
    deleted = mgr.delete_clips(clip_ids)
    return jsonify({"success": True, "deleted_count": deleted, "remaining_count": len(mgr.get_clips())})


@app.post("/api/live/clips/<clip_id>/update")
def live_update_clip(clip_id: str):
    data = request.get_json(silent=True) or {}
    mgr = _get_live_studio_mgr()
    ok = mgr.update_clip(clip_id, data)
    return jsonify({"success": ok})


@app.post("/api/live/clips/<clip_id>/generate-description")
def live_generate_clip_description(clip_id: str):
    mgr = _get_live_studio_mgr()
    res = mgr.generate_clip_description(clip_id)
    return jsonify(res)


@app.post("/api/live/clips/rank")
def live_rank_clips():
    data = request.get_json(silent=True) or {}
    top_n = int(data.get("top_n", 10))
    clip_ids = data.get("clip_ids")
    model_name = data.get("model_name")
    mgr = _get_live_studio_mgr()
    threading.Thread(
        target=mgr.rank_clips_ai,
        kwargs={"top_n": top_n, "clip_ids": clip_ids, "model_name": model_name},
        daemon=True,
    ).start()
    return jsonify({"success": True, "message": "AI clip ranking initiated"})


@app.get("/api/live/clips/rank/status")
def live_rank_status():
    mgr = _get_live_studio_mgr()
    return jsonify({
        "is_ranking": mgr.is_ranking,
        "logs": mgr.get_ranking_logs(),
        "ranked_clips": mgr.get_ranked_clips(),
    })


@app.get("/api/live/clips/ranked")
def live_ranked_clips():
    mgr = _get_live_studio_mgr()
    return jsonify({"ranked_clips": mgr.get_ranked_clips()})


@app.get("/api/live/transcript")
def live_transcript():
    mgr = _get_live_studio_mgr()
    return jsonify({"segments": mgr.get_recent_transcripts()})


@app.get("/api/live/console")
def live_console():
    mgr = _get_live_studio_mgr()
    return jsonify({"logs": mgr.get_console_logs()})


@app.get("/api/live/obs-config")
def live_obs_config():
    mgr = _get_live_studio_mgr()
    return jsonify(mgr.get_obs_config())


@app.get("/api/live/media/<path:filename>")
def live_media(filename: str):
    mgr = _get_live_studio_mgr()
    clips_dir = mgr.clips_dir
    return send_from_directory(str(clips_dir), filename)


@app.get("/api/live/preview-frame")
def live_preview_frame():
    mgr = _get_live_studio_mgr()
    preview_file = mgr.buffer_dir / "preview_current.jpg"
    if preview_file.exists() and preview_file.stat().st_size > 0:
        return send_file(str(preview_file), mimetype="image/jpeg", max_age=1)
    return ("", 204)


def _generate_thumbnail_file(video_path: Path, thumb_path: Path) -> bool:
    try:
        ff = _ffmpeg_path()
        if not ff or not video_path.exists():
            return False

        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        thumb_tmp = thumb_path.with_suffix(".tmp.jpg")

        # Extract 1 frame at 1s into video for an accurate preview
        cmd = [
            ff, "-y", "-ss", "1", "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=360:640:force_original_aspect_ratio=decrease",
            "-q:v", "4",
            str(thumb_tmp)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, creationflags=creationflags)
        if res.returncode != 0 or not thumb_tmp.exists() or thumb_tmp.stat().st_size == 0:
            cmd[3] = "0"
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, creationflags=creationflags)

        if res.returncode == 0 and thumb_tmp.exists() and thumb_tmp.stat().st_size > 0:
            thumb_tmp.replace(thumb_path)
            return True
        if thumb_tmp.exists():
            thumb_tmp.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def _prewarm_narrate_thumbnails(videos: list[dict[str, Any]]) -> None:
    """Pre-extract thumbnails in background for all clips in the library."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        def worker(v_info):
            clip_id = v_info.get("id")
            if not clip_id:
                return
            thumb_path = NARRATE_THUMBS / f"{clip_id}.jpg"
            if thumb_path.exists() and thumb_path.stat().st_size > 500:
                return
            target = NARRATE._find_video(clip_id)
            if target and target.exists():
                _generate_thumbnail_file(target, thumb_path)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(worker, videos))
    except Exception:
        pass


@app.get("/api/narrate/videos")
def narrate_videos():
    videos = NARRATE.scan_videos()
    folders = NARRATE.library_folders()
    if videos:
        threading.Thread(target=_prewarm_narrate_thumbnails, args=(videos,), daemon=True).start()
    return jsonify({
        "videos": videos,
        "folder_exists": bool(folders),
        "folder": str(NARRATE.default_library()),
        "folders": [str(folder) for folder in folders],
        "is_custom": NARRATE.has_custom_library(),
        "extra_clips_available": NARRATE.has_extra_clips(),
        "extra_clips_enabled": NARRATE.extra_clips_enabled(),
        "extra_clips_count": NARRATE.extra_clips_count(),
    })


_extra_download_state: dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "current_file": "",
    "downloaded_count": 0,
    "total_count": 0,
    "error": None,
}
_extra_download_lock = threading.Lock()


@app.post("/api/narrate/extra-clips")
def narrate_toggle_extra_clips():
    """Enable or disable the extra background clips (narrate download)."""
    try:
        data = request.get_json(silent=True) or {}
        enable = bool(data.get("enable", True))
        enabled = NARRATE.set_extra_clips_enabled(enable)
        videos = NARRATE.scan_videos()
        folders = NARRATE.library_folders()
        return jsonify({
            "ok": True,
            "extra_clips_available": NARRATE.has_extra_clips(),
            "extra_clips_enabled": enabled,
            "extra_clips_count": NARRATE.extra_clips_count(),
            "count": len(videos),
            "videos": videos,
            "folders": [str(folder) for folder in folders],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/narrate/download-extra")
def narrate_download_extra():
    """Download/install the additional background clips into the active library."""
    try:
        from narrate.pipeline import VIDEO_EXTENSIONS
    except ImportError:
        VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

    with _extra_download_lock:
        if _extra_download_state.get("status") == "downloading":
            return jsonify({"ok": True, "state": dict(_extra_download_state)})

        source_dir = NARRATE.extra_clips_folder()
        if not source_dir or not source_dir.is_dir():
            for candidate in [
                Path(r"L:\ClipifyAI\narrate download"),
                ROOT / "narrate download",
                USER_DATA_DIR / "narrate download",
            ]:
                if candidate.is_dir():
                    source_dir = candidate
                    break

        if not source_dir or not source_dir.is_dir():
            return jsonify({"ok": False, "error": "Additional clips folder not found on disk."}), 404

        target_dir = NARRATE.ensure_library()
        extra_files = [p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
        if not extra_files:
            return jsonify({"ok": False, "error": "No video clips found in additional clips folder."}), 404

        _extra_download_state.update({
            "status": "downloading",
            "progress": 0,
            "current_file": extra_files[0].name,
            "downloaded_count": 0,
            "total_count": len(extra_files),
            "error": None,
        })

    def worker():
        try:
            total = len(extra_files)
            for idx, src_file in enumerate(extra_files, start=1):
                dst_file = target_dir / src_file.name
                with _extra_download_lock:
                    _extra_download_state["current_file"] = src_file.name
                    _extra_download_state["downloaded_count"] = idx
                    _extra_download_state["progress"] = int((idx / total) * 100)
                if not dst_file.exists() or dst_file.stat().st_size != src_file.stat().st_size:
                    shutil.copy2(src_file, dst_file)
                import time
                time.sleep(0.03)

            NARRATE.set_extra_clips_enabled(True)
            with _extra_download_lock:
                _extra_download_state["status"] = "completed"
                _extra_download_state["progress"] = 100
                _extra_download_state["current_file"] = "Complete"
        except Exception as exc:
            with _extra_download_lock:
                _extra_download_state["status"] = "error"
                _extra_download_state["error"] = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "state": dict(_extra_download_state)})


@app.get("/api/narrate/download-extra-status")
def narrate_download_extra_status():
    with _extra_download_lock:
        state = dict(_extra_download_state)
    return jsonify({"ok": True, "state": state})


@app.post("/api/narrate/library")
def narrate_set_library():
    """Point the clip library at a folder the user chooses.

    Clips are the user's own footage, so they are never shipped with the
    product. Without this the only folders ever scanned were next to the
    executable, which an installed copy does not have, and the page could only
    ever say "No Narrate clips found".
    """
    data = request.get_json(silent=True) or {}
    raw = str(data.get("folder", "")).strip().strip('"')
    if not raw:
        # An empty request means "go back to the default folder", not "keep
        # whatever is remembered", so the stored choice has to be dropped.
        folder = NARRATE.reset_library()
        return jsonify({"ok": True, "folder": str(folder), "videos": NARRATE.scan_videos(),
                        "is_custom": False})

    candidate = Path(raw).expanduser()
    try:
        resolved = NARRATE.remember_library(candidate)
    except OSError as error:
        return jsonify({"ok": False, "error": f"Could not use that folder: {error}"}), 400
    videos = NARRATE.scan_videos()
    return jsonify({
        "ok": True,
        "folder": str(resolved),
        "videos": videos,
        "is_custom": NARRATE.has_custom_library(),
        "note": None if videos else "That folder has no video files in it yet.",
    })


def _prewarm_voice_previews(voices: list[dict[str, Any]]) -> None:
    preview_dir = JOBS / "_narrate_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for v in voices:
        vid = v.get("id")
        if not vid:
            continue
        try:
            create_tts(vid).preview(preview_dir)
        except Exception:
            pass


@app.get("/api/narrate/voices")
def narrate_voices():
    voices = available_voices()
    # Prewarm preview audio in background so clicking preview plays instantly
    if voices:
        threading.Thread(target=_prewarm_voice_previews, args=(voices,), daemon=True).start()
    engines = sorted({str(voice.get("engine", "")) for voice in voices if voice.get("engine")})
    return jsonify({
        "voices": voices,
        "engine": " + ".join(engines) if engines else "none",
        "engines": engines,
        "available": bool(voices),
    })


@app.post("/api/narrate/preview-voice")
def narrate_preview_voice():
    data = request.get_json(silent=True) or {}
    voice = str(data.get("voice", "")).strip()
    preview_dir = JOBS / "_narrate_previews"
    try:
        output = create_tts(voice).preview(preview_dir)
    except (ValueError, TTSUnavailable) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"url": f"/api/narrate/preview-media/{output.name}"})


@app.get("/api/narrate/preview-media/<path:filename>")
def narrate_preview_media(filename: str):
    return send_from_directory(JOBS / "_narrate_previews", Path(filename).name, as_attachment=False)


@app.post("/api/narrate/upload")
def narrate_upload():
    file = request.files.get("video")
    if not file or not file.filename or not is_allowed(file.filename):
        return jsonify({"error": "Choose a supported video file."}), 400
    library = NARRATE.ensure_library()
    target = library / (secure_filename(file.filename) or f"narrate_{uuid.uuid4().hex}.mp4")
    file.save(target)
    return jsonify({"ok": True, "video": target.name, "video_id": NARRATE.video_id(target), "folder": str(library)})


@app.get("/api/narrate/media/<path:filename>")
def narrate_media(filename: str):
    # Opaque clip IDs select an exact file across both library folders and
    # successful Clipify project exports. Unique legacy filenames still work.
    target = NARRATE._find_video(filename)
    if target is None:
        return jsonify({"error": "Narrate media not found."}), 404
    return send_from_directory(target.parent, target.name, as_attachment=False)


@app.get("/api/narrate/thumbnail/<clip_id>")
def narrate_thumbnail(clip_id: str):
    """Ultra-fast lightweight JPEG thumbnail for clip cards in the narrate picker."""
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", clip_id).strip()
    thumb_path = NARRATE_THUMBS / f"{clean_id}.jpg"
    if thumb_path.exists() and thumb_path.stat().st_size > 500:
        response = send_from_directory(thumb_path.parent, thumb_path.name, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    target = NARRATE._find_video(clip_id)
    if target is None:
        # Check by filename/stem
        for p in NARRATE._video_paths():
            if p.name == clip_id or p.stem == clip_id or NARRATE.video_id(p) == clip_id:
                target = p
                break

    if target and target.exists():
        if _generate_thumbnail_file(target, thumb_path):
            response = send_from_directory(thumb_path.parent, thumb_path.name, mimetype="image/jpeg")
            response.headers["Cache-Control"] = "public, max-age=86400"
            return response

    # Clean SVG fallback placeholder so <img> tags never render broken image icons
    svg_placeholder = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200" viewBox="0 0 360 200">'
        '<rect width="360" height="200" fill="#131d17"/>'
        '<circle cx="180" cy="90" r="28" fill="#243b2c"/>'
        '<polygon points="173,77 194,90 173,103" fill="#a3d9a5"/>'
        '<text x="180" y="145" text-anchor="middle" fill="#7ba380" font-family="sans-serif" font-size="13">Clip Preview</text>'
        '</svg>'
    )
    return Response(svg_placeholder, mimetype="image/svg+xml")


def _clean_ai_script(raw: str) -> str:
    """Clean LLM output so it produces clean spoken narration without markdown, labels, or stage directions."""
    text = raw or ""
    # Remove reasoning / think blocks
    text = re.sub(r"<think\b.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<think\b.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n\s*\n\s*(?:analysis|reasoning|thought process|thinking)\s*[:\-]*\n*.*?\n\s*\n", "\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    # Remove markdown code blocks
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text)
    text = text.replace("```", "")
    # Remove markdown formatting (*bold*, **bold**, _italic_, # Header)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = text.replace("`", "")
    # Remove bracketed stage directions e.g. [Laughs], [Music fades], [Sighs]
    text = re.sub(r"\[[^\]]*\]", "", text)
    # Remove parenthetical sound effects / directions e.g. (laughs), (dramatic pause)
    text = re.sub(r"\((?:pause|dramatic pause|laughs?|sighs?|giggles?|music cue|softly|loudly|whispers?|sound\s+effect)[^)]*\)", "", text, flags=re.IGNORECASE)
    # Remove speaker prefixes: "Narrator:", "Voiceover:", "Host:", "Speaker 1:", "Me:"
    text = re.sub(r"(?im)^\s*(?:narrator|voice(?:over)?|speaker\s*\d*|host|voice)\s*:\s*", "", text)
    # Remove title or metadata prefixes: "Title: ...", "Hook: ...", "Script: ..."
    text = re.sub(r"(?im)^\s*(?:title|script|hook|story|synopsis|metadata)\s*:\s*", "", text)
    # Remove conversational preamble like "Here is a script:" or "Sure, here's the story:"
    text = re.sub(r"(?im)^\s*(?:here is|here's|sure(?: thing)?[,!]|certainly[!]|okay[,!]|below is)\s+(?:a|the|your)?\s*(?:viral\s+)?(?:script|narration|story|take)[^\n.:]*[:.]?\s*", "", text)
    # Strip wrapping quotes
    text = text.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    return re.sub(r"\s+", " ", text).strip()


def _strip_reasoning_blocks(raw: str) -> str:
    return _clean_ai_script(raw)


def _script_is_complete(script: str) -> bool:
    text = _clean_ai_script(script)
    if not text:
        return False
    words = text.split()
    if len(words) < 15:
        return False
    return True


def _call_ollama_script_prompt(system_prompt: str, user_prompt: str, fallback: str, model: str = "") -> str:
    preferred_model = model.strip() or os.getenv("OLLAMA_MODEL", "qwen3:8b").strip()
    if not preferred_model:
        return fallback

    base_url = (OLLAMA_RUNTIME_BASE_URL or _ollama_base_url()).rstrip("/")
    for attempt in range(2):
        retry_note = (
            "\n\nRewrite the draft as complete plain spoken narration. Use at least 28 words, "
            "end with sentence punctuation, and include no headings, speaker labels, stage directions, "
            "or Markdown. Return only the narration."
            if attempt else ""
        )
        try:
            payload = json.dumps({
                "model": preferred_model,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0.85,
                    "top_p": 0.9,
                },
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + retry_note},
                ],
            }).encode("utf-8")
            request = urllib.request.Request(
                f"{base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            raw_content = str(data.get("message", {}).get("content", "") or "")
            cleaned = _strip_reasoning_blocks(raw_content)
            if _script_is_complete(cleaned):
                if not re.search(r"[.!?]$", cleaned):
                    cleaned += "."
                return cleaned
        except Exception:
            break
    return fallback


def _prompt_fallback(prompt: str, style: str, duration: int = 30) -> str:
    prompt_lower = prompt.lower()
    subject = prompt.strip().rstrip(".!?")
    subject = re.sub(r"\([^)]*\)", "", subject).strip()
    subject = re.sub(r"\b(make it|write|create|generate|actually happened|a dramatic story about|a story about)\b", "", subject, flags=re.I).strip(" ,:-")
    if not subject:
        subject = "that wild plan"

    viral_templates = [
        f"Nobody expected {subject} to blow up the way it did. It started as an ordinary moment, but then one mistake flipped everything upside down. By the time anyone tried to intervene, it was already too late to stop the chain reaction. In the end, what seemed like a disaster turned out to be the most memorable thing that happened all year.",
        f"If you told me yesterday that {subject} would end like this, I would have laughed in your face. The entire setup was supposed to be completely foolproof. But five seconds in, the first unexpected thing happened, and the panic was instantly contagious. It took everyone watching by complete surprise, and honestly, the payoff could not have been better.",
        f"Here is what they never tell you about {subject}. From the outside, everything looked totally calm and under control. But behind the scenes, every single choice was making the situation ten times more chaotic. When the final reveal dropped, the entire room erupted. You truly could not make this up.",
    ]
    funny_templates = [
        f"I thought {subject} was going to be an easy win, but reality had completely different plans. The first mistake was subtle enough to ignore, but the second one made it impossible to pretend I knew what I was doing. Everyone was watching in dead silence right until the punchline hit. Now none of us can talk about it without bursting out laughing.",
        f"There is having confidence, and then there is whatever happened with {subject}. I walked in thinking this would be my proudest achievement. Instead, one tiny blunder triggered a comedy of errors so ridiculous that even the people trying to help ended up laughing with tears in their eyes.",
    ]
    dramatic_templates = [
        f"The strangest thing about {subject} is that nobody saw the warning signs until it was already happening. The stakes were quietly climbing with every second, and one sudden move changed the entire outcome. When the truth finally came out, nobody looked at the situation the same way again.",
        f"It all came down to a single split-second choice during {subject}. One person noticed the detail everyone else missed, and that alone changed everything. The tension in the room was unbelievable, but the ending delivered exactly what everyone had been waiting for.",
    ]

    if style == "funny":
        return random.choice(funny_templates)
    elif style == "dramatic":
        return random.choice(dramatic_templates)
    return random.choice(viral_templates)


def _fit_script_to_duration(script: str, duration: int) -> str:
    target_words = max(35, round(duration * 3.2))
    words = script.split()
    if len(words) >= target_words:
        return script.strip()
    expansion = (
        "That unexpected moment caught everyone completely off guard.",
        "It turned a simple situation into something nobody could stop talking about.",
        "And honestly, that is the exact reason why everyone wanted to replay it.",
        "Nobody expected the chain reaction that followed immediately after.",
        "In seconds, what started as a quiet test became the highlight of the entire day.",
        "Everyone watching immediately knew this was something truly unforgettable.",
        "The reaction from the crowd made the entire experience even better.",
        "It proves that the best moments always happen when you least expect them.",
        "You could feel the energy in the room shift the second that happened.",
        "By the time it was over, everyone agreed it was worth watching again.",
    )
    result = script.strip()
    while len(result.split()) < target_words:
        for sentence in expansion:
            if len(result.split()) >= target_words:
                break
            result = f"{result} {sentence}".strip()
    return result


def _format_script_sentences(script: str) -> str:
    clean = re.sub(r"\s+", " ", script or "").strip()
    if not clean:
        return ""
    sentences = re.findall(r".*?(?:[.!?]+(?=\s|$)|$)", clean)
    return "\n".join(sentence.strip() for sentence in sentences if sentence.strip())


def _random_script() -> str:
    options = [
        "Hook: I just found the wildest thing about this clip.\n\nThis is the exact moment where everything changes. The timing is brutal, the reaction is priceless, and the whole room went silent. You had to see it happen to believe it.",
        "Okay, this is the funniest part of the whole run.\n\nThe plan was simple, the timing was terrible, and somehow it became the best mistake of the day. The reaction says it all. This is exactly why we never trust the easy route.",
        "This is the moment everything clicks.\n\nThe setup is perfect, the pressure is rising, and then the payoff lands exactly when it should. That one second changes the whole vibe of the clip.",
        "I did not expect this to work, and that is why it is so good.\n\nThe angle was bad, the move was messy, and somehow it turned into the cleanest highlight of the whole session.",
        "This is the kind of moment that makes you stop the video and replay it.\n\nThe reaction, the timing, the panic — it all lands in one perfect second. That is why this clip deserves a replay.",
        "There was no way this should have worked.\n\nBut it did, and now it is the highlight of the entire run. The rhythm, the timing, the chaos — all of it came together in one impossible moment.",
    ]
    return random.choice(options)


@app.post("/api/narrate/improve")
def narrate_improve():
    data = request.get_json(silent=True) or {}
    script = str(data.get("script", "")).strip()
    if not script:
        return jsonify({"error": "Enter a script first."}), 400
    improved = script
    improved = _call_ollama_script_prompt(
        "Improve narration scripts for hook, pacing, clarity and retention. Keep it concise, energetic, and in a single natural voice. Return only the revised script without preamble.",
        script,
        script,
    )
    return jsonify({"improved": improved, "used_ai": improved != script})


@app.post("/api/narrate/script")
def narrate_generate_script():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    model = str(data.get("model", "")).strip()
    try:
        duration = max(15, min(60, int(data.get("duration", 30))))
    except (TypeError, ValueError):
        duration = 30
    if not prompt:
        return jsonify({"error": "Give the AI a prompt like a funny joke, dramatic hook, or story setup."}), 400
    prompt_lower = prompt.lower()
    target_words = round(duration * 2.65)
    pacing = f"Aim for roughly {target_words} words ({duration} seconds narration). Speak directly to the viewer with punchy sentences. Return ONLY the spoken narration."
    if any(word in prompt_lower for word in ("funny", "joke", "laugh", "roast", "chaos", "meme", "comedy")):
        system_prompt = (
            "You are a viral comedy scriptwriter for vertical video (Shorts/TikTok/Reels). "
            "Write a hilarious, highly entertaining spoken monologue or story based on the user's idea. "
            "Hook the viewer in the very first sentence. Use fast pacing, sharp comedic timing, and an absurd or funny punchline. "
            "Return ONLY the spoken narration. Do NOT include titles, scene directions, bracketed actions, narrator labels, or hashtags. "
            f"{pacing}"
        )
    elif any(word in prompt_lower for word in ("dramatic", "story", "tension", "reveal", "mystery", "shocking", "creepy")):
        system_prompt = (
            "You are a viral storyteller for vertical video (Shorts/TikTok/Reels). "
            "Write an intense, suspenseful spoken story based on the user's idea. "
            "Grab attention in the first 3 seconds with a thrilling or mysterious hook. Build tension quickly and hit a shocking twist or payoff at the end. "
            "Return ONLY the spoken narration. Do NOT include titles, scene directions, bracketed actions, narrator labels, or hashtags. "
            f"{pacing}"
        )
    else:
        system_prompt = (
            "You are an elite short-form viral scriptwriter for YouTube Shorts, TikTok, and Instagram Reels. "
            "Write a dynamic, high-retention, addictive script based on the user's prompt. "
            "Open immediately with an irresistible curiosity hook in sentence one. Tell an unpredictable, engaging story that keeps viewers watching until the last second. "
            "Deliver a satisfying or surprising final payoff. "
            "Return ONLY the spoken narration. Do NOT include titles, bullet points, scene directions, speaker labels, or markdown formatting. "
            f"{pacing}"
        )

    style = "funny" if "funny" in prompt_lower or "joke" in prompt_lower else "dramatic" if any(word in prompt_lower for word in ("dramatic", "story", "tension", "reveal", "wow", "epic")) else "viral"
    fallback = _prompt_fallback(prompt, style, duration)
    script = _call_ollama_script_prompt(system_prompt, prompt, fallback, model)
    fitted = _fit_script_to_duration(script, duration)
    return jsonify({"script": _format_script_sentences(fitted), "used_ai": script.strip() != fallback.strip()})


@app.post("/api/narrate/random-script")
def narrate_random_script():
    data = request.get_json(silent=True) or {}
    try:
        duration = max(30, min(60, int(data.get("target_duration", 30))))
    except (TypeError, ValueError):
        duration = 30
    target_words = round(duration * 3.2)
    fallback = _fit_script_to_duration(_random_script(), duration)
    script = _call_ollama_script_prompt(
        f"Create a fresh, original narration for a random short-form video idea that lasts about {duration} seconds. Write approximately {target_words}-{target_words + 12} words at a natural pace of about 3.2 words per second. Write only spoken prose. Do not include a title, hook label, narrator or voiceover label, stage direction, music cue, bracketed text, or Markdown. Finish with sentence punctuation.",
        f"Generate a surprising, replay-worthy narration with a strong hook and payoff, around {target_words}-{target_words + 12} words. Make this variation different from previous ones. Return only complete narration prose.",
        fallback,
    )
    fitted = _fit_script_to_duration(script, duration)
    return jsonify({"script": fitted.strip(), "used_ai": script.strip() != fallback.strip(),
                    "target_duration": duration, "target_word_count": target_words})


@app.post("/api/narrate/generate")
def narrate_generate():
    data = request.get_json(silent=True) or {}
    script = str(data.get("script", "")).strip()
    voice = str(data.get("voice", "")).strip()
    video = str(data.get("video", "")).strip()
    try:
        speed = int(data.get("speed", 0))
    except (TypeError, ValueError):
        speed = 0
    try:
        target_duration = max(30.0, min(60.0, float(data.get("target_duration", 0) or 0)))
    except (TypeError, ValueError):
        target_duration = 0.0
    caption_mode = str(data.get("caption_mode", "sync-yellow"))
    if caption_mode not in {"sync-yellow", "selective-yellow", "color-words"}:
        caption_mode = "sync-yellow"
    try:
        caption_size = max(64, min(120, int(data.get("caption_size", 96))))
    except (TypeError, ValueError):
        caption_size = 96
    if not script or not voice or not video:
        return jsonify({"error": "Script, voice and background video are required."}), 400
    if NARRATE._find_video(video) is None:
        return jsonify({"error": "Choose a valid Narrate background clip."}), 400
    job_id = f"narrate_{uuid.uuid4().hex[:12]}"
    job_dir = JOBS / job_id
    with narrate_jobs_lock:
        narrate_jobs[job_id] = {"id": job_id, "status": "running", "progress": 0, "stage": "Starting Narrate", "detail": "", "output": None}

    def worker() -> None:
        def report(progress: int, stage: str) -> None:
            with narrate_jobs_lock:
                if job_id in narrate_jobs:
                    narrate_jobs[job_id].update(progress=progress, stage=stage, detail="Working locally")
        try:
            result = NARRATE.render(job_dir, script, voice, video, speed=speed, caption_mode=caption_mode,
                                    caption_size=caption_size,
                                    target_duration=target_duration or None, progress=report)
            with narrate_jobs_lock:
                narrate_jobs[job_id].update(status="done", progress=100, stage="Complete", output=result["filename"], duration=result["duration"], metadata=result["metadata"])
        except Exception as exc:
            with narrate_jobs_lock:
                narrate_jobs[job_id].update(status="error", stage="Narrate failed", error=str(exc))

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.get("/api/narrate/status/<job_id>")
def narrate_status(job_id: str):
    with narrate_jobs_lock:
        job = narrate_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Narrate job not found."}), 404
        return jsonify(dict(job))


@app.get("/api/narrate/result-media/<job_id>/<path:filename>")
def narrate_result_media(job_id: str, filename: str):
    target_dir = _safe_job_directory(job_id)
    if target_dir is None:
        return jsonify({"error": "Narrate result not found."}), 404
    return send_from_directory(target_dir, Path(filename).name, as_attachment=False)


@app.get("/api/narrate/history")
def narrate_history():
    history = []
    for job_dir in JOBS.glob("narrate_*"):
        if not job_dir.is_dir():
            continue
        metadata_path = job_dir / "narrated_short.json"
        video_path = job_dir / "narrated_short.mp4"
        if not metadata_path.exists() or not video_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
        history.append({
            "id": job_dir.name,
            "title": str(metadata.get("title") or "Narrated Short"),
            "voice": str(metadata.get("voice") or ""),
            "duration": float(metadata.get("duration") or 0),
            "created": video_path.stat().st_mtime,
            "url": f"/api/narrate/result-media/{job_dir.name}/{video_path.name}",
        })
    history.sort(key=lambda item: item["created"], reverse=True)
    return jsonify({"history": history})


@app.delete("/api/narrate/history/<job_id>")
def delete_narrate_history(job_id: str):
    target_dir = _safe_job_directory(job_id)
    if target_dir is None or not job_id.startswith("narrate_"):
        return jsonify({"error": "Invalid Narrate history item."}), 400
    if not target_dir.is_dir():
        return jsonify({"error": "Narrate history item not found."}), 404
    shutil.rmtree(target_dir)
    with narrate_jobs_lock:
        narrate_jobs.pop(job_id, None)
    return jsonify({"ok": True})


def _finalize_uploaded_job(job_id: str, safe_name: str, orig_filename: str, input_dir: Path, target: Path) -> dict:
    """Register a completed uploaded video (single or chunked) as a ready job."""
    target = _ensure_video_has_audio(target)
    target_stem = Path(safe_name).stem
    candidate_stems = [
        target_stem,
        target_stem.replace("_", " "),
        target_stem.replace(" ", "_"),
        Path(orig_filename).stem,
    ]
    for c_stem in candidate_stems:
        cached = USER_DATA_DIR / "input" / f"{c_stem}_transcription.pkl"
        if cached.is_file():
            dest_pkl = input_dir / f"{target_stem}_transcription.pkl"
            try:
                shutil.copy2(cached, dest_pkl)
            except Exception:
                pass
            break

    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "filename": safe_name,
            "status": "uploaded",
            "progress": 0,
            "stage": "Video ready",
            "detail": "Choose the editing mode, model and caption font.",
            "events": [],
            "outputs": [],
        }
    return {"ok": True, "job_id": job_id, "filename": safe_name}


@app.post("/api/upload-chunk")
def upload_chunk():
    """Stream large local video files in chunks directly to the job input folder."""
    orig_filename = (request.args.get("filename") or request.headers.get("X-File-Name") or "").strip()
    if not orig_filename:
        return jsonify({"error": "Missing filename."}), 400
    if not is_allowed(orig_filename):
        return jsonify({"error": "Unsupported video format."}), 400

    job_id = (request.args.get("job_id") or "").strip() or uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", job_id):
        return jsonify({"error": "Invalid job id."}), 400

    offset = int(request.args.get("offset", "0") or 0)
    is_last = request.args.get("is_last", "0") == "1"

    safe_name = secure_filename(orig_filename) or f"video_{job_id}.mp4"
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / safe_name

    mode = "wb" if offset == 0 else "r+b"
    if mode == "r+b" and not target.exists():
        mode = "wb"
    try:
        with open(target, mode) as fh:
            if offset > 0:
                fh.seek(offset)
            while True:
                buf = request.stream.read(1024 * 1024)
                if not buf:
                    break
                fh.write(buf)
    except OSError as exc:
        resp = jsonify({"error": f"Disk write error during upload: {exc}"})
        resp.headers["Connection"] = "close"
        return resp, 507

    if is_last:
        res = _finalize_uploaded_job(job_id, safe_name, orig_filename, input_dir, target)
        resp = jsonify(res)
        resp.headers["Connection"] = "close"
        return resp

    resp = jsonify({"ok": True, "job_id": job_id, "filename": safe_name, "received_offset": offset})
    resp.headers["Connection"] = "close"
    return resp


@app.post("/api/upload")
def upload():
    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"error": "Choose a video first."}), 400
    if not is_allowed(file.filename):
        return jsonify({"error": "Unsupported video format."}), 400

    job_id = uuid.uuid4().hex[:12]
    safe_name = secure_filename(file.filename) or f"video_{job_id}.mp4"
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / safe_name
    file.save(target)
    _finalize_uploaded_job(job_id, safe_name, file.filename, input_dir, target)
    emit(job_id, "log", f"Uploaded {safe_name}")
    return jsonify({"job_id": job_id, "filename": safe_name})


@app.post("/api/import-youtube")
def import_youtube():
    """Start a background yt-dlp download and expose real progress through /api/status."""
    data = request.get_json(silent=True) or {}
    req_platform = str(data.get("platform") or "").strip().lower()
    normalized = _normalize_import_url(data.get("url", ""), req_platform)
    if normalized is None:
        return jsonify({"error": "Paste a valid YouTube, Twitch, or Kick video/clip link."}), 400
    source_url, detected_platform = normalized
    plat_label = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}.get(detected_platform, "Video")
    try:
        max_height = int(data.get("quality") or 4320)
    except (TypeError, ValueError):
        max_height = 4320
    max_height = max(360, min(4320, max_height))
    yt_dlp_cmd = _yt_dlp_command()
    if not yt_dlp_cmd:
        return jsonify({"error": "Video import requires yt-dlp. Install the web requirements, then restart Clipify AI."}), 503

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id, "filename": "", "source_url": source_url,
            "status": "downloading", "progress": 0, "stage": f"Connecting to {plat_label}",
            "detail": "Starting yt-dlp…", "events": [], "outputs": [],
        }

    def worker() -> None:
        proc: subprocess.Popen[str] | None = None
        last_error: str = ""
        try:
            ffmpeg_path = _ffmpeg_path()
            output_template = str(input_dir / "youtube.%(ext)s")
            command = [*yt_dlp_cmd, "--no-playlist", "--no-warnings", "--newline", "--progress",
                       "--format-sort", f"res:{min(max_height, 2160)},fps,vbr",
                       "--progress-template", "download:[clip-prog] %(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes|progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
                       "--restrict-filenames", "--merge-output-format", "mp4", "--max-filesize", "8G",
                       "--socket-timeout", "30", "--retries", "5", "--fragment-retries", "5",
                       "--concurrent-fragments", "4",
                       "-f", f"bestvideo[height<={max_height}]+bestaudio/bestvideo[height<={max_height}]/best[height<={max_height}]/best",
                       "--ffmpeg-location", str(Path(ffmpeg_path).parent)]
            cookie_candidates = [
                ROOT / "cookies.txt",
                USER_DATA_DIR / "cookies.txt",
                ROOT / "youtube_cookies.txt",
                USER_DATA_DIR / "youtube_cookies.txt",
            ]
            cookie_file = next((str(p) for p in cookie_candidates if p.is_file()), None)
            if cookie_file:
                command.extend(["--cookies", cookie_file])
            node_binary = shutil.which("node") or shutil.which("node.exe")
            if node_binary:
                command.extend(["--js-runtimes", f"node:{node_binary}", "--remote-components", "ejs:github"])
            command.extend(["-o", output_template, source_url])
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=_hidden_creationflags())
            assert proc.stdout is not None

            def _fmt_size(n: float | int) -> str:
                try:
                    val = float(n)
                    for unit in ("B", "KB", "MB", "GB"):
                        if val < 1024.0:
                            return f"{val:.1f} {unit}"
                        val /= 1024.0
                    return f"{val:.1f} TB"
                except (TypeError, ValueError):
                    return ""

            stream_count = 0
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                with jobs_lock:
                    job = jobs.get(job_id)
                    if not job:
                        return
                    lower = line.lower()
                    if "[clip-prog]" in line:
                        payload = line.split("[clip-prog]", 1)[1].strip()
                        parts = [p.strip() for p in payload.split("|")]
                        pct = 0.0
                        pct_m = re.search(r"(\d+(?:\.\d+)?)%", parts[0]) if parts else None
                        if pct_m:
                            pct = float(pct_m.group(1))

                        info_items: list[str] = []
                        if len(parts) >= 3:
                            try:
                                dl_bytes = int(parts[1])
                                tot_bytes = int(parts[2])
                                if tot_bytes > 0:
                                    pct = (dl_bytes * 100.0) / tot_bytes
                                    info_items.append(f"{_fmt_size(dl_bytes)} / {_fmt_size(tot_bytes)}")
                                elif dl_bytes > 0:
                                    info_items.append(_fmt_size(dl_bytes))
                            except (TypeError, ValueError):
                                pass
                        if len(parts) >= 4 and parts[3] not in ("NA", ""):
                            try:
                                spd = float(parts[3])
                                info_items.append(f"{_fmt_size(spd)}/s")
                            except (TypeError, ValueError):
                                pass
                        if len(parts) >= 5 and parts[4] not in ("NA", ""):
                            try:
                                eta_val = int(float(parts[4]))
                                m, s = divmod(eta_val, 60)
                                info_items.append(f"ETA {m:02d}:{s:02d}")
                            except (TypeError, ValueError):
                                pass

                        if stream_count <= 1:
                            scaled = int(min(85, max(1, pct * 0.85)))
                            stage_lbl = "Downloading video"
                        else:
                            scaled = int(min(96, max(85, 85 + pct * 0.11)))
                            stage_lbl = "Downloading audio"

                        job["progress"] = max(job["progress"], scaled)
                        job["stage"] = stage_lbl
                        summary_info = " · ".join(info_items)
                        extra = f" ({summary_info})" if info_items else f" ({pct:.1f}%)"
                        job["detail"] = f"{stage_lbl}{extra}"

                    elif "destination:" in lower:
                        stream_count += 1
                        dest_file = line.split(":", 1)[1].strip() if ":" in line else line
                        dest_name = Path(dest_file).name
                        if stream_count <= 1:
                            job["progress"] = max(job["progress"], 1)
                            job["stage"] = "Downloading video"
                            job["detail"] = f"Connecting video stream ({dest_name})…"
                        else:
                            job["progress"] = max(job["progress"], 85)
                            job["stage"] = "Downloading audio"
                            job["detail"] = f"Connecting audio stream ({dest_name})…"

                    elif "[merger]" in lower or "merging" in lower:
                        job["progress"] = max(job["progress"], 97)
                        job["stage"] = "Finalizing download"
                        job["detail"] = "Merging video and audio streams…"

                    elif "[download]" in line and "%" in line:
                        pct_m = re.search(r"(\d+(?:\.\d+)?)%", line)
                        if pct_m:
                            pct = float(pct_m.group(1))
                            if stream_count <= 1:
                                scaled = int(min(85, max(1, pct * 0.85)))
                            else:
                                scaled = int(min(96, max(85, 85 + pct * 0.11)))
                            job["progress"] = max(job["progress"], scaled)
                        job["detail"] = line

                    job["events"].append({"kind": "log", "message": line})
            return_code = proc.wait()
            videos = []
            video_only_candidates = []
            ffprobe = Path(ffmpeg_path).with_name("ffprobe.exe")
            for candidate in input_dir.iterdir():
                if not candidate.is_file() or not is_allowed(candidate.name):
                    continue
                probe = _run_hidden(
                    [str(ffprobe), "-v", "error", "-show_entries", "stream=codec_type",
                     "-of", "csv=p=0", str(candidate)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, check=False,
                )
                streams_out = (probe.stdout or "").lower()
                if probe.returncode == 0 and "video" in streams_out and "audio" in streams_out:
                    videos.append(candidate)
                elif probe.returncode == 0 and "video" in streams_out:
                    video_only_candidates.append(candidate)

            # If high-quality video was downloaded without an audio track, download audio separately & mux
            if not videos and video_only_candidates:
                v_only = max(video_only_candidates, key=lambda p: p.stat().st_mtime)
                with jobs_lock:
                    if job_id in jobs:
                        jobs[job_id].update(progress=88, stage="Downloading separate audio", detail="High-quality video had no audio; fetching audio track separately…")
                aud_tpl = str(input_dir / "audio_sep.%(ext)s")
                aud_cmd = [*yt_dlp_cmd, "--no-playlist", "--no-warnings",
                           "-f", "bestaudio[ext=m4a]/bestaudio",
                           "--ffmpeg-location", str(Path(ffmpeg_path).parent),
                           "-o", aud_tpl, source_url]
                if cookie_file:
                    aud_cmd.extend(["--cookies", cookie_file])
                if node_binary:
                    aud_cmd.extend(["--js-runtimes", f"node:{node_binary}", "--remote-components", "ejs:github"])
                _run_hidden(aud_cmd, capture_output=True, text=True, timeout=300, check=False)
                aud_file = next((p for p in input_dir.iterdir() if p.is_file() and p.name.startswith("audio_sep.") and p.stat().st_size > 1024), None)
                if aud_file is not None:
                    mux_out = input_dir / f"{v_only.stem}_muxed.mp4"
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id].update(progress=95, stage="Muxing audio + video", detail="Combining high-quality video & audio…")
                    _run_hidden(
                        [ffmpeg_path, "-y", "-i", str(v_only), "-i", str(aud_file),
                         "-c:v", "copy", "-c:a", "aac", "-shortest", str(mux_out)],
                        capture_output=True, text=True, timeout=300, check=False,
                    )
                    if mux_out.is_file() and mux_out.stat().st_size > 1024:
                        videos.append(mux_out)
                        try:
                            aud_file.unlink()
                        except OSError:
                            pass
            last_error = ""
            if return_code != 0 or not videos:
                with jobs_lock:
                    for event in reversed(jobs[job_id].get("events", [])):
                        message = str(event.get("message", ""))
                        if message.startswith("ERROR:"):
                            if "not a bot" in message.lower() or "sign in" in message.lower():
                                last_error = "YouTube requested bot verification. Try saving the video with your browser and uploading the file directly, or provide cookies.txt."
                            else:
                                last_error = message
                            break
                detail = last_error or ("yt-dlp failed." if return_code != 0 else "yt-dlp finished but no video containing both video and audio was created.")
                with jobs_lock:
                    jobs[job_id].update(status="error", stage="YouTube download failed", detail=detail)
                    jobs[job_id]["events"].append({"kind":"error","message":detail})
                return
            target = max(videos, key=lambda p: p.stat().st_mtime)
            if target.stat().st_size == 0:
                detail = "Downloaded video file is empty (0 bytes). Your disk may be full or the download timed out."
                with jobs_lock:
                    jobs[job_id].update(status="error", stage="YouTube download failed", detail=detail, error=detail)
                    jobs[job_id]["events"].append({"kind": "error", "message": detail})
                return
            target = _ensure_video_has_audio(target)
            safe_name = secure_filename(target.name) or f"youtube_{job_id}.mp4"
            with jobs_lock:
                jobs[job_id].update(filename=safe_name, status="uploaded", progress=100,
                                    stage="Video ready", detail="YouTube download complete.")
                jobs[job_id]["events"].append({"kind":"download_complete","message":"YouTube download complete.","progress":100})
        except Exception as exc:
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    pass
            detail = f"{type(exc).__name__}: {exc}"
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id].update(status="error", stage="YouTube import error", detail=detail, error=detail)
                    jobs[job_id]["events"].append({"kind":"error","message":detail})

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "filename": "", "size": 0, "status": "downloading"}), 202


@app.post("/api/upload-logo/<job_id>")
def upload_logo(job_id: str):
    """Upload a logo image into the local job's branding folder."""
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"error": "Job not found."}), 404

    file = request.files.get("logo")
    if not file or not file.filename:
        return jsonify({"error": "Choose a logo image first."}), 400
    if not is_allowed_logo(file.filename):
        return jsonify({"error": "Logo must be PNG, JPG, JPEG or WEBP."}), 400

    branding_dir = job_dir / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix.lower()
    target = branding_dir / f"logo{ext}"
    file.save(target)
    return jsonify({
        "ok": True,
        "path": str(target),
        "url": f"/api/logo/{job_id}",
        "filename": target.name
    })


@app.get("/api/logo/<job_id>")
def get_job_logo(job_id: str):
    """Serve the logo image file associated with a job."""
    import mimetypes
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"error": "Job not found."}), 404
    branding_dir = job_dir / "branding"
    if branding_dir.is_dir():
        for ext in ("*.png", "*.webp", "*.jpg", "*.jpeg", "*.PNG", "*.WEBP", "*.JPG", "*.JPEG"):
            found = sorted(branding_dir.glob(ext))
            if found:
                mime, _ = mimetypes.guess_type(str(found[0]))
                return send_file(str(found[0]), mimetype=mime or "image/png")
    return jsonify({"error": "No logo found."}), 404


@app.post("/api/upload-logo")
def upload_generic_logo():
    """Upload a logo image into the user's global branding folder."""
    file = request.files.get("logo")
    if not file or not file.filename:
        return jsonify({"error": "Choose a logo image first."}), 400
    if not is_allowed_logo(file.filename):
        return jsonify({"error": "Logo must be PNG, JPG, JPEG or WEBP."}), 400

    branding_dir = USER_DATA_DIR / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix.lower()
    target = branding_dir / f"logo{ext}"
    file.save(target)
    return jsonify({
        "ok": True,
        "path": str(target),
        "url": "/api/global-logo",
        "filename": target.name
    })


@app.get("/api/global-logo")
def get_global_logo():
    """Serve the global uploaded logo image or fallback to app mark."""
    import mimetypes
    branding_dir = USER_DATA_DIR / "branding"
    if branding_dir.is_dir():
        for ext in ("*.png", "*.webp", "*.jpg", "*.jpeg", "*.PNG", "*.WEBP", "*.JPG", "*.JPEG"):
            found = sorted(branding_dir.glob(ext))
            if found:
                mime, _ = mimetypes.guess_type(str(found[0]))
                return send_file(str(found[0]), mimetype=mime or "image/png")
    mark = ROOT / "static" / "clipify-ai-mark.png"
    if mark.is_file():
        return send_file(str(mark), mimetype="image/png")
    return jsonify({"error": "No logo found."}), 404


@app.post("/api/start")
def start():
    raw_payload = request.get_json(silent=True)
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else dict(request.form)
    if payload and isinstance(payload.get("branding"), str):
        try:
            parsed = json.loads(payload["branding"])
            if isinstance(parsed, dict):
                payload["branding"] = parsed
        except (TypeError, ValueError):
            payload["branding"] = {}
    data = payload or {}
    split_screen = str(data.get("split_screen", data.get("splitScreen", "0"))).strip().lower() in {"1", "true", "yes", "on"}
    gaming_split = str(data.get("gaming_split", data.get("gamingSplit", "1"))).strip().lower() in {"1", "true", "yes", "on"}
    fast_whisper = str(data.get("fast_whisper", data.get("fastWhisper", "1"))).strip().lower() in {"1", "true", "yes", "on"}
    job_id = str(data.get("job_id", ""))
    mode = str(data.get("mode", "viral")).lower()
    model = str(data.get("model", "")).strip()
    font = str(data.get("font", "Montserrat Extra Bold")).strip()
    try:
        clips = max(1, min(10, int(data.get("clips", 2))))
    except (TypeError, ValueError):
        clips = 2
    try:
        min_duration = max(25, min(60, int(data.get("min_duration", 25))))
    except (TypeError, ValueError):
        min_duration = 25
    try:
        max_duration = max(25, min(60, int(data.get("max_duration", 60))))
    except (TypeError, ValueError):
        max_duration = 60
    if max_duration <= min_duration:
        max_duration = min_duration + 1

    # A source shorter than the requested minimum can never yield a clip, and
    # the pipeline then fails with "No final captioned Shorts were produced."
    # Shorten the requested window to fit the footage instead, and say so.
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"error": "Job not found."}), 404
    input_dir = job_dir / "input"
    if input_dir.is_dir():
        sources = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})
        if sources:
            if all(s.stat().st_size < 1024 for s in sources):
                return jsonify({
                    "error": "The input video file is incomplete or empty (< 1 KB). The download may still be running, was interrupted, or disk space was exhausted. Please wait for the download to finish or re-import the video."
                }), 400
            source_seconds = _media_duration_seconds(str(sources[0]))
            if source_seconds and source_seconds < min_duration:
                fitted_max = max(6, int(source_seconds))
                fitted_min = max(5, min(fitted_max - 1, int(source_seconds * 0.6)))
                if (fitted_min, fitted_max) != (min_duration, max_duration):
                    emit(job_id, "log", f"[Setup] Source is {source_seconds:.0f}s long; "
                                        f"clip length adjusted from {min_duration}-{max_duration}s "
                                        f"to {fitted_min}-{fitted_max}s to fit.")
                    min_duration, max_duration = fitted_min, fitted_max

    if mode not in MODES:
        return jsonify({"error": "Invalid editing mode."}), 400
    models, model_error = _discover_ollama_models()
    if not models:
        model = ""
    elif not model or model.lower() in ("heuristic", "builtin", "none", ""):
        model = ""
    elif models and model not in models:
        model = _default_model(models)
    allowed_fonts = ["Montserrat Extra Bold", "Arial", "Arial Black", "Segoe UI", "Segoe UI Black", "Impact", "Tahoma", "Trebuchet MS", "Verdana", "Calibri", "Aptos", "Comic Sans MS", "Georgia", "none"]
    if font not in allowed_fonts:
        font = "Montserrat Extra Bold"
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            # The app may have restarted after a YouTube download completed. The
            # job directory and its input video still exist on disk, but the
            # in-memory jobs dict was cleared. Reconstruct a minimal job entry so
            # the pipeline can run without requiring the user to re-download.
            _job_dir_check = _safe_job_directory(job_id)
            if _job_dir_check is not None and _job_dir_check.is_dir():
                _input_check = _job_dir_check / "input"
                _disk_sources = sorted(
                    p for p in (_input_check.iterdir() if _input_check.is_dir() else [])
                    if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"}
                )
                if _disk_sources:
                    job = {
                        "id": job_id,
                        "filename": _disk_sources[0].name,
                        "source_url": "",
                        "status": "uploaded",
                        "progress": 100,
                        "stage": "Video ready",
                        "detail": "Recovered from disk after app restart.",
                        "events": [],
                        "outputs": [],
                    }
                    jobs[job_id] = job
            if not job:
                return jsonify({"error": "Job not found."}), 404
        if job["status"] == "running":
            return jsonify({"error": "This job is already running."}), 409
        if job["status"] == "downloading":
            return jsonify({"error": "Video is still downloading from YouTube. Please wait."}), 400
        job.update({
            "mode": mode, "clips": clips, "model": model, "font": font,
            "min_duration": min_duration, "max_duration": max_duration,
            "status": "running",
            "progress": 2,
            "stage": "Starting Clipify AI",
            "detail": "Launching the local pipeline…",
            "stage_started": __import__("time").time(),
            "events": [],
            "outputs": [],
        })
    raw_branding = data.get("branding")
    branding_raw: dict[str, Any] = raw_branding if isinstance(raw_branding, dict) else {}
    branding: dict[str, Any] = {
        "logo_enabled": bool(branding_raw.get("logo_enabled", branding_raw.get("watermark_enabled", False))),
        "logo_path": str(branding_raw.get("logo_path", branding_raw.get("watermark_path", str(ROOT / "static" / "clipify-ai-mark.png")))).strip(),
        "logo_position": str(branding_raw.get("logo_position", branding_raw.get("watermark_position", "top-right"))),
        "logo_size": max(1, min(50, int(branding_raw.get("logo_size", branding_raw.get("watermark_size", 8))))),
        "logo_opacity": max(0, min(100, int(branding_raw.get("logo_opacity", branding_raw.get("watermark_opacity", 80))))),
        "logo_margin": max(0, min(500, int(branding_raw.get("logo_margin", branding_raw.get("watermark_margin", 40))))),
        "logo_x": max(0, min(100, float(branding_raw.get("logo_x", branding_raw.get("watermark_x", 92))))),
        "logo_y": max(0, min(100, float(branding_raw.get("logo_y", branding_raw.get("watermark_y", 8))))),
        "logo_bg_remove": bool(branding_raw.get("logo_bg_remove", branding_raw.get("watermark_bg_remove", False))),
        "logo_bg_color": "#" + _hex6(str(branding_raw.get("logo_bg_color", branding_raw.get("watermark_bg_color", "#9B5CFF")))),
        "logo_bg_similarity": max(0.01, min(1.0, float(branding_raw.get("logo_bg_similarity", branding_raw.get("watermark_bg_similarity", 0.22))))),
        "logo_bg_blend": max(0.0, min(1.0, float(branding_raw.get("logo_bg_blend", 0.05)))),
        "text_enabled": bool(branding_raw.get("text_enabled", False)),
        "text": str(branding_raw.get("text", "")).strip()[:100],
        "text_position": str(branding_raw.get("text_position", "bottom-center")),
        "text_size": max(2, min(25, int(branding_raw.get("text_size", 6)))),
        "text_color": str(branding_raw.get("text_color", "#FFFFFF")),
        "text_bg_enabled": bool(branding_raw.get("text_bg_enabled", True)),
        "text_bg_color": str(branding_raw.get("text_bg_color", "#000000")),
        "text_bg_opacity": max(0, min(100, int(branding_raw.get("text_bg_opacity", 65)))),
        "text_margin": max(20, min(500, int(branding_raw.get("text_margin", 110)))),
        "text_x": max(0, min(100, float(branding_raw.get("text_x", 50)))),
        "text_y": max(0, min(100, float(branding_raw.get("text_y", 75)))),
        "watermark_text_enabled": bool(branding_raw.get("watermark_text_enabled", False)),
        "watermark_text": str(branding_raw.get("watermark_text", "")).strip()[:100],
        "watermark_text_position": str(branding_raw.get("watermark_text_position", "center")),
        "watermark_text_size": max(3, min(20, int(branding_raw.get("watermark_text_size", 6)))),
        "watermark_text_opacity": max(0, min(100, int(branding_raw.get("watermark_text_opacity", 35)))),
        "watermark_text_angle": max(-45, min(45, int(branding_raw.get("watermark_text_angle", -20)))),
        "watermark_text_color": "#" + _hex6(str(branding_raw.get("watermark_text_color", "#FFFFFF"))),
        "watermark_text_x": max(0, min(100, float(branding_raw.get("watermark_text_x", 50)))),
        "watermark_text_y": max(0, min(100, float(branding_raw.get("watermark_text_y", 50)))),
        "premium_captions": bool(branding_raw.get("premium_captions", data.get("premium_captions", True))),
        "situational_cues": bool(branding_raw.get("situational_cues", data.get("situational_cues", True))),
        "caption_preset": str(branding_raw.get("caption_preset", data.get("caption_preset", "center_seam" if (gaming_split or split_screen) else "lower_safe"))),
        "caption_accent": str(branding_raw.get("caption_accent", data.get("caption_accent", "gold_yellow"))),
    }
    if branding["logo_position"] not in BRANDING_POSITIONS:
        branding["logo_position"] = "top-right"
    if branding["text_position"] not in BRANDING_POSITIONS:
        branding["text_position"] = "bottom-center"
    disable_captions = bool(
        str(data.get("disable_captions", data.get("disableCaptions", "0"))).strip().lower() in {"1", "true", "yes", "on"}
        or font == "none"
        or str(data.get("captions_enabled", data.get("captionsEnabled", "1"))).strip().lower() in {"0", "false", "no", "off"}
        or branding_raw.get("disable_captions")
        or branding_raw.get("captions_enabled") is False
    )
    language = str(data.get("language") or data.get("caption_language") or branding_raw.get("language") or "auto").strip().lower()
    branding["disable_captions"] = disable_captions
    branding["captions_enabled"] = not disable_captions
    branding["language"] = language

    branding["upscale_quality"] = str(branding_raw.get("upscale_quality", data.get("upscale_quality", "high"))).strip().lower()
    try:
        split_ratio = max(30, min(70, int(data.get("split_ratio", data.get("splitRatio", 50)))))
    except (TypeError, ValueError):
        split_ratio = 50
    upscale_quality = str(data.get("upscale_quality", data.get("upscaleQuality", "high"))).strip().lower()
    if upscale_quality not in UPSCALE_PROFILES:
        upscale_quality = "high"
    use_existing_transcription = str(data.get("use_existing_transcription", data.get("useExistingTranscription", "1"))).strip().lower() in {"1", "true", "yes", "on"}
    with jobs_lock:
        jobs[job_id]["branding"] = branding
        jobs[job_id]["split_screen"] = split_screen
        jobs[job_id]["gaming_split"] = gaming_split
        jobs[job_id]["split_ratio"] = split_ratio
        jobs[job_id]["fast_whisper"] = fast_whisper
        jobs[job_id]["use_existing_transcription"] = use_existing_transcription
        jobs[job_id]["upscale_quality"] = upscale_quality
        jobs[job_id]["disable_captions"] = disable_captions
        jobs[job_id]["language"] = language
    threading.Thread(target=run_job, args=(job_id, mode, clips, model, font, min_duration, max_duration, branding, split_screen, fast_whisper, gaming_split, split_ratio, upscale_quality, language, disable_captions, use_existing_transcription), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "model": model, "font": font, "min_duration": min_duration, "max_duration": max_duration, "branding": branding, "split_screen": split_screen, "gaming_split": gaming_split, "split_ratio": split_ratio, "fast_whisper": fast_whisper, "upscale_quality": upscale_quality, "disable_captions": disable_captions, "language": language})



@app.post("/api/apply-branding/<job_id>")
def apply_branding(job_id: str):
    """Apply logo/text to an existing rendered Short without rerunning the AI pipeline."""
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"error": "Project not found."}), 404
    data = request.get_json(silent=True) or {}
    filename = Path(str(data.get("filename", ""))).name
    if not filename:
        return jsonify({"error": "Choose a Short first."}), 400
    out_dir = job_dir / "output"
    source = out_dir / filename
    if not source.exists() or source.suffix.lower() != ".mp4":
        return jsonify({"error": "Selected Short was not found."}), 404

    # Prefer the clean captioned base created by main.py. This prevents stacked logos
    # when the user edits branding repeatedly after generation.
    clean_name = re.sub(r"_edited(?:_\d+)?\.mp4$", ".mp4", filename, flags=re.I)
    clean_name = re.sub(r"\.mp4$", "_clean.mp4", clean_name, flags=re.I)
    clean = out_dir / clean_name
    base = clean if clean.exists() else source

    raw_b = data.get("branding")
    b: dict[str, Any] = raw_b if isinstance(raw_b, dict) else {}
    raw_framing = data.get("framing") if isinstance(data.get("framing"), dict) else b.get("framing")
    framing_raw: dict[str, Any] = raw_framing if isinstance(raw_framing, dict) else {}
    branding: dict[str, Any] = {
        "logo_enabled": bool(b.get("logo_enabled")),
        "logo_path": str(b.get("logo_path", "")).strip(),
        "logo_position": str(b.get("logo_position", "top-right")),
        "logo_size": max(1, min(50, int(b.get("logo_size", 8)))),
        "logo_opacity": max(0, min(100, int(b.get("logo_opacity", 80)))),
        "logo_margin": max(0, min(500, int(b.get("logo_margin", 40)))),
        "logo_x": max(0, min(100, float(b.get("logo_x", 92)))),
        "logo_y": max(0, min(100, float(b.get("logo_y", 8)))),
        "logo_bg_remove": bool(b.get("logo_bg_remove")),
        "logo_bg_color": "#" + _hex6(str(b.get("logo_bg_color", "#9B5CFF"))),
        "logo_bg_similarity": max(0.01, min(1.0, float(b.get("logo_bg_similarity", 0.22)))),
        "logo_bg_blend": max(0.0, min(1.0, float(b.get("logo_bg_blend", 0.05)))),
        "text_enabled": bool(b.get("text_enabled")),
        "text": str(b.get("text", "")).strip()[:100],
        "text_position": str(b.get("text_position", "bottom-center")),
        "text_size": max(2, min(25, int(b.get("text_size", 6)))),
        "text_color": "#" + _hex6(str(b.get("text_color", "#FFFFFF"))),
        "text_bg_enabled": bool(b.get("text_bg_enabled")),
        "text_bg_color": "#" + _hex6(str(b.get("text_bg_color", "#000000"))),
        "text_bg_opacity": max(0, min(100, int(b.get("text_bg_opacity", 65)))),
        "text_margin": max(20, min(500, int(b.get("text_margin", 110)))),
        "text_x": max(0, min(100, float(b.get("text_x", 50)))),
        "text_y": max(0, min(100, float(b.get("text_y", 75)))),
        "watermark_text_enabled": bool(b.get("watermark_text_enabled", False)),
        "watermark_text": str(b.get("watermark_text", "")).strip()[:100],
        "watermark_text_position": str(b.get("watermark_text_position", "center")),
        "watermark_text_size": max(3, min(20, int(b.get("watermark_text_size", 6)))),
        "watermark_text_opacity": max(0, min(100, int(b.get("watermark_text_opacity", 35)))),
        "watermark_text_angle": max(-45, min(45, int(b.get("watermark_text_angle", -20)))),
        "watermark_text_color": "#" + _hex6(str(b.get("watermark_text_color", "#FFFFFF"))),
        "watermark_text_x": max(0, min(100, float(b.get("watermark_text_x", 50)))),
        "watermark_text_y": max(0, min(100, float(b.get("watermark_text_y", 50)))),
        "framing": {
            "pan_x": max(-50.0, min(50.0, float(framing_raw.get("pan_x", 0.0)))),
            "pan_y": max(-50.0, min(50.0, float(framing_raw.get("pan_y", 0.0)))),
            "zoom": max(1.0, min(2.5, float(framing_raw.get("zoom", 1.0)))),
        },
    }
    if branding["logo_position"] not in BRANDING_POSITIONS:
        branding["logo_position"] = "top-right"
    if branding["text_position"] not in BRANDING_POSITIONS:
        branding["text_position"] = "bottom-center"
    branding["upscale_quality"] = str(b.get("upscale_quality", data.get("upscale_quality", "high"))).strip().lower()

    font = str(data.get("font", "Arial"))
    stem = source.stem
    canonical = re.sub(r"_edited(?:_\d+)?$", "", stem, flags=re.I)
    canonical = re.sub(r"_clean$", "", canonical, flags=re.I)
    target = out_dir / f"{canonical}_edited.mp4"
    try:
        apply_branding_to_file(str(base), str(target), branding, font)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "filename": target.name, "url": f"/media/{job_id}/{target.name}", "base": base.name})


@app.post("/api/beta/apply-text")
def beta_apply_text():
    """Burn timed, repositioned text into a beta clip for pixel-perfect modifications."""
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id", "")).strip()
    filename = Path(str(data.get("filename", ""))).name
    text = str(data.get("text", "")).strip()
    if not job_id or not filename:
        return jsonify({"ok": False, "error": "Select a Short first."}), 400
    if not text:
        return jsonify({"ok": False, "error": "Text cannot be empty."}), 400

    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"ok": False, "error": "Project not found."}), 404

    out_dir = job_dir / "output"
    source = out_dir / filename
    if not source.exists() or source.suffix.lower() != ".mp4":
        return jsonify({"ok": False, "error": f"Short {filename} not found."}), 404

    # Use clean source base if available to prevent compounding previous text burns
    clean_name = re.sub(r"_edited(?:_\d+)?\.mp4$", ".mp4", filename, flags=re.I)
    clean_name = re.sub(r"\.mp4$", "_clean.mp4", clean_name, flags=re.I)
    clean = out_dir / clean_name
    base_file = clean if clean.exists() else source

    timestamp = int(time.time() * 1000)
    stem = re.sub(r"(_edited|_custom|_clean)(?:_\d+)?$", "", source.stem, flags=re.I)
    out_filename = f"{stem}_edited_{timestamp}.mp4"
    target = out_dir / out_filename

    start_time = max(0.0, float(data.get("start_time", 0.0)))
    end_time = float(data.get("end_time", 0.0))
    x_pct = max(0.0, min(100.0, float(data.get("x", 50.0))))
    y_pct = max(0.0, min(100.0, float(data.get("y", 25.0))))
    font_size_pt = max(18, min(120, int(data.get("font_size", 42))))
    fs_canvas = max(36, min(160, round(font_size_pt * 2.4)))
    font_name = str(data.get("font_name", "Montserrat Extra Bold"))
    font_path = _font_path_for_editor(font_name)
    font_expr = f":fontfile='{_ffmpeg_filter_path(font_path)}'" if font_path else ""

    text_color = _hex6(str(data.get("color", "#facc15")))
    bg_enabled = bool(data.get("bg_enabled", True))
    bg_color = str(data.get("bg_color", "#000000"))
    bg_opacity = max(0, min(100, int(data.get("bg_opacity", 65))))
    box = 1 if bg_enabled else 0
    boxcolor = _ffmpeg_color(bg_color, bg_opacity)

    temp_text = str(out_dir / f"_temp_beta_text_{timestamp}.txt")
    try:
        Path(temp_text).write_text(text, encoding="utf-8")
        tf = _ffmpeg_filter_path(temp_text)

        x_expr = f"(w-tw)*{x_pct/100:.6f}"
        y_expr = f"(h-th)*{y_pct/100:.6f}"
        enable_expr = f":enable='between(t,{start_time:.3f},{end_time:.3f})'" if (end_time > start_time) else ""

        drawtext_filter = (
            f"drawtext=textfile='{tf}':fontsize={fs_canvas}:fontcolor=0x{text_color}{font_expr}"
            f":x={x_expr}:y={y_expr}:box={box}:boxcolor={boxcolor}:boxborderw=18:borderw=4:bordercolor=0x000000"
            f"{enable_expr}:fix_bounds=true"
        )

        ffmpeg = _ffmpeg_path()
        cmd = [
            ffmpeg, "-y", "-i", str(base_file),
            "-vf", drawtext_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(target)
        ]
        proc = _run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    finally:
        try:
            Path(temp_text).unlink()
        except OSError:
            pass

    if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1024:
        err_msg = proc.stderr[-800:] if proc.stderr else "FFmpeg text overlay rendering failed."
        return jsonify({"ok": False, "error": err_msg}), 500

    return jsonify({
        "ok": True,
        "filename": out_filename,
        "url": f"/media/{job_id}/{out_filename}?t={timestamp}",
        "clean_filename": clean.name if clean.exists() else filename,
    })


# ============================================================================
# INSTANT CLIPPING LAB (ISOLATED ULTRA-FAST 9:16 ENGINE)
# ============================================================================
instant_jobs: dict[str, dict[str, Any]] = {}
instant_jobs_lock = threading.Lock()


def _fast_generate_captions(audio_path: Path, ass_path: Path, clip_dur: float, layout: str) -> bool:
    """Generate dynamic kinetic ASS captions for an isolated instant short in seconds using faster-whisper."""
    try:
        _ensure_cuda_dlls()
        from faster_whisper import WhisperModel
        try:
            from clipify.platform.gpu_manager import get_whisper_device_and_type
            device, compute_type = get_whisper_device_and_type()
        except Exception:
            use_cuda = _is_cuda_available()
            device = "cuda" if use_cuda else "cpu"
            compute_type = "float16" if use_cuda else "int8"
        try:
            model = WhisperModel("tiny", device=device, compute_type=compute_type)
        except Exception:
            # Automatic fallback to CPU if CUDA initialization fails
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), word_timestamps=True, beam_size=1, vad_filter=True)
        words = []
        for segment in segments:
            for w in (getattr(segment, "words", None) or []):
                word_text = w.word.strip()
                if word_text:
                    words.append({
                        "word": word_text,
                        "start": max(0.0, float(w.start)),
                        "end": min(clip_dur, float(w.end))
                    })
        try:
            del model
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        if not words:
            return False

        margin_v = 920 if ("split" in layout) else 280
        style_header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
            "WrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Kinetic,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{margin_v},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        def to_ass_time(sec: float) -> str:
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = int(sec % 60)
            cs = round((sec - int(sec)) * 100)
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

        beats = []
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 3 or (chunk and chunk[-1]["word"].endswith((".", "!", "?", ","))):
                beats.append(chunk)
                chunk = []
        if chunk:
            beats.append(chunk)

        with open(ass_path, "w", encoding="utf-8-sig") as f:
            f.write(style_header)
            for beat in beats:
                b_start = beat[0]["start"]
                b_end = max(b_start + 0.3, beat[-1]["end"])
                text = " ".join(w["word"] for w in beat).upper()
                pop = "{\\fscx90\\fscy90\\t(0,70,\\fscx108\\fscy108)\\t(70,140,\\fscx100\\fscy100)}"
                f.write(f"Dialogue: 0,{to_ass_time(b_start)},{to_ass_time(b_end)},Kinetic,,0,0,0,,{pop}{text}\n")

        return ass_path.exists() and ass_path.stat().st_size > 100
    except Exception as e:
        print(f"[FastCaptions] Notice: {e}")
        return False


def _instant_worker(
    job_id: str,
    input_path: Path | None,
    target_dur: float,
    layout: str,
    start_mode: str,
    custom_start: float,
    youtube_url: str = "",
    num_clips: int = 1,
    captions: str = "yes",
    iteration: int = 0
) -> None:
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    out_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        with instant_jobs_lock:
            if job_id in instant_jobs:
                instant_jobs[job_id]["logs"].append(entry)

    def update_status(status: str, progress: int, stage: str) -> None:
        with instant_jobs_lock:
            if job_id in instant_jobs:
                instant_jobs[job_id].update(status=status, progress=progress, stage=stage)

    try:
        update_status("running", 5, "Initializing engine")
        log("⚡ Instant Engine Initialized (Isolated High-Speed Mode)")
        log("Bypassing heavy LLM transcription & multi-stage candidate scoring...")

        # If YouTube URL provided and input not downloaded yet
        if youtube_url and (not input_path or not input_path.exists()):
            log(f"Connecting to YouTube stream: {youtube_url}...")
            update_status("running", 10, "Fetching YouTube stream")
            yt_out = input_dir / f"yt_source_{job_id[:8]}.mp4"
            cookie_candidates = [
                ROOT / "cookies.txt",
                USER_DATA_DIR / "cookies.txt",
                ROOT / "youtube_cookies.txt",
                USER_DATA_DIR / "youtube_cookies.txt",
            ]
            cookie_file = next((str(p) for p in cookie_candidates if p.is_file()), None)
            yt_cookie_args = ["--cookies", cookie_file] if cookie_file else []

            yt_cmd = [
                sys.executable, "-m", "yt_dlp",
                "--no-playlist",
                "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best/18",
                "--extractor-args", "youtube:player_client=android,ios,mweb",
                "--no-check-certificates",
                *yt_cookie_args,
                "-o", str(yt_out),
                youtube_url
            ]
            yt_proc = _run_hidden(yt_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            if not yt_out.exists() or yt_out.stat().st_size == 0:
                yt_cmd_fb = [
                    sys.executable, "-m", "yt_dlp",
                    "--no-playlist",
                    "-f", "18/best[ext=mp4]/best",
                    "--extractor-args", "youtube:player_client=android,ios,mweb",
                    "--no-check-certificates",
                    *yt_cookie_args,
                    "-o", str(yt_out),
                    youtube_url
                ]
                _run_hidden(yt_cmd_fb, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)

            if not yt_out.exists() or yt_out.stat().st_size == 0:
                raw_err = yt_proc.stderr or ""
                if "not a bot" in raw_err.lower() or "sign in" in raw_err.lower():
                    err_msg = "YouTube requested bot verification. Try downloading with your browser and uploading the MP4 directly, or provide cookies.txt."
                else:
                    err_msg = raw_err[-300:] if raw_err else "Failed to download YouTube video."
                log(f"ERROR: YouTube download failed: {err_msg}")
                update_status("error", 0, "YouTube import failed")
                return

            input_path = yt_out
            log(f"YouTube stream ready ({yt_out.stat().st_size // (1024 * 1024)} MB)")

        if not input_path or not input_path.exists():
            log("ERROR: Source video file not found.")
            update_status("error", 0, "Source video missing")
            return

        total_dur = _media_duration_seconds(str(input_path))
        if total_dur <= 0.0:
            total_dur = 60.0
        log(f"Source video verified: {input_path.name} (Duration: {total_dur:.1f}s)")

        # Load previously used segments for this video to ensure diverse, non-overlapping clips
        used_segments_file = job_dir / "used_segments.json"
        used_segments: list[list[float]] = []
        if used_segments_file.exists():
            try:
                used_segments = json.loads(used_segments_file.read_text(encoding="utf-8"))
            except Exception:
                used_segments = []

        # Calculate segment windows for num_clips
        clip_len = min(target_dur, total_dur)
        usable_span = max(0.0, total_dur - clip_len)
        segments: list[tuple[float, float]] = []

        if num_clips <= 1:
            if start_mode == "start":
                s = 0.0
            elif start_mode == "custom":
                s = max(0.0, min(custom_start, usable_span))
            else:  # auto / golden hook or generate another option
                if usable_span <= 0.0:
                    s = 0.0
                else:
                    golden_ratios = [0.18, 0.48, 0.72, 0.04, 0.32, 0.60, 0.85, 0.12, 0.39, 0.67, 0.88, 0.24, 0.54, 0.79]

                    def overlap_amount(candidate_s: float) -> float:
                        candidate_e = candidate_s + clip_len
                        tot_overlap = 0.0
                        for prev_s, prev_e in used_segments:
                            overlap = max(0.0, min(candidate_e, prev_e) - max(candidate_s, prev_s))
                            tot_overlap += overlap
                        return tot_overlap

                    sample_points = []
                    for r in golden_ratios:
                        cand = max(0.0, min(usable_span, total_dur * r))
                        sample_points.append(cand)

                    num_grid = max(6, int(usable_span / max(5.0, clip_len * 0.75)))
                    for g in range(num_grid):
                        sample_points.append(g * (usable_span / max(1, num_grid - 1)))

                    rot = iteration % len(sample_points)
                    candidate_order = sample_points[rot:] + sample_points[:rot]

                    best_s = None
                    min_overlap = float("inf")
                    for cand_s in candidate_order:
                        ov = overlap_amount(cand_s)
                        if ov == 0.0:
                            best_s = cand_s
                            break
                        if ov < min_overlap:
                            min_overlap = ov
                            best_s = cand_s

                    s = best_s if best_s is not None else max(0.0, min(usable_span, total_dur * golden_ratios[iteration % len(golden_ratios)]))

            segments.append((s, s + clip_len))
            used_segments.append([round(s, 2), round(s + clip_len, 2)])
            if iteration > 0:
                log(f"⚡ Iteration #{iteration + 1}: Selected unique hook window at {s:.1f}s -> {s + clip_len:.1f}s (avoiding previous clips)")
        else:
            if usable_span <= 0.0:
                for _ in range(num_clips):
                    segments.append((0.0, clip_len))
            else:
                step = usable_span / (num_clips + 1)
                offset_shift = (iteration * (step * 0.35)) % max(1.0, step)
                for i in range(num_clips):
                    if start_mode == "start" and i == 0:
                        s = 0.0
                    elif start_mode == "custom" and i == 0:
                        s = max(0.0, min(custom_start, usable_span))
                    else:
                        base = step * (i + 1) + offset_shift
                        s = max(0.0, min(usable_span, base))
                    segments.append((s, s + clip_len))
                    used_segments.append([round(s, 2), round(s + clip_len, 2)])

        try:
            used_segments_file.write_text(json.dumps(used_segments), encoding="utf-8")
        except Exception:
            pass

        outputs = []
        ffmpeg = _ffmpeg_path()
        fonts_dir = str((ROOT / "fonts").resolve()).replace("\\", "/").replace(":", "\\:")

        for c_idx, (start_sec, end_sec) in enumerate(segments):
            c_dur = end_sec - start_sec
            log(f"Rendering Clip {c_idx + 1}/{num_clips} (window: {start_sec:.1f}s -> {end_sec:.1f}s, {c_dur:.1f}s)...")
            prog = int(25 + 65 * (c_idx / num_clips))
            update_status("running", prog, f"Rendering Clip {c_idx + 1}/{num_clips}")

            # Check if captions requested
            ass_path = None
            if captions == "yes":
                try:
                    chunk_wav = job_dir / f"chunk_{job_id[:8]}_{c_idx}.wav"
                    audio_cmd = [
                        ffmpeg, "-y",
                        "-ss", f"{start_sec:.2f}",
                        "-i", str(input_path),
                        "-t", f"{c_dur:.2f}",
                        "-vn", "-ac", "1", "-ar", "16000",
                        str(chunk_wav)
                    ]
                    _run_hidden(audio_cmd, timeout=30)
                    if chunk_wav.exists() and chunk_wav.stat().st_size > 1000:
                        candidate_ass = job_dir / f"subs_{job_id[:8]}_{c_idx}.ass"
                        if _fast_generate_captions(chunk_wav, candidate_ass, c_dur, layout):
                            ass_path = candidate_ass
                            log(f"✔ Kinetic captions generated for Clip {c_idx + 1}")
                    chunk_wav.unlink(missing_ok=True)
                except Exception as e:
                    log(f"Notice: Fast captions skipped for clip {c_idx + 1} ({e})")

            ass_filter_frag = ""
            if ass_path and ass_path.exists():
                ass_esc = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
                ass_filter_frag = f"ass='{ass_esc}':fontsdir='{fonts_dir}'"

            is_complex = False
            if layout == "blur_fill":
                is_complex = True
                log("Applying Cinematic Blur Background 9:16 layout...")
                base_chain = (
                    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,boxblur=20:5[bg];"
                    "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2"
                )
                if ass_filter_frag:
                    filter_str = f"{base_chain}[vstacked];[vstacked]{ass_filter_frag}"
                else:
                    filter_str = base_chain
            elif layout == "gaming_split":
                is_complex = True
                log("Applying Gaming Facecam + Gameplay Split Screen layout...")
                base_chain = (
                    "[0:v]crop=iw*0.5:ih*0.5:(iw-iw*0.5)/2:0,scale=1080:720:flags=fast_bilinear[top];"
                    "[0:v]crop=iw:ih*0.75:0:ih*0.25,scale=1080:1200:flags=fast_bilinear[bot];"
                    "[top][bot]vstack=inputs=2"
                )
                if ass_filter_frag:
                    filter_str = f"{base_chain}[vstacked];[vstacked]{ass_filter_frag}"
                else:
                    filter_str = base_chain
            elif layout == "split":
                is_complex = True
                log("Applying 50/50 Vertical Split Screen (Top & Bottom) layout...")
                base_chain = (
                    "[0:v]crop=iw:ih/2:0:0,scale=1080:960:flags=fast_bilinear[top];"
                    "[0:v]crop=iw:ih/2:0:ih/2,scale=1080:960:flags=fast_bilinear[bot];"
                    "[top][bot]vstack=inputs=2"
                )
                if ass_filter_frag:
                    filter_str = f"{base_chain}[vstacked];[vstacked]{ass_filter_frag}"
                else:
                    filter_str = base_chain
            else:  # center_crop
                log("Applying High-Speed Smart 9:16 Center Crop...")
                crop_chain = (
                    "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9):(iw-min(iw\\,ih*9/16))/2:(ih-min(ih\\,iw*16/9))/2,"
                    "scale=1080:1920:flags=fast_bilinear"
                )
                if ass_filter_frag:
                    filter_str = f"{crop_chain},{ass_filter_frag}"
                else:
                    filter_str = crop_chain

            if iteration > 0:
                out_name = f"instant_{job_id[:8]}_short_v{iteration + 1}_{c_idx + 1}.mp4" if num_clips > 1 else f"instant_{job_id[:8]}_short_v{iteration + 1}.mp4"
            else:
                out_name = f"instant_{job_id[:8]}_short_{c_idx + 1}.mp4" if num_clips > 1 else f"instant_{job_id[:8]}_short.mp4"
            out_path = out_dir / out_name

            try:
                from clipify.platform.gpu_manager import get_ffmpeg_video_encoder_flags
                enc_flags = get_ffmpeg_video_encoder_flags(bitrate="12M", preset="veryfast", crf=20)
            except Exception:
                enc_flags = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]

            cmd = [
                ffmpeg, "-y",
                "-ss", f"{start_sec:.2f}",
                "-i", str(input_path),
                "-t", f"{c_dur:.2f}",
                "-filter_complex" if is_complex else "-vf", filter_str,
                *enc_flags,
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(out_path)
            ]

            proc = _run_hidden(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)

            if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
                err = proc.stderr[-400:] if proc.stderr else "FFmpeg execution failed."
                log(f"ERROR: Clip {c_idx + 1} render failed: {err}")
                continue

            outputs.append(out_name)
            size_kb = out_path.stat().st_size // 1024
            log(f"✔ Clip {c_idx + 1}/{num_clips} rendered successfully: {out_name} ({size_kb} KB)")

            # Generate & save title + description JSON metadata so Projects/Editor never show "Short #1"
            try:
                src_clean = re.sub(r"[_-]+", " ", input_path.stem).strip() or "Viral Moment"
                clip_title = f"{src_clean[:42]} · Highlight #{c_idx + 1} 🔥"
                clip_desc = f"Auto-clipped viral highlight from {src_clean} ({int(start_sec)}s–{int(start_sec + clip_len)}s). #Shorts #ClipifyAI"
                try:
                    ollama_url = _ollama_base_url()
                    cfg_ai = _load_ai_config()
                    installed_models, _ = _discover_ollama_models()
                    m_name = cfg_ai.get("ollama_model") or ""
                    if installed_models and m_name not in installed_models:
                        m_name = _get_fastest_ollama_model()[0] or installed_models[0]
                    if not m_name:
                        m_name = "qwen3:4b"
                    prompt_txt = (
                        f"Return JSON {{\"title\":\"...\",\"description\":\"...\"}} for a {int(clip_len)}s YouTube Short "
                        f"from '{src_clean}' (segment {int(start_sec)}s-{int(start_sec + clip_len)}s). Keep title under 7 words with 1 emoji."
                    )
                    o_req = urllib.request.Request(
                        f"{ollama_url}/api/generate",
                        data=json.dumps({"model": m_name, "prompt": prompt_txt, "stream": False, "think": False, "format": "json"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(o_req, timeout=25) as o_resp:
                        o_data = json.loads(o_resp.read().decode("utf-8", errors="replace"))
                        ai_raw = o_data.get("response", "")
                        m_json = re.search(r"\{[\s\S]*\}", ai_raw)
                        if m_json:
                            ai_obj = json.loads(m_json.group(0))
                            if str(ai_obj.get("title", "")).strip():
                                clip_title = str(ai_obj["title"]).strip()[:90]
                            if str(ai_obj.get("description", "")).strip():
                                clip_desc = str(ai_obj["description"]).strip()[:500]
                except Exception:
                    pass
                meta_file = out_path.with_suffix(".json")
                meta_file.write_text(json.dumps({
                    "title": clip_title,
                    "description": clip_desc,
                    "hashtags": ["#shorts", "#ClipifyAI", "#viral"],
                    "tags": ["shorts", "clipify", src_clean[:30]],
                    "source_video": input_path.name,
                    "start_time": round(float(start_sec), 2),
                    "end_time": round(float(start_sec + clip_len), 2),
                    "duration": round(float(clip_len), 2),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        if not outputs:
            log("ERROR: All requested clips failed to render.")
            update_status("error", 0, "Render failed")
            return

        log("Registering project with Editor & Review Workspace...")

        # Register in main jobs dict for Review Editor integration
        with jobs_lock:
            jobs[job_id] = {
                "id": job_id,
                "status": "done",
                "progress": 100,
                "stage": "Finished",
                "detail": f"Instant Shorts ready ({len(outputs)} clips)",
                "outputs": outputs,
                "filename": input_path.name,
                "branding": {"logo": None, "text": ""},
                "mode": "instant"
            }

        with instant_jobs_lock:
            if job_id in instant_jobs:
                instant_jobs[job_id].update(
                    status="done",
                    progress=100,
                    stage="Finished",
                    outputs=outputs,
                    output_url=f"/media/{job_id}/{outputs[0]}",
                    filename=outputs[0],
                    duration=clip_len
                )
        log(f"🎉 Instant Clipping complete! Created {len(outputs)} Short{'s' if len(outputs) > 1 else ''}. Ready to preview, download, or edit.")

    except Exception as exc:
        log(f"ERROR: Unhandled exception in instant pipeline: {exc}")
        update_status("error", 0, str(exc))


@app.post("/api/instant/upload")
def instant_upload():
    """Upload a source video directly into an isolated instant clipping workspace."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file selected."}), 400

    job_id = str(uuid.uuid4())
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file.filename) or f"instant_{job_id[:8]}.mp4"
    dest = input_dir / safe_name
    file.save(dest)

    dur = _media_duration_seconds(str(dest))
    with instant_jobs_lock:
        instant_jobs[job_id] = {
            "id": job_id,
            "status": "ready",
            "progress": 0,
            "stage": "Video loaded",
            "filename": safe_name,
            "duration": dur,
            "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Source uploaded: {safe_name} ({dur:.1f}s)"],
            "outputs": [],
            "output_url": None,
        }

    return jsonify({"ok": True, "job_id": job_id, "filename": safe_name, "duration": dur})


@app.post("/api/instant/start")
def instant_start():
    """Launch the isolated lightning-fast instant clipping job."""
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id", "")).strip()
    youtube_url = str(data.get("youtube_url", "")).strip()
    target_dur = max(5.0, min(120.0, float(data.get("duration", 30.0))))
    layout = str(data.get("layout", "center_crop")).strip()
    captions = str(data.get("captions", "yes")).strip().lower()
    num_clips = max(1, min(10, int(data.get("num_clips", data.get("clips", 1)))))
    start_mode = str(data.get("start_mode", "auto")).strip()
    custom_start = max(0.0, float(data.get("custom_start", 0.0)))
    iteration = max(0, int(data.get("iteration", 0)))

    # If YouTube URL provided: verify whether existing job_id matches this exact video
    if youtube_url:
        if job_id:
            job_dir_check = JOBS / job_id
            yt_file = job_dir_check / "yt_url.txt"
            if not yt_file.exists() or yt_file.read_text(encoding="utf-8").strip() != youtube_url:
                # Video link is different from previous job -> spawn fresh isolated job
                job_id = str(uuid.uuid4())
                iteration = 0
        else:
            job_id = str(uuid.uuid4())
    elif not job_id:
        job_id = str(uuid.uuid4())

    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    out_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    if youtube_url:
        try:
            (job_dir / "yt_url.txt").write_text(youtube_url, encoding="utf-8")
        except Exception:
            pass

    input_path = None
    input_files = list(input_dir.glob("*.mp4")) + list(input_dir.glob("*.mov")) + list(input_dir.glob("*.mkv"))
    if input_files:
        input_path = max(input_files, key=lambda p: p.stat().st_mtime)

    # If job_id references an existing source from projects/jobs
    if not input_path:
        src_job_id = str(data.get("source_job_id", "")).strip()
        if src_job_id:
            src_dir = JOBS / src_job_id / "input"
            if src_dir.exists():
                src_files = list(src_dir.glob("*.mp4")) + list(src_dir.glob("*.mov"))
                if src_files:
                    input_path = max(src_files, key=lambda p: p.stat().st_mtime)

    if not input_path and not youtube_url:
        return jsonify({"ok": False, "error": "No source video or YouTube URL provided."}), 400

    with instant_jobs_lock:
        instant_jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "Queued",
            "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] Job queued (Iteration #{iteration + 1})."],
            "outputs": [],
            "output_url": None,
            "filename": input_path.name if input_path else "",
            "duration": target_dur,
            "num_clips": num_clips,
            "captions": captions,
            "iteration": iteration
        }

    threading.Thread(
        target=_instant_worker,
        args=(job_id, input_path, target_dur, layout, start_mode, custom_start, youtube_url, num_clips, captions, iteration),
        daemon=True
    ).start()

    return jsonify({"ok": True, "job_id": job_id, "status": "queued", "iteration": iteration})


@app.get("/api/instant/status/<job_id>")
def instant_status(job_id: str):
    """Poll progress, logs and output of an instant clipping job."""
    with instant_jobs_lock:
        job = instant_jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Instant job not found."}), 404
        return jsonify({"ok": True, **job})

@app.get("/api/metadata/<job_id>/<path:filename>")
def metadata(job_id: str, filename: str):
    """Return saved YouTube metadata for a generated Short."""
    job_dir = _safe_job_directory(job_id)
    if job_dir is None:
        return jsonify({"ok": False, "error": "Project not found."}), 404
    out_dir = job_dir / "output"
    safe = Path(filename).name
    stem = Path(safe).stem
    stem = re.sub(r"_edited(?:_\d+)?$", "", stem, flags=re.I)
    meta = out_dir / f"{stem}.json"
    if not meta.exists():
        vid_file = out_dir / safe
        if not vid_file.exists():
            return jsonify({"ok": False, "error": "Metadata not found."}), 404
        # Auto-create metadata for older/instant clips missing a sidecar JSON
        in_dir = job_dir / "input"
        src_name = next((p.stem for p in in_dir.iterdir() if p.is_file()), "") if in_dir.exists() else ""
        src_clean = re.sub(r"[_-]+", " ", src_name).strip() or re.sub(r"[_-]+", " ", stem).strip() or "Viral Moment"
        fallback_meta = {
            "title": f"{src_clean[:44]} 🔥",
            "description": f"Viral highlight from {src_clean}. #Shorts #ClipifyAI",
            "hashtags": ["#shorts", "#ClipifyAI", "#viral"],
            "tags": ["shorts", "clipify", src_clean[:30]],
            "source_video": src_name or safe,
        }
        try:
            meta.write_text(json.dumps(fallback_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return jsonify({"ok": True, **fallback_meta})
    try:
        return jsonify({"ok": True, **json.loads(meta.read_text(encoding="utf-8"))})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Metadata read failed: {exc}"}), 500


# --- Social Media Publishing & MCP Integration ---

@app.get("/api/publish/platforms")
def get_publish_platforms():
    """Return configured social platforms and account status."""
    from tools.mcp_publish import list_social_accounts
    return jsonify({"ok": True, "platforms": list_social_accounts()})


@app.post("/api/publish/credentials")
def save_publish_credentials():
    """Save API credentials for YouTube, Instagram, or TikTok."""
    from tools.mcp_publish import load_credentials, save_credentials
    data = request.get_json(silent=True) or {}
    platform = str(data.get("platform", "")).lower()
    if platform not in {"youtube", "instagram", "tiktok"}:
        return jsonify({"ok": False, "error": "Invalid platform specified."}), 400
    creds = load_credentials()
    if platform not in creds:
        creds[platform] = {}
    creds[platform].update({k: v for k, v in data.items() if k != "platform"})
    creds[platform]["enabled"] = True
    saved = save_credentials(creds)
    return jsonify({"ok": saved, "platform": platform, "configured": True})


def _normalize_search_title(t: str) -> str:
    """Normalize titles for matching across smart quotes, emojis, and varied punctuation."""
    if not t:
        return ""
    t = re.sub(r"[\u2018\u2019\u201a\u201b]", "'", t)
    t = re.sub(r"[\u201c\u201d\u201e\u201f]", '"', t)
    t = re.sub(r"[^\w\s']", " ", t)
    return " ".join(t.lower().split())


def _resolve_publish_video(job_id: str, filename: str, title: str = "") -> tuple[Path | None, Path | None]:
    """Resolve video path and sidecar metadata path across job directories, roots, and user data."""
    if not filename:
        return None, None

    clean_filename = filename.split("?")[0].split("#")[0].strip()
    direct = Path(clean_filename)
    if direct.is_file():
        meta = direct.parent / f"{direct.stem}.json"
        return direct.resolve(), (meta.resolve() if meta.is_file() else None)

    clean_name = direct.name
    stem = direct.stem
    base_stem = re.sub(r"(_edited|_clean|_custom|_with_subtitles|_subtitled|_captioned)(?:_\d+)?$", "", stem, flags=re.I)

    candidates_names = [
        clean_name,
        f"{stem}.mp4",
        f"{base_stem}.mp4",
        f"{base_stem}_clean.mp4",
        f"{base_stem}_with_subtitles.mp4",
        f"{base_stem}_edited.mp4",
        f"{base_stem}_subtitled.mp4",
        f"{base_stem}_captioned.mp4",
        f"{base_stem}_branded.mp4",
        f"{stem}.mov",
        f"{stem}.mkv",
        f"{stem}.webm",
    ]
    num_match = re.search(r"(\d+)$", base_stem)
    num: int | None = None
    if num_match:
        num = int(num_match.group(1))
        prefix = base_stem[:num_match.start(1)]
        candidates_names.extend([
            f"{prefix}{num:02d}.mp4",
            f"{prefix}{num}.mp4",
            f"{prefix}{num:02d}_clean.mp4",
            f"{prefix}{num}_clean.mp4",
            f"{prefix}{num:02d}_with_subtitles.mp4",
            f"{prefix}{num}_with_subtitles.mp4",
            f"{prefix}{num:02d}_edited.mp4",
            f"{prefix}{num}_edited.mp4",
        ])

    seen = set()
    names = [n for n in candidates_names if not (n in seen or seen.add(n))]

    search_dirs: list[Path] = []

    # Priority 1: Specified job directory (by safe ID or direct path)
    if job_id:
        jd = _safe_job_directory(job_id)
        if not jd and (Path(job_id).is_dir() or (ROOT / "jobs" / job_id).is_dir()):
            cand_p = Path(job_id) if Path(job_id).is_dir() else (ROOT / "jobs" / job_id)
            try:
                cand_p_res = cand_p.resolve()
                if cand_p_res.exists():
                    jd = cand_p_res
            except Exception:
                pass
        if jd and jd.is_dir():
            search_dirs.extend([jd / "output", jd, jd / "input"])

        local_appdata = os.environ.get("LOCALAPPDATA", "")
        roaming_appdata = os.environ.get("APPDATA", "")
        fallback_job_roots = [
            JOBS,
            USER_DATA_DIR / "jobs",
            ROOT / "jobs",
            Path.cwd() / "jobs",
        ]
        if local_appdata:
            fallback_job_roots.extend([
                Path(local_appdata) / "Programs" / "ClipifyAI" / "jobs",
                Path(local_appdata) / "ClipifyAI" / "jobs",
                Path(local_appdata) / "ClippedAI" / "jobs",
            ])
        if roaming_appdata:
            fallback_job_roots.extend([
                Path(roaming_appdata) / "ClipifyAI" / "jobs",
                Path(roaming_appdata) / "ClippedAI" / "jobs",
            ])
        for root in fallback_job_roots:
            cand = root / job_id
            if cand.is_dir():
                search_dirs.extend([cand / "output", cand, cand / "input"])

    # Priority 2: Common output directories
    search_dirs.extend([
        USER_DATA_DIR / "output",
        ROOT / "output",
        Path.cwd() / "output",
        USER_DATA_DIR / "narrate clips",
        USER_DATA_DIR / "input",
    ])

    norm_target_title = _normalize_search_title(title)

    def _find_in_dir(d: Path) -> tuple[Path | None, Path | None]:
        if not d.is_dir():
            return None, None
        for name in names:
            f = d / name
            if f.is_file() and f.stat().st_size >= 1024:
                meta = d / f"{base_stem}.json"
                if not meta.is_file():
                    meta = d / f"{stem}.json"
                return f.resolve(), (meta.resolve() if meta.is_file() else None)
        for pattern in (f"{base_stem}*.mp4", f"*{base_stem}*.mp4"):
            matches = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
            for m in matches:
                if m.is_file() and m.stat().st_size >= 1024:
                    meta = d / f"{base_stem}.json"
                    if not meta.is_file():
                        meta = d / f"{m.stem}.json"
                    return m.resolve(), (meta.resolve() if meta.is_file() else None)
        if norm_target_title:
            for jf in d.glob("*.json"):
                try:
                    meta_content = json.loads(jf.read_text(encoding="utf-8"))
                    cand_title = _normalize_search_title(meta_content.get("title", ""))
                    if cand_title and (cand_title == norm_target_title or norm_target_title in cand_title or cand_title in norm_target_title):
                        matching_video = d / f"{jf.stem}.mp4"
                        if matching_video.is_file() and matching_video.stat().st_size >= 1024:
                            return matching_video.resolve(), jf.resolve()
                        for v in sorted(d.glob(f"{jf.stem}*.mp4"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                            if v.is_file() and v.stat().st_size >= 1024:
                                return v.resolve(), jf.resolve()
                except Exception:
                    pass
        # Extra fallback: if directory has files matching short number
        if num is not None:
            num_patterns = (f"*{num:02d}*.mp4", f"*_{num}*.mp4")
            for pat in num_patterns:
                for candidate in sorted(d.glob(pat), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                    if candidate.is_file() and candidate.stat().st_size >= 1024 and not candidate.name.startswith("_tmp_"):
                        meta = d / f"{candidate.stem}.json"
                        return candidate.resolve(), (meta.resolve() if meta.is_file() else None)
        return None, None

    for d in search_dirs:
        try:
            f, m = _find_in_dir(d)
            if f:
                return f, m
        except OSError:
            continue

    # Priority 3: Scan all job folders under known job roots
    all_job_roots = [JOBS, USER_DATA_DIR / "jobs", ROOT / "jobs", Path.cwd() / "jobs"]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    roaming_appdata = os.environ.get("APPDATA", "")
    if local_appdata:
        all_job_roots.extend([
            Path(local_appdata) / "Programs" / "ClipifyAI" / "jobs",
            Path(local_appdata) / "ClipifyAI" / "jobs",
            Path(local_appdata) / "ClippedAI" / "jobs",
        ])
    if roaming_appdata:
        all_job_roots.extend([
            Path(roaming_appdata) / "ClipifyAI" / "jobs",
            Path(roaming_appdata) / "ClippedAI" / "jobs",
        ])

    for jr in all_job_roots:
        try:
            if not jr.is_dir():
                continue
            for j in sorted(jr.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if not j.is_dir():
                    continue
                for sub in ("output", ""):
                    target_dir = j / sub if sub else j
                    f, m = _find_in_dir(target_dir)
                    if f:
                        return f, m
        except OSError:
            continue

    return None, None


@app.post("/api/publish/upload")
def publish_short():
    """Publish a generated Short to YouTube, TikTok, Instagram, or export as package."""
    from tools.mcp_publish import (
        publish_youtube_short, publish_instagram_reel,
        publish_tiktok_video, export_social_package
    )
    data = request.get_json(silent=True) or {}
    platform = str(data.get("platform", "youtube")).lower()
    job_id = str(data.get("job_id", "")).strip()
    filename = str(data.get("filename", "")).strip()
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    privacy = str(data.get("privacy", "public")).lower()

    if not filename:
        return jsonify({"ok": False, "error": "Missing filename parameter."}), 400

    video_path, metadata_path = _resolve_publish_video(job_id, filename, title)
    if not video_path or not video_path.is_file():
        return jsonify({"ok": False, "error": f"Video file not found: {filename}"}), 404

    meta_path_str = str(metadata_path) if metadata_path and metadata_path.is_file() else None

    # Load title / description / tags from sidecar metadata if not provided
    if (not title or not description) and meta_path_str and Path(meta_path_str).is_file():
        try:
            with open(meta_path_str, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not title:
                title = meta.get("title", "")
            if not description:
                description = meta.get("description", "")
            if not tags and isinstance(meta.get("tags"), list):
                tags = meta.get("tags")
        except Exception:
            pass

    if platform == "youtube":
        res = publish_youtube_short(str(video_path), title or Path(filename).stem, description, tags, privacy)
    elif platform == "instagram":
        res = publish_instagram_reel(str(video_path), description or title)
    elif platform == "tiktok":
        res = publish_tiktok_video(str(video_path), title or description)
    elif platform in {"package", "export"}:
        res = export_social_package(str(video_path), meta_path_str)
    else:
        return jsonify({"ok": False, "error": f"Unsupported platform: {platform}"}), 400

    return jsonify(res)

@app.get("/api/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        outputs = list(job.get("outputs") or [])
        if not outputs and job.get("status") == "done":
            out_dir = JOBS / job_id / "output"
            if out_dir.exists():
                vfiles = [p for p in sorted(out_dir.iterdir()) if p.is_file() and p.suffix.lower() == ".mp4" and p.stat().st_size >= 1024]
                outputs = [p.name for p in vfiles if not p.name.startswith("_tmp_") and not p.name.endswith("_with_subtitles.mp4") and not p.stem.endswith("_clean")]
                if not outputs:
                    outputs = [p.name for p in vfiles if p.name.endswith("_with_subtitles.mp4")]
                if outputs:
                    job["outputs"] = outputs
        return jsonify(
            {
                "id": job["id"],
                "filename": job["filename"],
                "status": job["status"],
                "progress": job["progress"],
                "stage": job["stage"],
                "outputs": outputs,
                "min_duration": job.get("min_duration", 25),
                "max_duration": job.get("max_duration", 60),
                "mode": job.get("mode"),
                "model": job.get("model"),
                "font": job.get("font"),
                "branding": job.get("branding", {}),
                "detail": job.get("detail", ""),
                "return_code": job.get("return_code"),
                "event_persistence_error": job.get("event_persistence_error"),
                "elapsed": max(0, int(__import__("time").time() - float(job.get("stage_started", __import__("time").time())))) if job.get("stage_started") else 0,
            }
        )


@app.get("/api/events/<job_id>")
def events(job_id: str):
    def stream():
        sent = 0
        while True:
            new_events: list[Any] = []
            snapshot: dict[str, Any] = {}
            done: bool = False
            job: dict[str, Any] | None = None
            with jobs_lock:
                job = jobs.get(job_id)
                if job:
                    new_events = list(job.get("events", [])[sent:])
                    sent = len(job.get("events", []))
                    done = job.get("status") in {"done", "error"}
                    snapshot = {
                        "kind": "status",
                        "status": job.get("status"),
                        "progress": job.get("progress"),
                        "stage": job.get("stage"),
                        "outputs": job.get("outputs", []),
                        "min_duration": job.get("min_duration", 25),
                        "max_duration": job.get("max_duration", 60),
                        "detail": job.get("detail", ""),
                        "model": job.get("model"),
                        "font": job.get("font"),
                        "elapsed": max(0, int(__import__("time").time() - float(job.get("stage_started", __import__("time").time())))) if job.get("stage_started") else 0,
                    }
            if not job:
                job_dir = _safe_job_directory(job_id)
                journal = job_dir / "events.jsonl" if job_dir is not None else None
                if journal is None or not journal.is_file():
                    payload = {"kind": "error", "message": "Job not found."}
                    yield f"data: {json.dumps(payload)}\n\n"
                    return
                try:
                    with journal.open("r", encoding="utf-8") as stream_file:
                        for line in stream_file:
                            try:
                                record = json.loads(line)
                                event = record.get("event")
                                if isinstance(event, dict):
                                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                            except (json.JSONDecodeError, AttributeError):
                                continue
                except OSError as exc:
                    payload = {"kind": "error", "message": f"Saved job events could not be read: {type(exc).__name__}: {exc}"}
                    yield f"data: {json.dumps(payload)}\n\n"
                return
            for event in new_events:
                yield f"data: {json.dumps(event)}\n\n"
            yield f"data: {json.dumps(snapshot)}\n\n"
            if done:
                return
            threading.Event().wait(0.6)

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/media/<job_id>/<path:filename>")
def media(job_id: str, filename: str):
    job_dir = _safe_job_directory(job_id)
    if job_dir is None:
        return jsonify({"error": "Project not found."}), 404
    output_dir = job_dir / "output"
    return send_from_directory(output_dir, filename, as_attachment=False)


@app.get("/api/models")
def models():
    installed, error = _discover_ollama_models()
    payload = {
        "ok": bool(installed),
        "models": installed,
        "default": _default_model(installed),
        "count": len(installed),
        "error": error,
    }
    return jsonify(payload), (200 if installed else 503)


@app.route("/api/models/scan", methods=["GET", "POST"])
def scan_models():
    """Auto-scan all local drives and system paths for Ollama models and recover them."""
    recovered_models, path, error = _scan_and_recover_ollama_models()
    payload = {
        "ok": bool(recovered_models),
        "models": recovered_models,
        "default": _default_model(recovered_models),
        "count": len(recovered_models),
        "path": path,
        "error": error,
    }
    return jsonify(payload), (200 if recovered_models else 404)


_AI_CONFIG_PATH = USER_DATA_DIR / "settings" / "ai_model_config.json"
_ollama_download_state: dict[str, Any] = {"active": False, "model": "", "percent": 0, "status": "idle", "error": ""}

def _load_ai_config() -> dict:
    default_cfg = {
        "provider": os.getenv("CLIPPEDAI_AI_PROVIDER", "ollama"),
        "hf_token": os.getenv("HF_TOKEN", ""),
        "hf_model": os.getenv("CLIPPEDAI_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
    }
    try:
        if _AI_CONFIG_PATH.exists():
            with open(_AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_cfg.update(saved)
    except Exception as exc:
        logger.warning(f"Failed to read ai_model_config: {exc}")
    try:
        installed, _ = _discover_ollama_models()
        if installed and default_cfg.get("ollama_model") not in installed:
            default_cfg["ollama_model"] = _default_model(installed)
    except Exception:
        pass
    return default_cfg

def _save_ai_config(cfg: dict) -> None:
    try:
        _AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_AI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        if cfg.get("provider"):
            os.environ["CLIPPEDAI_AI_PROVIDER"] = cfg["provider"]
        if cfg.get("hf_token"):
            os.environ["HF_TOKEN"] = cfg["hf_token"]
        if cfg.get("hf_model"):
            os.environ["CLIPPEDAI_HF_MODEL"] = cfg["hf_model"]
        if cfg.get("ollama_model"):
            os.environ["OLLAMA_MODEL"] = cfg["ollama_model"]
    except Exception as exc:
        logger.warning(f"Failed to write ai_model_config: {exc}")

@app.get("/api/models/config")
def get_model_config():
    cfg = _load_ai_config()
    installed, _ = _discover_ollama_models()
    hf_token = cfg.get("hf_token", "")
    masked = (f"hf_...{hf_token[-4:]}" if len(hf_token) > 8 else ("hf_configured" if hf_token else ""))
    return jsonify({
        "ok": True,
        "provider": cfg.get("provider", "ollama"),
        "hf_token_configured": bool(hf_token),
        "hf_token_masked": masked,
        "hf_model": cfg.get("hf_model", "Qwen/Qwen2.5-7B-Instruct"),
        "available_hf_models": [
            {"id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen 2.5 7B Instruct (Recommended - Fast & Free)", "recommended": True},
            {"id": "meta-llama/Llama-3.2-3B-Instruct", "name": "Meta Llama 3.2 3B Instruct (Ultra-Fast - Free)", "recommended": False},
            {"id": "mistralai/Mistral-7B-Instruct-v0.3", "name": "Mistral 7B Instruct v0.3 (Free)", "recommended": False},
            {"id": "google/gemma-2-9b-it", "name": "Google Gemma 2 9B IT (Free)", "recommended": False}
        ],
        "ollama_models": installed,
        "default_ollama_model": _default_model(installed)
    })

@app.post("/api/models/config")
def update_model_config():
    payload = request.get_json(silent=True) or {}
    cfg = _load_ai_config()
    if "provider" in payload and payload["provider"] in ("ollama", "huggingface", "heuristic"):
        cfg["provider"] = payload["provider"]
    if "hf_token" in payload and payload["hf_token"] and not payload["hf_token"].startswith("hf_..."):
        cfg["hf_token"] = payload["hf_token"].strip()
    if "hf_model" in payload and payload["hf_model"]:
        cfg["hf_model"] = payload["hf_model"].strip()
    if "ollama_model" in payload and payload["ollama_model"]:
        cfg["ollama_model"] = payload["ollama_model"].strip()
    _save_ai_config(cfg)
    return jsonify({"ok": True, "config": cfg})


def _dir_usage_info(path_str: str) -> dict[str, Any]:
    p = Path(path_str)
    total_bytes = 0
    file_count = 0
    if p.exists():
        try:
            for root_dir, _, files in os.walk(p):
                for fn in files:
                    file_count += 1
                    try:
                        total_bytes += (Path(root_dir) / fn).stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
    free_bytes = 0
    try:
        probe = p if p.exists() else p.parent
        while probe and not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if probe and probe.exists():
            free_bytes = shutil.disk_usage(probe).free
    except OSError:
        pass

    def _fmt_bytes(b: int) -> str:
        if b >= 1024 ** 3:
            return f"{b / (1024 ** 3):.2f} GB"
        if b >= 1024 ** 2:
            return f"{b / (1024 ** 2):.1f} MB"
        if b >= 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b} B"

    return {
        "used_bytes": total_bytes,
        "used_human": _fmt_bytes(total_bytes),
        "free_bytes": free_bytes,
        "free_human": _fmt_bytes(free_bytes),
        "file_count": file_count,
        "exists": p.exists(),
    }


@app.get("/api/storage/config")
def get_storage_config():
    cfg = _load_storage_config()
    defaults = {k: str(v) for k, v in _default_storage_paths().items()}
    items = [
        {
            "key": "jobs_dir",
            "title": "Output Clips & Jobs",
            "description": "Where imported videos, transcription caches, and rendered Shorts are stored.",
            "path": cfg["jobs_dir"],
            "default_path": defaults["jobs_dir"],
            **_dir_usage_info(cfg["jobs_dir"]),
        },
        {
            "key": "ollama_models_dir",
            "title": "Ollama Models",
            "description": "Directory where local Ollama LLM weights are stored (OLLAMA_MODELS).",
            "path": cfg["ollama_models_dir"],
            "default_path": defaults["ollama_models_dir"],
            **_dir_usage_info(cfg["ollama_models_dir"]),
        },
        {
            "key": "cache_dir",
            "title": "AI, Whisper & Hugging Face Cache",
            "description": "Cache for WhisperX, Hugging Face weights (HF_HOME), and Narrate thumbnails.",
            "path": cfg["cache_dir"],
            "default_path": defaults["cache_dir"],
            **_dir_usage_info(cfg["cache_dir"]),
        },
    ]
    return jsonify({"ok": True, "locations": items, "config": cfg})


@app.post("/api/storage/browse")
def browse_storage_folder():
    payload = request.get_json(silent=True) or {}
    initial = str(payload.get("current_path", "")).strip()
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = 'Select Clipify AI storage folder'; "
        f"if (Test-Path '{initial.replace(chr(39), chr(39)*2)}') {{ $d.SelectedPath = '{initial.replace(chr(39), chr(39)*2)}' }}; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }"
    )
    try:
        res = _run_hidden(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_script],
            capture_output=True, text=True, timeout=90, check=False,
        )
        chosen = (res.stdout or "").strip()
        if chosen:
            return jsonify({"ok": True, "path": chosen})
        return jsonify({"ok": False, "cancelled": True, "error": "Folder selection cancelled."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/storage/update")
def update_storage_config():
    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip()
    new_path_str = str(payload.get("new_path", "")).strip()
    move_data = bool(payload.get("move_data", False))
    reset_default = bool(payload.get("reset_default", False))

    defaults = {k: str(v) for k, v in _default_storage_paths().items()}
    if key not in defaults:
        return jsonify({"ok": False, "error": "Invalid storage key."}), 400
    if reset_default:
        new_path_str = defaults[key]
    if not new_path_str:
        return jsonify({"ok": False, "error": "Target folder path cannot be empty."}), 400

    cfg = _load_storage_config()
    old_path = Path(cfg[key])
    new_path = Path(new_path_str).expanduser()

    try:
        new_path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Cannot create folder '{new_path}': {exc}"}), 400

    moved_files = 0
    moved_bytes = 0
    skipped_files = 0
    if move_data and old_path.exists() and old_path.resolve() != new_path.resolve():
        for root_dir, _, files in os.walk(old_path):
            rel = Path(root_dir).relative_to(old_path)
            dest_dir = new_path / rel
            dest_dir.mkdir(parents=True, exist_ok=True)
            for fn in files:
                src_f = Path(root_dir) / fn
                dst_f = dest_dir / fn
                try:
                    sz = src_f.stat().st_size
                    shutil.copy2(src_f, dst_f)
                    moved_files += 1
                    moved_bytes += sz
                    try:
                        src_f.unlink()
                    except OSError:
                        pass
                except Exception:
                    skipped_files += 1
        # Clean empty directories left behind
        for root_dir, dirs, files in os.walk(old_path, topdown=False):
            if not dirs and not files:
                try:
                    Path(root_dir).rmdir()
                except OSError:
                    pass

    cfg[key] = str(new_path)
    _STORAGE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORAGE_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _apply_storage_config(cfg)

    return jsonify({
        "ok": True,
        "key": key,
        "path": str(new_path),
        "moved_files": moved_files,
        "moved_bytes": moved_bytes,
        "skipped_files": skipped_files,
        "message": (
            f"Updated to {new_path} (moved {moved_files} file(s))."
            if move_data else f"Storage path updated to {new_path}."
        ),
    })

@app.route("/api/models/verify-hf", methods=["POST"])
@app.post("/api/models/huggingface/verify")
def verify_hf_token():
    payload = request.get_json(silent=True) or {}
    raw_input = (payload.get("token") or payload.get("hf_token") or payload.get("url") or "").strip()

    if "huggingface.co/settings/tokens" in raw_input.lower() and "hf_" not in raw_input:
        return jsonify({
            "ok": False,
            "error": "You pasted the settings page URL. Please copy an Access Token from that page (starts with hf_...) and paste it here."
        }), 400

    token = raw_input
    if token.startswith("Bearer "):
        token = token[7:].strip()
    token = token.strip("\"' \t\r\n")

    # Extract hf_ token if user pasted a full URL or sentence containing their token
    hf_match = re.search(r"hf_[A-Za-z0-9]+", token)
    if hf_match:
        token = hf_match.group(0)
    if not token or token.startswith("hf_..."):
        cfg = _load_ai_config()
        token = cfg.get("hf_token", "")
    if not token:
        return jsonify({"ok": False, "error": "Please enter a valid Hugging Face token (starts with hf_)."}), 400
    try:
        req = urllib.request.Request(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "ClipifyAI/4.0.4"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            user_name = data.get("name", "User")
            user_type = data.get("type", "user")
            cfg = _load_ai_config()
            cfg["hf_token"] = token
            cfg["provider"] = "huggingface"
            _save_ai_config(cfg)
            return jsonify({"ok": True, "name": user_name, "type": user_type, "message": f"Verified Hugging Face token for @{user_name}"})
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return jsonify({"ok": False, "error": "Invalid Hugging Face token. Please check your token at huggingface.co/settings/tokens."}), 401
        cfg = _load_ai_config()
        cfg["hf_token"] = token
        _save_ai_config(cfg)
        return jsonify({"ok": True, "name": "Cloud User", "message": f"Token saved (HF returned {exc.code})"})
    except Exception as exc:
        cfg = _load_ai_config()
        cfg["hf_token"] = token
        _save_ai_config(cfg)
        return jsonify({"ok": True, "name": "Local User", "message": "Token saved locally."})

@app.post("/api/models/ollama/download")
def download_ollama_model():
    payload = request.get_json(silent=True) or {}
    model_name = payload.get("model", "").strip()
    if not model_name:
        return jsonify({"ok": False, "error": "Model name is required (e.g. qwen2.5:3b)"}), 400
    if _ollama_download_state["active"]:
        return jsonify({"ok": False, "error": f"Another download is already in progress ({_ollama_download_state['model']})"}), 409

    def _pull_thread():
        _ollama_download_state["active"] = True
        _ollama_download_state["model"] = model_name
        _ollama_download_state["percent"] = 0
        _ollama_download_state["status"] = "Starting download..."
        _ollama_download_state["error"] = ""
        try:
            exe = shutil.which("ollama")
            if not exe:
                for candidate in [
                    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                    Path("C:/Program Files/Ollama/ollama.exe"),
                    Path("C:/Users") / os.environ.get("USERNAME", "") / "AppData/Local/Programs/Ollama/ollama.exe"
                ]:
                    if candidate.exists():
                        exe = str(candidate)
                        break
            if not exe:
                _ollama_download_state["error"] = "Ollama executable not found on PC."
                _ollama_download_state["status"] = "Failed"
                return
            proc = subprocess.Popen([exe, "pull", model_name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            if proc.stdout is not None:
                for line in proc.stdout:
                    line_str = line.strip()
                    if "%" in line_str:
                        m = re.search(r"(\d{1,3})%", line_str)
                        if m:
                            _ollama_download_state["percent"] = int(m.group(1))
                            _ollama_download_state["status"] = f"Downloading {model_name} ({m.group(1)}%)"
                    elif "verifying" in line_str.lower():
                        _ollama_download_state["status"] = "Verifying checksums..."
                    elif "writing manifest" in line_str.lower():
                        _ollama_download_state["status"] = "Writing manifest..."
            proc.wait()
            if proc.returncode == 0:
                _ollama_download_state["percent"] = 100
                _ollama_download_state["status"] = "Completed successfully!"
            else:
                _ollama_download_state["error"] = f"Download failed with exit code {proc.returncode}"
                _ollama_download_state["status"] = "Failed"
        except Exception as exc:
            _ollama_download_state["error"] = str(exc)
            _ollama_download_state["status"] = "Failed"
        finally:
            _ollama_download_state["active"] = False

    t = threading.Thread(target=_pull_thread, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": f"Download of {model_name} started."})

@app.get("/api/models/ollama/download-status")
def get_ollama_download_status():
    return jsonify({"ok": True, **_ollama_download_state})


@app.post("/api/models/ollama/delete")
def delete_ollama_model():
    payload = request.get_json(silent=True) or {}
    model_name = payload.get("model", "").strip()
    if not model_name:
        return jsonify({"ok": False, "error": "Model name is required"}), 400
    exe = shutil.which("ollama") or _find_ollama_exe()
    if not exe:
        return jsonify({"ok": False, "error": "Ollama executable not found on PC."}), 404
    try:
        res = _run_hidden([exe, "rm", model_name], capture_output=True, text=True, timeout=30, check=False)
        if res.returncode == 0:
            return jsonify({"ok": True, "message": f"Successfully deleted model '{model_name}'."})
        else:
            return jsonify({"ok": False, "error": res.stderr or res.stdout or f"Could not remove {model_name}"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/models/ollama/details")
def ollama_models_details():
    """Returns all locally installed Ollama models with their exact sizes and IDs."""
    exe = _find_ollama_exe()
    installed_list = []
    if exe:
        try:
            res = _run_hidden([exe, "list"], capture_output=True, text=True, timeout=8, check=False)
            if res.returncode == 0 and res.stdout:
                lines = res.stdout.strip().splitlines()
                if len(lines) > 1:
                    for line in lines[1:]:
                        parts = re.split(r"\s{2,}", line.strip())
                        if parts and parts[0]:
                            name = parts[0].strip()
                            size = parts[2].strip() if len(parts) > 2 else ""
                            modified = parts[3].strip() if len(parts) > 3 else ""
                            installed_list.append({"name": name, "size": size, "modified": modified})
        except Exception:
            pass

    # Fallback to HTTP tag discovery
    if not installed_list:
        models_raw, _ = _discover_ollama_models()
        for m in models_raw:
            installed_list.append({"name": m, "size": "", "modified": ""})

    # Fallback to disk manifests
    if not installed_list:
        disk_models = _read_models_from_all_stores()
        for m in disk_models:
            installed_list.append({"name": m["name"], "size": m.get("size", ""), "modified": "On disk"})

    # If any model exists without size, fill size from disk manifests
    if installed_list and any(not m.get("size") for m in installed_list):
        disk_map = {m["name"]: m.get("size", "") for m in _read_models_from_all_stores()}
        for item in installed_list:
            if not item.get("size") and item.get("name") in disk_map:
                item["size"] = disk_map[item["name"]]

    cfg = _load_ai_config()
    default_model = cfg.get("ollama_model")
    if not default_model or default_model not in [m["name"] for m in installed_list]:
        model_names = [m["name"] for m in installed_list]
        default_model = _default_model(model_names) if model_names else (default_model or "qwen2.5:3b")

    return jsonify({
        "ok": True,
        "models": installed_list,
        "default": default_model,
        "count": len(installed_list),
    })


@app.get("/api/fonts")
def fonts():
    # Curated names are intentionally limited to fonts that ASS/DirectWrite can resolve on normal Windows installs,
    # plus the Montserrat font already used by this project when installed in the project's fonts/ folder.
    available = ["Montserrat Extra Bold", "Arial", "Arial Black", "Segoe UI", "Segoe UI Black", "Impact", "Tahoma", "Trebuchet MS", "Verdana", "Calibri", "Aptos", "Comic Sans MS", "Georgia"]
    return jsonify({"fonts": available, "default": "Montserrat Extra Bold"})


@app.get("/api/projects")
def projects():
    items = []
    for d in sorted(JOBS.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        if not d.is_dir() or d.name.startswith("."):
            continue
        inp = d / "input"
        out = d / "output"
        videos = [x.name for x in inp.iterdir() if x.is_file() and x.suffix.lower() in {".mp4",".mov",".mkv",".webm",".avi",".m4v"}] if inp.exists() else []
        outputs = [x.name for x in out.iterdir() if x.is_file() and x.suffix.lower() == ".mp4" and not x.name.startswith("_tmp_") and not x.stem.endswith("_clean")] if out.exists() else []
        job = jobs.get(d.name, {})
        meta_path = d / "project.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        except (OSError, ValueError):
            meta = {}
        output_metadata = {}
        for output in outputs:
            metadata_path = out / f"{Path(output).stem}.json"
            try:
                output_metadata[output] = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            except (OSError, ValueError):
                output_metadata[output] = {}
        items.append({"id": d.name, "name": str(meta.get("name", "")).strip(), "source": videos[0] if videos else job.get("filename"), "outputs": outputs,
                      "output_metadata": output_metadata,
                      "status": job.get("status", "saved"), "mode": job.get("mode"), "model": job.get("model"),
                      "updated": d.stat().st_mtime})
    return jsonify({"projects": items})


@app.post("/api/projects/<job_id>/rename")
def rename_project(job_id: str):
    project_dir = _safe_job_directory(job_id)
    if project_dir is None or not project_dir.is_dir() or job_id.startswith("."):
        return jsonify({"error": "Project not found."}), 404
    data = request.get_json(silent=True) or {}
    name = re.sub(r"\s+", " ", str(data.get("name", "")).strip())[:80]
    if not name:
        return jsonify({"error": "Enter a project name."}), 400
    try:
        (project_dir / "project.json").write_text(json.dumps({"name": name}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return jsonify({"error": f"Could not rename project: {exc}"}), 500
    return jsonify({"ok": True, "name": name})


@app.delete("/api/projects/<job_id>")
def delete_project(job_id: str):
    project_dir = _safe_job_directory(job_id)
    if project_dir is None or not project_dir.is_dir() or job_id.startswith("."):
        return jsonify({"error": "Project not found."}), 404
    trash_dir = JOBS / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / job_id
    if target.exists():
        shutil.rmtree(target)
    try:
        shutil.move(str(project_dir), str(target))
    except OSError as exc:
        return jsonify({"error": f"Could not delete project: {exc}"}), 500
    with jobs_lock:
        jobs.pop(job_id, None)
    return jsonify({"ok": True})


@app.get("/api/projects/trash")
def trashed_projects():
    trash_dir = JOBS / ".trash"
    items = []
    if not trash_dir.exists():
        return jsonify({"projects": items})
    for d in sorted(trash_dir.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        if not d.is_dir():
            continue
        meta_path = d / "project.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        except (OSError, ValueError):
            meta = {}
        items.append({"id": d.name, "name": str(meta.get("name", "")).strip(), "updated": d.stat().st_mtime})
    return jsonify({"projects": items})


@app.post("/api/projects/<job_id>/restore")
def restore_project(job_id: str):
    target = _safe_job_directory(job_id)
    trash_root = (JOBS / ".trash").resolve()
    try:
        source = (trash_root / job_id).resolve()
    except (OSError, RuntimeError, ValueError):
        return jsonify({"error": "Deleted project is not available to restore."}), 404
    if (target is None or source.parent != trash_root or not source.is_dir()
            or target.exists() or job_id.startswith(".")):
        return jsonify({"error": "Deleted project is not available to restore."}), 404
    try:
        shutil.move(str(source), str(target))
    except OSError as exc:
        return jsonify({"error": f"Could not restore project: {exc}"}), 500
    return jsonify({"ok": True})

@app.get("/api/projects/<job_id>")
def project_detail(job_id: str):
    d = _safe_job_directory(job_id)
    if d is None or not d.is_dir():
        return jsonify({"error": "Project not found."}), 404
    inp, out = d / "input", d / "output"
    videos = [x.name for x in inp.iterdir() if x.is_file()] if inp.exists() else []
    files = [x.name for x in out.iterdir() if x.is_file()] if out.exists() else []
    return jsonify({"id": job_id, "input": videos, "output": files, "job": jobs.get(job_id, {})})

@app.get("/api/assets/<job_id>")
def project_assets(job_id: str):
    d = _safe_job_directory(job_id)
    if d is None or not d.is_dir():
        return jsonify({"error": "Project not found."}), 404
    assets=[]
    for base in (d / "input", d / "output"):
        if base.exists():
            for f in sorted(base.iterdir()):
                if f.is_file():
                    assets.append({"name": f.name, "kind": "source" if base.name == "input" else "output", "size": f.stat().st_size,
                                   "url": f"/project-media/{job_id}/{base.name}/{f.name}"})
    return jsonify({"assets": assets})

@app.get("/project-media/<job_id>/<folder>/<path:filename>")
def project_media(job_id: str, folder: str, filename: str):
    if folder not in {"input", "output"}:
        return jsonify({"error": "Invalid folder."}), 400
    job_dir = _safe_job_directory(job_id)
    if job_dir is None:
        return jsonify({"error": "Project not found."}), 404
    return send_from_directory(job_dir / folder, filename, as_attachment=False)

@app.post("/api/projects/sync")
def sync_project():
    """Receives portable project data from Clipify AI mobile (Android) or LAN desktop client."""
    data = request.get_json(silent=True) or {}
    raw_id = str(data.get("project_id", "")).strip()
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_id) if raw_id else f"sync_{uuid.uuid4().hex[:8]}"
    project_dir = _safe_job_directory(clean_id)
    if project_dir is None:
        return jsonify({"error": "Invalid project_id."}), 400
    try:
        (project_dir / "input").mkdir(parents=True, exist_ok=True)
        (project_dir / "output").mkdir(parents=True, exist_ok=True)
        title = str(data.get("title", data.get("name", "Synced Project"))).strip()
        project_meta = {
            "name": title,
            "project_id": clean_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source": data.get("source_media", {}).get("filename", "mobile_clip.mp4") if isinstance(data.get("source_media"), dict) else "mobile_clip.mp4",
            "data": data,
        }
        (project_dir / "project.json").write_text(json.dumps(project_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "project_id": clean_id, "message": "Project synced successfully."})
    except Exception as exc:
        return jsonify({"error": f"Failed to sync project: {exc}"}), 500

@app.route("/api/open-input-folder", methods=["GET", "POST"])
def open_input_folder():
    """Opens the local input / source video folder in Windows File Explorer (or default system file manager)."""
    data = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    elif request.args:
        data = request.args.to_dict()

    job_id = data.get("jobId") or data.get("job_id")
    target_dir: Path | None = None

    # 1. If explicit job_id is provided, check its input folder first
    if job_id:
        safe_job = _safe_job_directory(str(job_id).strip())
        if safe_job:
            cand = safe_job / "input"
            if cand.exists() and cand.is_dir():
                target_dir = cand
            elif safe_job.exists():
                target_dir = safe_job

    # 2. Check top-level input directory
    if not target_dir:
        cand = (ROOT / "input").resolve()
        if cand.exists():
            target_dir = cand

    if not target_dir:
        cand = (USER_DATA_DIR / "input").resolve()
        if cand.exists():
            target_dir = cand

    # 3. Check most recent job with input files
    if not target_dir and JOBS.exists():
        try:
            for d in sorted(JOBS.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if d.is_dir() and not d.name.startswith("."):
                    cand = d / "input"
                    if cand.exists() and cand.is_dir() and any(cand.iterdir()):
                        target_dir = cand.resolve()
                        break
        except Exception:
            pass

    # 4. Fallback: ensure ROOT / "input" exists
    if not target_dir:
        target_dir = (ROOT / "input").resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

    opened = False
    error_msg = None
    try:
        target_str = str(target_dir)
        if sys.platform == "win32":
            try:
                os.startfile(target_str)
                opened = True
            except Exception:
                subprocess.Popen(["explorer.exe", target_str])
                opened = True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_str])
            opened = True
        else:
            subprocess.Popen(["xdg-open", target_str])
            opened = True
    except Exception as exc:
        error_msg = str(exc)

    return jsonify({
        "ok": True,
        "opened": opened,
        "path": str(target_dir),
        "error": error_msg
    })


@app.route("/api/open-output-folder", methods=["GET", "POST"])
def open_output_folder():
    """Opens the local output folder in Windows File Explorer (or default system file manager)."""
    data = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    elif request.args:
        data = request.args.to_dict()

    job_id = data.get("jobId") or data.get("job_id")
    target_dir: Path | None = None

    # 1. If explicit job_id is provided, check its output folder first
    if job_id:
        safe_job = _safe_job_directory(str(job_id).strip())
        if safe_job:
            cand = safe_job / "output"
            if cand.exists() and cand.is_dir():
                target_dir = cand
            elif safe_job.exists():
                target_dir = safe_job

    # 2. Check top-level output directory (where standalone renders and exported shorts go)
    if not target_dir:
        cand = (ROOT / "output").resolve()
        if cand.exists() and any(cand.iterdir()):
            target_dir = cand

    if not target_dir:
        cand = (USER_DATA_DIR / "output").resolve()
        if cand.exists() and any(cand.iterdir()):
            target_dir = cand

    # 3. Check most recent job with output files
    if not target_dir and JOBS.exists():
        try:
            for d in sorted(JOBS.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if d.is_dir() and not d.name.startswith("."):
                    cand = d / "output"
                    if cand.exists() and cand.is_dir() and any(cand.iterdir()):
                        target_dir = cand.resolve()
                        break
        except Exception:
            pass

    # 4. Fallback: ensure ROOT / "output" exists
    if not target_dir:
        target_dir = (ROOT / "output").resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

    opened = False
    error_msg = None
    try:
        target_str = str(target_dir)
        if sys.platform == "win32":
            try:
                os.startfile(target_str)
                opened = True
            except Exception:
                subprocess.Popen(["explorer.exe", target_str])
                opened = True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_str])
            opened = True
        else:
            subprocess.Popen(["xdg-open", target_str])
            opened = True
    except Exception as exc:
        error_msg = str(exc)

    return jsonify({
        "ok": True,
        "opened": opened,
        "path": str(target_dir),
        "error": error_msg
    })


def _scan_cache_and_media() -> dict[str, Any]:
    """Scans all storage locations for cached transcriptions, temporary files,
    and imported YouTube media.
    """
    dirs = set()
    dirs.add(USER_DATA_DIR.resolve())
    dirs.add(ROOT.resolve())
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        for name in ["ClippedAI", "ClipifyAI", os.path.join("Programs", "ClipifyAI")]:
            p = Path(local_app) / name
            if p.is_dir():
                dirs.add(p.resolve())

    yt_files: list[Path] = []
    cache_files: list[Path] = []
    empty_job_dirs: list[Path] = []

    for base in dirs:
        jobs_dir = base / "jobs"
        if jobs_dir.is_dir():
            for j in jobs_dir.iterdir():
                if not j.is_dir():
                    continue
                inp = j / "input"
                out = j / "output"
                has_outputs = out.is_dir() and any(
                    f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
                    for f in out.iterdir()
                )
                if inp.is_dir():
                    for f in inp.iterdir():
                        if not f.is_file():
                            continue
                        name_low = f.name.lower()
                        if name_low.startswith("youtube.") or name_low.endswith((".part", ".ytdl", ".temp")):
                            yt_files.append(f)
                        elif name_low.endswith(("_transcription.pkl", ".pkl", ".tmp")):
                            cache_files.append(f)

                diag = j / "diagnostics"
                if diag.is_dir():
                    for f in diag.iterdir():
                        if f.is_file() and f.suffix.lower() in {".log", ".jsonl", ".tmp"}:
                            cache_files.append(f)

                if not has_outputs and inp.is_dir():
                    empty_job_dirs.append(j)

        inp_base = base / "input"
        if inp_base.is_dir():
            for f in inp_base.iterdir():
                if not f.is_file():
                    continue
                name_low = f.name.lower()
                if name_low.startswith("youtube.") or name_low.endswith((".part", ".ytdl")):
                    yt_files.append(f)
                elif name_low.endswith(("_transcription.pkl", ".pkl", ".tmp")):
                    cache_files.append(f)

        c_dir = base / "cache"
        if c_dir.is_dir():
            for f in c_dir.rglob("*"):
                if f.is_file():
                    cache_files.append(f)

        t_dir = base / "trash"
        if t_dir.is_dir():
            for f in t_dir.rglob("*"):
                if f.is_file():
                    cache_files.append(f)

    yt_unique = list({p.resolve(): p for p in yt_files if p.exists()}.values())
    cache_unique = list({p.resolve(): p for p in cache_files if p.exists()}.values())

    yt_bytes = sum(p.stat().st_size for p in yt_unique if p.is_file())
    cache_bytes = sum(p.stat().st_size for p in cache_unique if p.is_file())

    def _format_bytes(b: int) -> str:
        val = float(b)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if val < 1024.0 or unit == "TB":
                return f"{val:.1f} {unit}" if unit in ("MB", "GB", "TB") else f"{int(val)} {unit}"
            val /= 1024.0
        return f"{b} B"

    return {
        "yt_files": yt_unique,
        "cache_files": cache_unique,
        "empty_job_dirs": empty_job_dirs,
        "yt_count": len(yt_unique),
        "yt_bytes": yt_bytes,
        "yt_formatted": _format_bytes(yt_bytes),
        "cache_count": len(cache_unique),
        "cache_bytes": cache_bytes,
        "cache_formatted": _format_bytes(cache_bytes),
        "total_bytes": yt_bytes + cache_bytes,
        "total_formatted": _format_bytes(yt_bytes + cache_bytes),
    }


@app.route("/api/cache/status", methods=["GET"])
def cache_status():
    """Returns storage usage of cache files and imported YouTube media."""
    scan = _scan_cache_and_media()
    return jsonify({
        "ok": True,
        "total_bytes": scan["total_bytes"],
        "total_formatted": scan["total_formatted"],
        "yt_count": scan["yt_count"],
        "yt_bytes": scan["yt_bytes"],
        "yt_formatted": scan["yt_formatted"],
        "cache_count": scan["cache_count"],
        "cache_bytes": scan["cache_bytes"],
        "cache_formatted": scan["cache_formatted"],
    })


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """Clears transcription cache, thumbnails, temporary files, and imported YouTube videos."""
    scan = _scan_cache_and_media()
    freed_bytes = 0
    yt_deleted = 0
    cache_deleted = 0

    # 1. Delete imported YouTube videos
    yt_list: list[Path] = scan.get("yt_files", [])
    for p in yt_list:
        try:
            if p.is_file():
                sz = p.stat().st_size
                p.unlink(missing_ok=True)
                freed_bytes += sz
                yt_deleted += 1
        except Exception:
            pass

    # 2. Delete cache files
    cache_list: list[Path] = scan.get("cache_files", [])
    for p in cache_list:
        try:
            if p.is_file():
                sz = p.stat().st_size
                p.unlink(missing_ok=True)
                freed_bytes += sz
                cache_deleted += 1
        except Exception:
            pass

    # 3. Clean empty job dirs without outputs
    for jd in scan["empty_job_dirs"]:
        try:
            inp = jd / "input"
            if inp.is_dir() and not any(inp.iterdir()):
                shutil.rmtree(jd, ignore_errors=True)
        except Exception:
            pass

    # 4. Clean jobs dict in memory
    with jobs_lock:
        to_del = []
        for jid, jinfo in jobs.items():
            if jinfo.get("status") in {"uploaded", "finished", "error", "ready"}:
                j_dir = JOBS / jid
                if not j_dir.exists() or not any(j_dir.iterdir()):
                    to_del.append(jid)
        for jid in to_del:
            jobs.pop(jid, None)

    def _fmt(b: int) -> str:
        val = float(b)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if val < 1024.0 or unit == "TB":
                return f"{val:.1f} {unit}" if unit in ("MB", "GB", "TB") else f"{int(val)} {unit}"
            val /= 1024.0
        return f"{b} B"

    formatted = _fmt(freed_bytes)
    return jsonify({
        "ok": True,
        "freed_bytes": freed_bytes,
        "freed_formatted": formatted,
        "yt_removed": yt_deleted,
        "cache_removed": cache_deleted,
        "message": f"Successfully cleared {formatted} of disk space ({yt_deleted} YouTube video(s) and {cache_deleted} cache file(s) removed)."
    })

APP_VERSION = "v5.0.7"
try:
    _v_file = ROOT / "version.json"
    if _v_file.exists():
        _v_data = json.loads(_v_file.read_text(encoding="utf-8"))
        if _v_data.get("version"):
            APP_VERSION = str(_v_data["version"]).strip()
except Exception:
    pass
GITHUB_REPO = "sherlock-dev-ai/Clipify-AI-Video-Clipper-FREE"


def _urlopen_with_ssl_fallback(req: urllib.request.Request | str, timeout: float = 30.0):
    """Safely open an HTTPS URL with certifi, system trust, unverified SSL, and curl fallback."""
    import ssl
    # 1. Try certifi if available
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        pass

    # 2. Try standard system context
    try:
        ctx = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        pass

    # 3. Fallback to unverified SSL context (bypasses Windows local issuer certificate missing)
    try:
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        pass

    # 4. Fallback to default urlopen
    return urllib.request.urlopen(req, timeout=timeout)


def _download_file_resilient(url: str, dest_path: Path, timeout: float = 120.0) -> bool:
    """Download a file with SSL fallbacks, curl, and powershell to ensure zero certificate failures."""
    # 1. Try Python urllib with SSL fallback
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ClipifyAI-Updater"})
        with _urlopen_with_ssl_fallback(req, timeout=timeout) as resp:
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
        if dest_path.is_file() and dest_path.stat().st_size > 1024:
            return True
    except Exception:
        pass

    # 2. Try native Windows curl.exe (uses Windows Schannel SSL store, ignores Python cert issues)
    curl_bin = shutil.which("curl") or shutil.which("curl.exe")
    if curl_bin:
        try:
            res = _run_hidden([curl_bin, "-L", "-k", "-s", "--max-time", str(int(timeout)), "-o", str(dest_path), url], timeout=timeout + 10, check=False)
            if res.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 1024:
                return True
        except Exception:
            pass

    # 3. Try PowerShell WebClient with SSL verification bypass
    ps_bin = shutil.which("powershell") or shutil.which("powershell.exe")
    if ps_bin:
        try:
            ps_cmd = f"[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {{$true}}; (New-Object System.Net.WebClient).DownloadFile('{url}', '{dest_path}')"
            res = _run_hidden([ps_bin, "-NoProfile", "-Command", ps_cmd], timeout=timeout + 10, check=False)
            if res.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 1024:
                return True
        except Exception:
            pass

    return False


@app.route("/api/updater/check", methods=["GET"])
def updater_check():
    """Checks GitHub for the latest release and local Git status."""
    result: dict[str, Any] = {
        "current_version": APP_VERSION,
        "latest_version": APP_VERSION,
        "update_available": False,
        "release_name": "",
        "release_url": f"https://github.com/{GITHUB_REPO}/releases",
        "published_at": "",
        "body": "",
        "is_git": (ROOT / ".git").is_dir(),
        "git_behind": False,
        "error": None,
    }
    # 1. Check GitHub API for latest release
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ClipifyAI-Updater",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with _urlopen_with_ssl_fallback(req, timeout=12.0) as resp:
            if resp.status == 200:
                rel = json.loads(resp.read().decode("utf-8"))
                latest_tag = (rel.get("tag_name") or "").strip()
                result["latest_version"] = latest_tag or APP_VERSION
                result["release_name"] = rel.get("name") or latest_tag
                result["release_url"] = rel.get("html_url") or result["release_url"]
                result["published_at"] = rel.get("published_at", "")
                result["body"] = (rel.get("body") or "")[:500]

                curr_norm = APP_VERSION.lstrip("v").strip()
                late_norm = latest_tag.lstrip("v").strip()
                if late_norm and curr_norm != late_norm:
                    result["update_available"] = True
    except Exception as e:
        result["error"] = str(e)

    # 2. If inside a git repository, check git status
    if result["is_git"]:
        try:
            git_bin = shutil.which("git") or shutil.which("git.exe") or "git"
            _run_hidden([git_bin, "fetch", "--dry-run"], cwd=str(ROOT), timeout=15, check=False)
            status = _run_hidden([git_bin, "status", "-uno"], cwd=str(ROOT), timeout=15, check=False)
            if status.returncode == 0:
                out = (status.stdout or "").lower()
                if "your branch is behind" in out or "can be fast-forwarded" in out:
                    result["update_available"] = True
                    result["git_behind"] = True
        except Exception:
            pass

    return jsonify(result)


@app.route("/api/updater/apply", methods=["POST"])
def updater_apply():
    """Performs a fast, in-place update from GitHub without requiring a full re-install."""
    def _delayed_restart():
        import time
        time.sleep(0.35)
        try:
            # Never combine DETACHED_PROCESS with CREATE_NO_WINDOW on Windows (invalid flag combo).
            spawn_flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
            runtime_py = ROOT / "runtime" / "Scripts" / "python.exe"
            py_exe = str(runtime_py) if runtime_py.is_file() else sys.executable
            app_exe = ROOT / "Clipify AI.exe"
            target_args = [str(app_exe)] if app_exe.is_file() else [py_exe, str(ROOT / "app.py")]
            log_path = str(ROOT / "updater_restart.log")
            helper_code = (
                "import os, socket, subprocess, time\n"
                "time.sleep(0.3)\n"
                "for _ in range(75):\n"
                "    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:\n"
                "        s.settimeout(0.2)\n"
                "        if s.connect_ex(('127.0.0.1', 5000)) != 0:\n"
                "            break\n"
                "    time.sleep(0.2)\n"
                "time.sleep(0.3)\n"
                "env = os.environ.copy()\n"
                "env['CLIPPEDAI_NO_BROWSER'] = '1'\n"
                "try:\n"
                f"    with open({repr(log_path)}, 'ab') as lf:\n"
                f"        subprocess.Popen({repr(target_args)}, cwd={repr(str(ROOT))}, env=env, "
                "stdin=subprocess.DEVNULL, stdout=lf, stderr=lf, "
                f"close_fds=True, creationflags={spawn_flags})\n"
                "except Exception as exc:\n"
                f"    with open({repr(log_path)}, 'a', encoding='utf-8') as lf:\n"
                "        lf.write(f'Restart error: {exc}\\n')\n"
            )
            subprocess.Popen(
                [py_exe, "-c", helper_code],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=spawn_flags,
            )
        except Exception:
            pass
        finally:
            time.sleep(0.2)
            os._exit(0)

    # 1. Prioritize dedicated fast update release asset (update-v*.zip)
    update_url = None
    rel_data: dict[str, Any] = {}
    try:
        rel_req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "ClipifyAI-Updater", "Accept": "application/vnd.github.v3+json"}
        )
        with _urlopen_with_ssl_fallback(rel_req, timeout=8.0) as rel_resp:
            if rel_resp.status == 200:
                rel_data = json.loads(rel_resp.read().decode("utf-8", errors="replace"))
                for asset in rel_data.get("assets", []):
                    aname = asset.get("name", "").lower()
                    if "update" in aname and aname.endswith(".zip"):
                        update_url = asset.get("browser_download_url")
                        break
    except Exception:
        pass

    is_git = (ROOT / ".git").is_dir()
    git_bin = shutil.which("git") or shutil.which("git.exe") or "git"

    if is_git and not update_url:
        try:
            # Determine current branch
            branch_cmd = _run_hidden([git_bin, "branch", "--show-current"], cwd=str(ROOT), timeout=10, check=False)
            branch = (branch_cmd.stdout or "").strip() or "feature/cross-platform"

            # 1. Fetch latest changes
            _run_hidden([git_bin, "fetch", "origin", branch], cwd=str(ROOT), timeout=60, check=False)

            # 2. Fast-forward pull
            pull = _run_hidden([git_bin, "pull", "--ff-only", "origin", branch], cwd=str(ROOT), timeout=90, check=False)
            if pull.returncode != 0:
                # Fallback: stash unstaged scratch edits and pull
                _run_hidden([git_bin, "stash"], cwd=str(ROOT), timeout=15, check=False)
                pull = _run_hidden([git_bin, "pull", "origin", branch], cwd=str(ROOT), timeout=90, check=False)

            if pull.returncode == 0:
                threading.Thread(target=_delayed_restart, daemon=True).start()
                return jsonify({
                    "ok": True,
                    "method": "git",
                    "message": "Successfully updated to the latest GitHub code! Reloading in 3 seconds…",
                    "details": pull.stdout or "Updated to latest commit.",
                })
            else:
                return jsonify({
                    "ok": False,
                    "error": f"Git pull failed: {pull.stderr or pull.stdout or 'Unknown git error'}",
                }), 500
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    # Standalone or asset package update: download lightweight source archive from GitHub
    try:
        import tempfile
        import zipfile

        zip_url = update_url or f"https://github.com/{GITHUB_REPO}/archive/refs/heads/feature/cross-platform.zip"

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf_path = Path(tf.name)

        if not _download_file_resilient(zip_url, tf_path, timeout=120.0):
            raise RuntimeError(f"Could not download update package from {zip_url}")

        excluded_dirs = {
            "runtime", "input", "output", "jobs", "models", "settings",
            "installer", ".venv", "tools", "website", "build", "docs",
            "scratch", "tests", ".git", ".github",
        }
        updated_count = 0
        with zipfile.ZipFile(tf_path, "r") as zf:
            # Check if all members are nested under a single top-level directory (e.g. GitHub branch archive)
            # or if the zip contains top-level project files directly.
            all_non_dirs = [m.filename.replace("\\", "/").strip("/") for m in zf.infolist() if not m.is_dir()]
            first_dirs = [n.split("/")[0] for n in all_non_dirs if "/" in n]
            has_single_wrapper = (
                len(first_dirs) == len(all_non_dirs)
                and len(set(first_dirs)) == 1
                and all(not n.startswith(("app.py", "main.py", "static", "templates", "version.json")) for n in set(first_dirs))
            )

            for member in zf.infolist():
                if member.is_dir():
                    continue
                clean_name = member.filename.replace("\\", "/").strip("/")
                parts = clean_name.split("/")
                if has_single_wrapper:
                    parts = parts[1:]

                if not parts or not parts[0]:
                    continue
                if parts[0] in excluded_dirs:
                    continue

                dest_file = ROOT / Path(*parts)
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, open(dest_file, "wb") as target:
                    shutil.copyfileobj(source, target)
                updated_count += 1

        tf_path.unlink(missing_ok=True)
        threading.Thread(target=_delayed_restart, daemon=True).start()

        return jsonify({
            "ok": True,
            "method": "archive",
            "message": f"Successfully updated {updated_count} files in-place! Reloading in 3 seconds…",
            "files_updated": updated_count,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"In-place update failed: {exc}"}), 500


@app.get("/api/health")
def health():
    installed, error = _discover_ollama_models()
    return jsonify({
        "ok": True,
        "pid": os.getpid(),
        "version": APP_VERSION,
        "ollama": bool(installed),
        "models": installed,
        "model": _default_model(installed),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "error": error,
        "runtime": runtime_status(),
        "app_dir": str(ROOT),
        "user_data_dir": str(USER_DATA_DIR),
        "port": APP_PORT,
    })


@app.get("/api/system/gpus")
def api_system_gpus():
    """Retrieve all detected physical GPUs, current accelerator selection and status."""
    try:
        from clipify.platform.gpu_manager import get_gpu_status
        return jsonify(get_gpu_status())
    except Exception as ex:
        logger.warning("Error fetching GPU status: %s", ex)
        return jsonify({"ok": False, "error": str(ex), "gpus": []}), 500


@app.post("/api/system/gpus/select")
def api_system_gpus_select():
    """Select active accelerator GPU across PyTorch, CTranslate2, WhisperX, Ollama & FFmpeg."""
    try:
        data = request.get_json(silent=True) or {}
        gpu_id = data.get("gpu_id")
        if not gpu_id:
            return jsonify({"ok": False, "error": "Missing gpu_id parameter"}), 400
        from clipify.platform.gpu_manager import apply_gpu_selection, get_gpu_status
        selected = apply_gpu_selection(gpu_id)
        # Invalidate encoder cache so next render immediately adopts the chosen accelerator
        try:
            from clipify.platform.hardware import get_hardware_accelerator
            get_hardware_accelerator().detect_best_encoder(force_refresh=True)
        except Exception:
            pass
        status = get_gpu_status()
        status["selected"] = selected
        return jsonify(status)
    except Exception as ex:
        logger.exception("Error selecting GPU: %s", ex)
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.get("/api/diagnostic")
def diagnostic():
    """Full system diagnostic report.

    Returns a snapshot of every subsystem the application depends on so that
    support investigations can begin with concrete data rather than guessing.
    Call GET /api/diagnostic from a browser or curl to retrieve the report.
    """
    import datetime
    import platform as _platform

    report: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": _platform.platform(),
        "python_version": sys.version,
        "app_dir": str(ROOT),
        "user_data_dir": str(USER_DATA_DIR),
        "port": APP_PORT,
    }

    # ── Ollama ──────────────────────────────────────────────────────────────
    try:
        ollama_models, ollama_error = _discover_ollama_models()
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ollama_models_dir = os.getenv("OLLAMA_MODELS", "")

        # Try to find the ollama executable via common paths.
        _ollama_candidates = [
            os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
            os.path.join(os.getenv("ProgramFiles", ""), "Ollama", "ollama.exe"),
            os.path.join(os.getenv("ProgramFiles(x86)", ""), "Ollama", "ollama.exe"),
        ]
        ollama_exe = next((p for p in _ollama_candidates if os.path.isfile(p)), "")
        if not ollama_exe:
            import shutil
            ollama_exe = shutil.which("ollama") or ""

        # Try ollama --version
        ollama_version = ""
        if ollama_exe:
            try:
                import subprocess
                _vr = subprocess.run(
                    [ollama_exe, "--version"],
                    capture_output=True, text=True, timeout=8, check=False
                )
                ollama_version = (_vr.stdout or _vr.stderr or "").strip().splitlines()[0] if _vr.returncode == 0 else ""
            except Exception:
                pass

        report["ollama"] = {
            "ok": bool(ollama_models) and not ollama_error,
            "exe": ollama_exe,
            "version": ollama_version,
            "api_url": ollama_url,
            "models_dir_env": ollama_models_dir,
            "models": ollama_models,
            "model_count": len(ollama_models),
            "error": ollama_error,
        }
    except Exception as exc:
        report["ollama"] = {"ok": False, "error": str(exc)}

    # ── FFmpeg ───────────────────────────────────────────────────────────────
    try:
        ffmpeg_version = ""
        ffmpeg_ok = False
        try:
            ffmpeg_path = _ffmpeg_path()
        except Exception:
            ffmpeg_path = ""
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            try:
                import subprocess
                _fr = subprocess.run(
                    [ffmpeg_path, "-version"],
                    capture_output=True, text=True, timeout=10, check=False
                )
                if _fr.returncode == 0:
                    ffmpeg_ok = True
                    ffmpeg_version = (_fr.stdout or "").splitlines()[0] if _fr.stdout else ""
            except Exception as fe:
                ffmpeg_version = str(fe)
        report["ffmpeg"] = {
            "path": ffmpeg_path,
            "exists": bool(ffmpeg_path and os.path.isfile(ffmpeg_path)),
            "ok": ffmpeg_ok,
            "version": ffmpeg_version,
        }
    except Exception as exc:
        report["ffmpeg"] = {"ok": False, "error": str(exc)}

    # ── GPU / CUDA ────────────────────────────────────────────────────────────
    try:
        cuda_available = False
        vram_total_gb = 0.0
        vram_free_gb = 0.0
        gpu_name = ""
        cuda_version = ""
        torch_version = ""
        try:
            import torch
            torch_version = torch.__version__
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                props = torch.cuda.get_device_properties(0)
                vram_total_gb = round(props.total_memory / 1e9, 2)
                vram_free_gb = round(
                    (props.total_memory - torch.cuda.memory_allocated(0)) / 1e9, 2
                )
                gpu_name = props.name
                cuda_version = getattr(getattr(torch, "version", None), "cuda", "") or ""
        except Exception as te:
            gpu_name = str(te)
        if not cuda_available:
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    cuda_available = True
                    cuda_version = "12.x (CTranslate2/Faster-Whisper)"
                    try:
                        import pynvml
                        pynvml.nvmlInit()
                        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                        gpu_name = pynvml.nvmlDeviceGetName(handle)
                        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        vram_total_gb = round(mem.total / 1e9, 2)
                        vram_free_gb = round(mem.free / 1e9, 2)
                    except Exception:
                        gpu_name = "NVIDIA CUDA GPU"
            except Exception:
                pass
        report["gpu"] = {
            "cuda_available": cuda_available,
            "cuda_version": cuda_version,
            "torch_version": torch_version,
            "gpu_name": gpu_name,
            "vram_total_gb": vram_total_gb,
            "vram_free_gb": vram_free_gb,
        }
    except Exception as exc:
        report["gpu"] = {"cuda_available": False, "error": str(exc)}

    # ── Runtime ───────────────────────────────────────────────────────────────
    try:
        report["runtime"] = runtime_status()
    except Exception as exc:
        report["runtime"] = {"error": str(exc)}

    # ── Active jobs ───────────────────────────────────────────────────────────
    report["active_jobs"] = len(jobs)

    return jsonify(report)


def _find_app_browser() -> str:
    """Locate a Chromium-based browser that can host a chromeless app window.

    Returns an empty string when none is found, so the caller can fall back to
    the default browser.
    """
    import glob
    import os as _os

    candidates: list[str] = []
    # Check Google Chrome first: reliable chromeless --app window without profile lock clashes
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = _os.environ.get(var)
        if not base:
            continue
        candidates.extend(
            glob.glob(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        )
    # Edge as secondary option
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = _os.environ.get(var)
        if not base:
            continue
        candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for candidate in candidates:
        if candidate and _os.path.isfile(candidate):
            return candidate
    return ""


def _window_icon() -> str:
    """Locate the application icon, for the launcher shortcut."""
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    for candidate in (
        _os.path.join(ROOT, "icon.ico"),                                       # installed
        _os.path.join(_here, "build", "installer_app", "resources", "payload", "icon.ico"),
        _os.path.join(_here, "build", "installer_app", "build", "icon.ico"),
        _os.path.join(_here, "icon.ico"),
    ):
        if _os.path.isfile(candidate):
            return candidate
    return ""


def _app_window_shortcut(browser: str, url: str, profile: str, extra: str = "") -> str:
    """Create the launcher shortcut that gives the app window its own icon."""
    import os as _os
    import subprocess

    try:
        programs = _os.path.join(
            _os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"
        )
        _os.makedirs(programs, exist_ok=True)
        link = _os.path.join(programs, "Clipify AI App Window.lnk")
    except OSError:
        return ""

    icon = _window_icon()
    args = (
        f'--app="{url}" --app-id=ClipifyAI.AppWindow '
        f'--user-data-dir="{profile}" --window-size=1440,900 '
        "--no-default-browser-check --no-first-run "
        "--disable-features=Translate,EdgeShoppingAssistant"
    )
    if extra:
        args = f"{extra} {args}"

    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut('{link}'); "
        f"$l.TargetPath = '{browser}'; "
        f"$l.Arguments = '{args}'; "
        f"$l.WorkingDirectory = '{ROOT}'; "
        "$l.Description = 'Clipify AI'; "
        + (f"$l.IconLocation = '{icon},0'; " if icon else "")
        + "$l.Save()"
    )
    try:
        _run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return link if _os.path.isfile(link) else ""


def _open_app_window(host: str, port: int, timeout: float = 40.0) -> None:
    """Open the app in its own window once the server is actually up."""
    import subprocess
    import threading
    import time

    connect_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{connect_host}:{port}/"

    def wait_then_open() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.5) as response:
                    if response.status < 500:
                        break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.4)

        profile = None
        try:
            from clippedai_runtime import data_dir
            profile = str(data_dir("settings", "app-window-profile"))
            os.makedirs(profile, exist_ok=True)
        except Exception:
            profile = None

        browser = _find_app_browser()
        with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
            _lf.write(f"[{datetime.now()}] _open_app_window browser={browser}\n")
        opened = False
        if browser:
            args = [
                browser,
                f"--app={url}",
                "--window-size=1440,900",
                "--no-default-browser-check",
                "--no-first-run",
            ]
            is_edge = "edge" in os.path.basename(browser).lower()
            if profile and not is_edge:
                args.append(f"--user-data-dir={profile}")
            try:
                proc = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.6)
                poll_code = proc.poll()
                opened = (poll_code is None or poll_code == 0)
                with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{datetime.now()}] _open_app_window Popen poll={poll_code} opened={opened}\n")
                # If this browser instance owns the app window (poll_code is None), shut down Clipify & child processes when closed
                if poll_code is None:
                    try:
                        proc.wait()
                    except Exception:
                        pass
                    _cleanup_all_child_processes()
                    os._exit(0)
            except Exception as _e:
                opened = False
                with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{datetime.now()}] _open_app_window Popen failed: {_e}\n")

        if not opened:
            try:
                import webbrowser
                webbrowser.open(url)
                with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{datetime.now()}] _open_app_window webbrowser.open fallback used\n")
            except Exception as _we:
                with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{datetime.now()}] _open_app_window webbrowser.open failed: {_we}\n")

    threading.Thread(target=wait_then_open, name="clipify-open-window", daemon=True).start()


# ==============================================================================
# CLIPPY AI - SMART IN-APP CHAT ASSISTANT
# ==============================================================================

def _get_fastest_ollama_model() -> tuple[str, str | None]:
    """Finds all available Ollama models and selects the fastest model (smallest parameter size)."""
    models, err = _discover_ollama_models()
    if not models:
        return "", err or "No Ollama models detected"

    def _model_speed_rank(model_name: str) -> float:
        low = model_name.lower()
        if "0.5b" in low:
            return 0.5
        if "1b" in low or "1.5b" in low:
            return 1.0
        if "2b" in low or "3b" in low:
            return 3.0
        match = re.search(r"(\d+(?:\.\d+)?)\s*b", low)
        if match:
            try:
                return float(match.group(1))
            except Exception:
                pass
        if "tiny" in low or "mini" in low or "small" in low:
            return 2.0
        if "7b" in low or "8b" in low:
            return 8.0
        if "14b" in low:
            return 14.0
        if "32b" in low:
            return 32.0
        if "70b" in low:
            return 70.0
        return 7.0

    sorted_models = sorted(models, key=_model_speed_rank)
    return sorted_models[0], None


_CLIPPY_SYSTEM_PROMPT = f"""You are the official in-app AI assistant for Clipify AI (Version {APP_VERSION}).
You talk naturally, concisely, warmly, and helpfully like a creative video editing expert.
Never dump overwhelming bulleted lists for simple greetings (like "hi", "hello") or casual comments. Reply normally and ask what they'd like to create!

Key In-App Features & Knowledge ({APP_VERSION}):
1. Instant Clipping ([NAVIGATE:instant] or #instant):
   - Ultra-fast isolated pipeline that cuts high-impact 9:16 vertical shorts in seconds.
   - Completely skips heavy LLM transcription and multi-stage candidate scoring for instant results.
   - Accepts YouTube links or local video files (drag-and-drop or file picker).
   - Framing Layouts: 9:16 Center Crop, Blur-Fill 9:16, Split Screen (Top/Bottom), and Gaming Split (Facecam / Gameplay).
   - Target Durations: 15s Hook, 30s Viral Short, 60s Full Highlight.
   - Segment Selection: Auto Golden Hook (peaks excitement), Video Start (0:00), or Custom Timestamp.
   - Dynamic Kinetic Subtitle Captions: optional animated word captions overlay.
   - Multi-Clip Count: choose how many clips to generate at once.
   - Fresh URL Ingestion: pasting a new YouTube URL or dropping a new file immediately resets and starts a clean, isolated job (never re-uses previous footage).
   - "⚡ Generate Another Clip": when a clip is done, users can click "Generate Another Clip" to cut a completely different, non-overlapping hook from the video without re-downloading or re-processing!

2. GPU Acceleration & Hardware Performance:
   - Built-in hardware acceleration for NVIDIA GPUs (RTX / GTX with CUDA 12).
   - Whisper transcription uses GPU (CTranslate2 float16) automatically when available, falling back to CPU (int8) only if no GPU is present. This completely eliminates CPU transcription delays!
   - Video rendering utilizes hardware NVENC, AMF, or Intel QSV encoders with graceful fallback to libx264.

3. Live Studio ([NAVIGATE:live] or /live):
   - Real-time OBS RTMP live stream clipping.
   - Stream directly to rtmp://localhost:1935/live from OBS Studio.
   - Automatic live excitement scoring and instant vertical highlight generation while broadcasting.

4. Narration Studio ([NAVIGATE:narrate] or /narrate):
   - Create faceless AI voiceover videos.
   - Pairs neural voice models (like Kokoro TTS) with satisfying gameplay and aesthetic background loops.

5. Beta Lab & Caption Playground ([NAVIGATE:beta] or #beta):
   - YouTube / Twitch / Kick platform selector when importing from link.
   - 7 caption design presets, interactive mouse drag/resize Caption Playground, 18 audio languages, Disable Captions toggle, and custom draggable timed text overlays.

6. Create Shorts & Reuse Existing Subtitles ([NAVIGATE:create] or #create):
   - Full AI highlight generation engine with WhisperX transcription, multi-speaker diarization, smart podcast split, face tracking, and automatic AI viral title + description + hashtag generation.
   - Reuse Existing Subtitles Toggle: Automatically detects and reuses .srt, .vtt, .ass, .json, or embedded video subtitle tracks (ffprobe) to skip WhisperX transcription and save time!

7. Storage Manager ([NAVIGATE:storage] or #storage):
   - Dedicated Storage section in the sidebar to view disk usage and customize folder paths for Workspace & Output, Ollama Models (OLLAMA_MODELS), and AI Caches & Models (HF_HOME, WhisperX, Narrate thumbnails), plus Move Current Data.

8. Trending Streams & Gameplay ([NAVIGATE:trending] or #trending):
   - Discover live broadcasts and trending gameplay across YouTube, Twitch, and Kick with hover-to-play previews and 1-click Clip This / Clip This Stream.

7. Editor & Projects ([NAVIGATE:editor] or #editor):
   - Interactive timeline, trim adjustments, watermark & logo branding, and social publishing.

8. Models & Engine Hub ([NAVIGATE:models]):
   - Local AI models manager for Ollama and local Whisper.
   - Recommends lightweight ultra-fast models like qwen2.5:3b or qwen2.5:1.5b.

9. Promoters Spotlight ([NAVIGATE:promoters]):
   - Creator spotlight modal celebrating top promoters, viral creators, and community supporters.

10. Update Manager ([NAVIGATE:update]):
   - 1-click in-place updater directly from GitHub releases to Clipify AI v5.0.1.

11. Forest Runner Mascot & Mini-Game:
   - Interactive creature mascot card on the sidebar ("need help?") triggering the Instagram community link or the playable retro Forest Runner game.

12. Support, Discord & Community ([NAVIGATE:support]):
   - Official Discord Server:
     👉 [**Join Official Clipify AI Discord Server**](https://discord.gg/5ZBsasgryX)
   - Official Instagram Creator Community group chat:
     👉 [**Join Official Instagram Creator Community**](https://ig.me/j/AQj1lYCWh_iV_S7J/)
   - Creator contact: `@sherlock.fy`.
   - Star on GitHub.

13. Clipper Campaigns & Bounties ([NAVIGATE:campaigns]):
   - Built-in directory of the top 10 platforms for streamer & podcast clippers to earn bounties and monetize viral clips.
   - Top Platforms Ranked:
     1. **Content Rewards**: Top overall pick for podcasts, YouTubers, streamers, and gaming. Available in India + International.
     2. **Vyro**: Huge creator ecosystem (MrBeast ecosystem, shows, podcasts). Worldwide / India supported.
     3. **Clipster**: Streamers, music, gaming, and influencers. Worldwide without country blocks.
     4. **Clipping.net**: Influencer & creator podcasts.
     5. **Vues**: Brands, creators, and social media campaigns.
     6. **Clip**: Streamers, sports, film, TV, music.
     7. **Wondeed**: Creator and influencer clipping (International payouts).
     8. **ClipAffiliates**: Creator affiliate clipping.
     9. **ClipGrow**: India-focused clipping campaigns.
     10. **ClipConnect India**: India-dedicated social-media and podcast campaigns.
   - For users asking "which is the best campaign" or asking how to monetize, recommend **Content Rewards** and **Vyro** as the top choices, explain that Content Rewards pays per view milestones, and direct them to `#campaigns` by using `[NAVIGATE:campaigns]`.

Navigation Action Tags:
When recommending or directing a user to a specific feature, always include the matching navigation tag on its own line:
- [NAVIGATE:storage] -> For Storage Manager, changing output/Ollama folders, moving data
- [NAVIGATE:campaigns] -> For Clipper Campaigns & Bounties Directory
- [NAVIGATE:trending] -> For Trending Streams & Gameplay (YouTube, Twitch, Kick)
- [NAVIGATE:instant] -> For Instant Clipping, fast 9:16 shorts, split screen, generate another clip
- [NAVIGATE:live] -> For Live Studio, OBS, RTMP stream clipping
- [NAVIGATE:narrate] -> For Narration Studio, AI voiceovers, Kokoro
- [NAVIGATE:beta] -> For Beta Lab, YouTube/Twitch/Kick link selector, caption playground, draggable text
- [NAVIGATE:create] -> For Create Shorts, YouTube import, reuse existing subtitles toggle, full AI highlight detection
- [NAVIGATE:editor] -> For Editor, video trimming, watermarks, branding
- [NAVIGATE:projects] -> For Projects library
- [NAVIGATE:models] -> For Models & Engine Hub, Ollama, Whisper
- [NAVIGATE:update] -> For Update Manager, checking updates
- [NAVIGATE:promoters] -> For Promoters Spotlight
- [NAVIGATE:support] -> For Support Us, GitHub star, Instagram
"""


def _clippy_builtin_fallback(user_query: str) -> str:
    """Provides natural, human-like responses when Ollama is offline or uninstalled."""
    q = user_query.lower().strip()

    # Trending Streams & Gameplay
    if any(k in q for k in ("trend", "twitch", "kick", "stream", "live stream", "broadcast", "gameplay", "clip this")):
        return (
            "[NAVIGATE:trending]\n"
            "I've opened the **Trending Streams & Gameplay Cockpit** for you! 🔴\n\n"
            "Here you can discover and clip content across 3 major platforms:\n"
            "- 📺 **YouTube**: Live broadcasts with viewer counts + trending gameplay videos with high viral CTR.\n"
            "- 🟣 **Twitch**: Live streams with streamer name, viewer counts, and game categories.\n"
            "- 🟢 **Kick**: Featured and trending creator livestreams.\n\n"
            "**One-Click Clipping:**\n"
            "- Click **⚡ Clip This** on any regular video to import it into Create Studio.\n"
            "- Click **🔴 Clip This Stream** on any live broadcast to open Live Studio with the stream pre-connected and ready to clip!"
        )

    # Disable Captions Toggle & Language Selection
    if any(k in q for k in ("disable caption", "toggle caption", "turn off caption", "no caption", "caption toggle", "language", "hindi", "spanish", "audio language", "transcribe language", "auto-detect")):
        return (
            "[NAVIGATE:beta]\n"
            "I've opened **Beta Features** where you can configure Captions & Languages! 🌐\n\n"
            "- 🔘 **Disable Captions (Toggle)**: Turn OFF the **Subtitle Captions** switch to export clean vertical shorts without burned-in text.\n"
            "- 🗣️ **Language Selection**: Choose from 18 audio languages (English, Hindi हिन्दी, Spanish, French, German, Japanese, Korean, Chinese, Arabic, and Auto-Detect) for precise transcription.\n\n"
            "Both controls are active right now inside the **Beta Features** tab on the left menu!"
        )

    # Caption Designs & Interactive Mouse Playground
    if any(k in q for k in ("caption design", "caption style", "caption playground", "yellow caption", "lime green", "tiktok cyan", "caption preset", "resize caption", "drag caption", "caption size", "caption position", "hormozi")):
        return (
            "[NAVIGATE:beta]\n"
            "I've opened the **Caption Designs & Mouse Playground** in Beta Features! 🎨\n\n"
            "**Features you can try:**\n"
            "- 🌈 **7 High-Impact Caption Presets**: Viral Yellow Punch, Cyber Lime Green, Hormozi Bold White, TikTok Cyan Pop, Crimson Fire, Typewriter Retro, and Neon Lavender.\n"
            "- 🖱️ **Interactive Mouse Dragging**: Click and drag the subtitle box anywhere on the 9:16 phone stage with automatic alignment snapping (Top Safe 25%, Center Seam 50%, Lower Safe 75%).\n"
            "- 🎛️ **Mouse Resizing**: Resize text easily using the corner drag handle (`⤡`), mouse wheel scrolling, or the size slider (`24px` to `76px`).\n"
            "- 📐 **1:1 Video Sync**: The position and font size you set here are passed directly to the video export pipeline!"
        )

    # Instant Clipping & Variations
    if any(k in q for k in (
        "instant", "quick clip", "fast clip", "fast mode", "instant clipping", 
        "split screen", "gaming split", "blur-fill", "blur fill", "center crop",
        "generate another", "another clip", "different clip", "new clip", "diverse"
    )):
        return (
            "[NAVIGATE:instant]\n"
            "I've opened **Instant Clipping** for you! ⚡\n\n"
            "Instant Clipping creates high-impact 9:16 vertical shorts in seconds by skipping heavy LLM transcription:\n"
            "- 📥 **Source**: Paste any YouTube link or drag-and-drop a local video file (fresh links immediately start a clean isolated job).\n"
            "- 📐 **Framing Presets**: Choose between **9:16 Center Crop**, **Blur-Fill 9:16**, **Split Screen (Top/Bottom)**, or **Gaming Split (Facecam / Gameplay)**.\n"
            "- ⏱️ **Target Duration**: 15s Hook, 30s Viral Short, or 60s Full Highlight.\n"
            "- 💬 **Kinetic Captions**: Toggle dynamic animated word subtitle overlays.\n"
            "- 🔢 **Multi-Clips**: Select how many clips to generate at once.\n"
            "- ⚡ **Generate Another Clip**: Once your clip is ready, click *Generate Another Clip* to automatically cut a completely different, non-overlapping hook from the video without re-downloading!\n\n"
            "Give it a try in the Instant Clipping panel!"
        )

    # GPU Acceleration, CUDA, Hardware delays
    if any(k in q for k in ("gpu", "cuda", "nvidia", "hardware", "cpu", "delay", "slow", "speed up", "transcribe", "nvenc")):
        return (
            "🚀 **GPU Acceleration & Performance in Clipify AI v5.0.2**:\n\n"
            "- **Automatic NVIDIA CUDA Detection**: Clipify AI automatically detects your NVIDIA GPU (RTX / GTX with CUDA 12). "
            "When detected, Whisper speech-to-text transcribes at lightning speed using CTranslate2 `float16`.\n"
            "- **Zero CPU Bottlenecks**: The CPU is only used as a fallback if no compatible GPU is installed, preventing transcription freezes and system lag.\n"
            "- **Hardware Video Encoding**: Exports leverage hardware acceleration (NVIDIA NVENC, AMD AMF, or Intel QSV) for ultra-fast rendering with automatic fallback to CPU libx264.\n\n"
            "Everything is configured automatically out of the box—no manual driver setup required!"
        )

    # Promoters Spotlight
    if any(k in q for k in ("promoter", "spotlight", "supporter", "contributor")):
        return (
            "[NAVIGATE:promoters]\n"
            "I've opened the **Promoters Spotlight** for you! 🌟\n\n"
            "This showcases our top community promoters, viral creators, and supporters who help Clipify AI grow. "
            "Check out their channels and see how you can get featured in our creator spotlight!"
        )

    # Clipper Campaigns & Bounties
    if any(k in q for k in ("campaign", "bount", "monetiz", "earn", "platform", "vyro", "content reward", "clipster", "payout", "paid", "make money", "best campaign")):
        return (
            "[NAVIGATE:campaigns]\n"
            "I've opened the **Clipper Campaigns & Bounties Directory** for you! 💰\n\n"
            "Here are the best platforms for streamer & podcast clippers to earn bounties:\n"
            "- 🏆 **Content Rewards** (#1 Pick): Active clipping campaigns for podcasts, top YouTubers, and gaming. Fully open to **India + International** clippers!\n"
            "- 🥈 **Vyro** (#2 Pick): Major creator network (including MrBeast ecosystem & top podcasts). High payouts and global reach.\n"
            "- 🥉 **Clipster** (#3 Pick): Streamers, music, and esports clipping with worldwide access and no country blocks.\n"
            "- 🇮🇳 **ClipGrow & ClipConnect India**: Great dedicated platforms for India-focused creator campaigns.\n\n"
            "You can click on any platform in the **Campaigns** tab on the left menu to visit their official website and apply!"
        )

    # Conversational follow-ups and queries
    if q in ("huh", "what", "what?", "huh?", "idk", "why", "help me", "confused", "pardon", "?"):
        return (
            "No worries! I'm here to help. You can tell me what you'd like to do:\n"
            "- ⚡ **Create fast 9:16 vertical clips** from YouTube links or local videos (`#instant`)\n"
            "- 💰 **Find clipper bounties & campaigns** to earn from your clips (`#campaigns`)\n"
            "- 🔴 **Explore Trending live streams** on YouTube, Twitch & Kick (`#trending`)\n"
            "- 🎨 **Try Caption Designs & Position Playground** (`#beta`)\n"
            "- 🎙️ **Generate voiceover stories** with gameplay backgrounds (`#narrate`)\n"
            "- 🔴 **Clip live streams** from OBS in real-time (`#live`)\n\n"
            "What kind of clip are you looking to create?"
        )

    # Models & Engine Hub
    if any(k in q for k in ("model", "models", "engine", "ollama", "whisper", "qwen", "llama")):
        return (
            "[NAVIGATE:models]\n"
            "I've opened the **Models & Engine Hub** for you! 🤖\n\n"
            "Here you can manage local AI engines and check Whisper transcription status:\n"
            "- **Fastest Recommendation**: For instant chat and analysis, we recommend `qwen2.5:3b` or `qwen2.5:1.5b` via Ollama.\n"
            "- **Install**: Run `ollama pull qwen2.5:3b` in your terminal to enable intelligent local chatting."
        )

    # Community, Discord & Instagram Support
    if any(k in q for k in ("discord", "server", "instagram", "insta", "group", "community", "help", "support", "contact", "chat link", "need help", "star", "github")):
        return (
            "[NAVIGATE:support]\n"
            "Join the official **Clipify AI Community** on Discord & Instagram! 💬\n\n"
            "- 🎮 **Discord Server**: [**Join Clipify AI Discord**](https://discord.gg/5ZBsasgryX) (live help, updates, presets & feedback)\n"
            "- 📸 **Instagram Group Chat**: [**Join Instagram Creator Community**](https://ig.me/j/AQj1lYCWh_iV_S7J/)\n\n"
            "You can also reach the creator on Instagram `@sherlock.fy` or star the repo on GitHub!"
        )

    # Forest Runner Mascot & Mini-Game
    if any(k in q for k in ("forest", "mascot", "game", "runner", "creature", "monkey")):
        return (
            "🌲 **Forest Runner Mascot & Mini-Game**:\n\n"
            "See the cute little creature in the bushes at the bottom of the left sidebar? "
            "Clicking on it lets you jump into our retro **Forest Runner** mini-game while waiting for exports, "
            "or connects you directly with the community on Instagram!"
        )

    # Storage Manager
    if any(k in q for k in ("storage", "folder", "move data", "change path", "output path", "ollama path", "disk location")):
        return (
            "[NAVIGATE:storage]\n"
            "I've opened **Storage Manager** for you! 💾\n\n"
            "Here you can view live disk usage and change the folder locations for:\n"
            "- 📁 **Workspace & Output**: Imported videos, transcription caches, and rendered Shorts.\n"
            "- 🤖 **Ollama Models**: Your local LLM weights (`OLLAMA_MODELS`).\n"
            "- 🧠 **AI Caches & Models**: WhisperX, Hugging Face (`HF_HOME`), and Narrate thumbnails.\n\n"
            "You can pick a new folder and click **Move Current Data** to migrate your existing files safely!"
        )

    # Reuse Existing Subtitles / Transcription
    if any(k in q for k in ("existing transcript", "existing subtitle", "reuse subtitle", "reuse transcript", ".srt", ".vtt", "skip transcri")):
        return (
            "[NAVIGATE:create]\n"
            "I've opened **Create Shorts** for you! 📝\n\n"
            "Turn on the **Reuse Existing Subtitles / Transcription** toggle to automatically use matching `.srt`, `.vtt`, `.ass`, `.json`, or embedded video subtitle tracks (`ffprobe`) — skipping heavy WhisperX transcription and saving a ton of time!"
        )

    # Updates and Version Info
    if any(k in q for k in ("update", "version", "what's new", "whats new", "latest", "upgrade", "changelog", "patch", "v5")):
        return (
            "[NAVIGATE:update]\n"
            f"You are currently running **Clipify AI {APP_VERSION}**! 🚀\n\n"
            f"**What's new in {APP_VERSION}:**\n"
            "- 💾 **Storage Manager (`#storage`)**: Change paths & move existing data for Output, Ollama Models, and AI Caches.\n"
            "- 📝 **Existing Subtitles Reuse**: Toggle in Create Shorts to reuse `.srt`/`.vtt`/embedded subtitles and skip transcription.\n"
            "- ⚡ **Instant & Main AI Titles + Descriptions**: Automatic viral titles, descriptions, hashtags & tags powered by your installed Ollama model (`qwen3:4b`, etc.).\n"
            "- 🎮 **Beta Platform Selector**: Pick **YouTube**, **Twitch**, or **Kick** when importing links in Beta Lab, plus 7 caption styles and mouse Caption Playground.\n"
            "- 🚀 **Top-Header GPU Cockpit**: Instant switching across NVIDIA CUDA, Intel QSV, and CPU with cached detection.\n"
            "- 🔔 **Highlighted Update Button & 1-Click Updater**: Automatic update highlight when a new release is available on GitHub.\n"
            "- 📱 **Android Companion v5.0.7**: 4K/8K high-quality split-screen rendering.\n\n"
            "Click **Update** in the left sidebar anytime to install the latest release in one click!"
        )

    # Casual greetings
    if q in ("hi", "hello", "hey", "yo", "sup", "howdy", "good morning", "good evening") or q.startswith(("hi ", "hello ", "hey ")):
        return "Hey there! 👋 I'm your Clipify AI assistant. How can I help you create today? You can try Instant 9:16 Clipping, Live Studio, voiceovers, or standard AI shorts!"

    if "bored" in q:
        return "Let's make something viral! You can generate quick 9:16 shorts with **Instant Clipping**, play the **Forest Runner** mini-game from the sidebar mascot, or create an AI story in **Narration Studio**. What would you like to do?"

    if any(k in q for k in ("live", "obs", "rtmp", "stream")):
        return (
            "[NAVIGATE:live]\n"
            "I've opened the Live Studio page for you!\n\n"
            "To clip your live stream, just set OBS to stream to `rtmp://localhost:1935/live`. "
            "Clipify AI will automatically monitor audio excitement and create instant clips while you broadcast.\n\n"
            "If you'd like a step-by-step walkthrough, just click on **App Guide** from the left menu!"
        )

    if any(k in q for k in ("text", "beta", "draggable", "drag", "timing", "overlay")):
        return (
            "[NAVIGATE:beta]\n"
            "I've opened Beta Lab for you!\n\n"
            "Here you can add draggable text onto your shorts, drag it anywhere on the video player, "
            "and use the playhead buttons to set exact start and end times before burning it in.\n\n"
            "For a quick guided tour, click **App Guide** on the left menu!"
        )

    if any(k in q for k in ("narrat", "voice", "tts", "kokoro", "script")):
        return (
            "[NAVIGATE:narrate]\n"
            "I've opened Narration Studio for you!\n\n"
            "You can type or generate a script, choose a neural voice (like Kokoro), "
            "and pair it with satisfying gameplay backgrounds.\n\n"
            "Feel free to click **App Guide** on the left sidebar for an interactive tour!"
        )

    if any(k in q for k in ("create", "import", "short", "youtube", "link", "url", "make clip")):
        return (
            "[NAVIGATE:create]\n"
            "I've opened the Create section for you!\n\n"
            "Just paste any YouTube link or select a local video file, choose your preferred duration and framing, "
            "and click Start Clipping.\n\n"
            "Tip: If you want ultra-fast 9:16 clips without heavy transcription, check out **Instant Clipping**!"
        )

    if any(k in q for k in ("edit", "editor", "project", "review", "brand", "logo", "watermark")):
        return (
            "[NAVIGATE:editor]\n"
            "I've switched to the Editor for you!\n\n"
            "Here you can preview your finished Shorts, adjust framing, add custom logos and watermarks, "
            "and publish directly to YouTube Shorts, TikTok, or Instagram.\n\n"
            "Click **App Guide** on the left menu if you'd like an interactive walkthrough!"
        )

    if any(k in q for k in ("cache", "clean", "disk", "space", "delete", "temp", "storage")):
        return (
            "To free up disk space safely, click **Clear Cache** in the left sidebar navigation. "
            "Clipify AI will clean up temporary audio extractions and working cache while preserving all your saved Shorts and projects!"
        )

    if any(k in q for k in ("thank", "thanks", "awesome", "great", "cool")):
        return "You're very welcome! Let me know if you need any other help creating your clips."

    return (
        f"I'm here to help you get the most out of Clipify AI {APP_VERSION}! 🚀\n\n"
        "Here are a few quick things I can help you with:\n"
        "- 💾 **Storage Manager**: Change Output, Ollama & AI Cache folders (`#storage`)\n"
        "- 📝 **Reuse Existing Subtitles**: Skip transcription when subtitles exist (`#create`)\n"
        "- 🔴 **Trending Streams**: Discover & clip YouTube, Twitch & Kick streams (`#trending`)\n"
        "- 🎨 **Caption Studio & Platform Import**: 7 styles, mouse playground & YT/Twitch/Kick (`#beta`)\n"
        "- 💰 **Campaigns & Bounties**: Find platforms paying clippers per view (`#campaigns`)\n"
        "- ⚡ **Instant Clipping**: Fast 9:16 vertical shorts with AI titles & descriptions (`#instant`)\n\n"
        "Just ask me what you'd like to do!"
    )


@app.get("/api/clippy/model")
def clippy_model_info():
    """Returns the fastest Ollama model detected or fallback information."""
    fastest_model, err = _get_fastest_ollama_model()
    if fastest_model:
        return jsonify({
            "ok": True,
            "model": fastest_model,
            "provider": "ollama",
            "speed": "Fastest Local AI",
        })
    return jsonify({
        "ok": True,
        "model": "Clipify Intelligence",
        "provider": "builtin",
        "speed": "Instant Fallback",
        "note": err or "Ollama offline; using comprehensive knowledge engine.",
    })


@app.post("/api/clippy/chat")
def clippy_chat():
    """Interactive chat with Clippy AI using the fastest available local Ollama model."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not message:
        return jsonify({"ok": False, "error": "No message provided"}), 400

    fastest_model, err = _get_fastest_ollama_model()

    # Attempt query to local Ollama if model available
    if fastest_model:
        try:
            # Build messages list
            messages = [{"role": "system", "content": _CLIPPY_SYSTEM_PROMPT}]
            # Include last 4 history turns for context
            for h in history[-4:]:
                if isinstance(h, dict) and "role" in h and "content" in h:
                    messages.append({"role": h["role"], "content": str(h["content"])[:500]})
            messages.append({"role": "user", "content": message[:1000]})

            ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
            base = ollama_url.rstrip("/")
            chat_req = urllib.request.Request(
                f"{base}/api/chat",
                data=json.dumps({
                    "model": fastest_model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.4, "num_predict": 1024}
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(chat_req, timeout=35.0) as resp:
                if resp.status == 200:
                    chat_res = json.loads(resp.read().decode("utf-8", errors="replace"))
                    msg = (chat_res.get("message", {}).get("content") or "").strip()
                    if msg:
                        import re
                        if '</think>' in msg:
                            msg = msg.split('</think>', 1)[1].strip()
                        cleaned = re.sub(r'(?i)<think>.*?</think>', '', msg, flags=re.DOTALL).strip()
                        # Clean any leftover internal monologue / chain-of-thought preamble
                        while cleaned and (cleaned.lower().startswith("okay,") or cleaned.lower().startswith("thinking") or cleaned.lower().startswith("hmm,") or cleaned.lower().startswith("let me ")):
                            parts = cleaned.split("\n\n", 1)
                            if len(parts) > 1 and len(parts[1].strip()) > 15:
                                cleaned = parts[1].strip()
                            else:
                                break
                        if cleaned:
                            msg = cleaned
                    if not msg:
                        # If model only populated internal reasoning and exhausted tokens, use high-accuracy knowledge fallback
                        msg = _clippy_builtin_fallback(message)
                    if msg:
                        low_m = message.lower()
                        if any(k in low_m for k in ("campaign", "bount", "monetiz", "earn", "vyro", "content reward")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:campaigns]\n{msg}\n\n*Tip: Check the **Campaigns** tab on the left menu to view all 10 platforms!*"
                        elif any(k in low_m for k in ("instant", "fast clip", "quick clip", "instant clipping", "generate another")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:instant]\n{msg}\n\n*Tip: Click **App Guide** on the left menu for a step-by-step walkthrough!*"
                        elif any(k in low_m for k in ("live", "obs", "rtmp", "stream")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:live]\n{msg}\n\n*Tip: Click **App Guide** on the left menu for a step-by-step walkthrough!*"
                        elif any(k in low_m for k in ("beta", "text overlay", "draggable text", "overlay")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:beta]\n{msg}\n\n*Tip: Click **App Guide** on the left menu for a step-by-step walkthrough!*"
                        elif any(k in low_m for k in ("narrat", "voiceover", "kokoro")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:narrate]\n{msg}\n\n*Tip: Click **App Guide** on the left menu for a step-by-step walkthrough!*"
                        elif any(k in low_m for k in ("promoter", "spotlight")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:promoters]\n{msg}"
                        elif any(k in low_m for k in ("model", "engine hub")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:models]\n{msg}"
                        elif any(k in low_m for k in ("update", "upgrade", "new version", "changelog")) and "[NAVIGATE:" not in msg:
                            msg = f"[NAVIGATE:update]\n{msg}"
                        elif any(k in low_m for k in ("support us", "support group", "get support", "instagram", "community", "donate", "patreon")):
                            if "[NAVIGATE:" not in msg:
                                msg = f"[NAVIGATE:support]\n{msg}"
                            if "ig.me" not in msg:
                                msg += "\n\n👉 [**Join Official Instagram Creator Community**](https://ig.me/j/AQj1lYCWh_iV_S7J/)\nCreator contact: `@sherlock.fy`"
                        elif any(k in low_m for k in ("create short", "import video", "how to clip")) and "[NAVIGATE:" not in msg and "live" not in low_m:
                            msg = f"[NAVIGATE:create]\n{msg}\n\n*Tip: Click **App Guide** on the left menu for a step-by-step walkthrough!*"
                        return jsonify({
                            "ok": True,
                            "reply": msg,
                            "model": fastest_model,
                            "provider": "ollama",
                        })
        except Exception as exc:
            print(f"[Clippy] Ollama query failed ({exc}); using built-in knowledge fallback.")

    # Seamless high-accuracy fallback
    fallback_reply = _clippy_builtin_fallback(message)
    return jsonify({
        "ok": True,
        "reply": fallback_reply,
        "model": fastest_model or "Clipify Intelligence",
        "provider": "builtin" if not fastest_model else "builtin_fallback",
    })


def _cleanup_all_child_processes() -> None:
    """Terminate Ollama, FFmpeg, Live Studio, and any active job processes when Clipify closes."""
    global _CLEANUP_DONE
    if _CLEANUP_DONE:
        return
    _CLEANUP_DONE = True

    # 1. Stop Live Studio session (stops StreamConnector ffmpeg & LiveTranscriber)
    try:
        mgr = globals().get("_LIVE_STUDIO_MGR")
        if mgr is not None and getattr(mgr, "session_active", False):
            mgr.stop_session()
    except Exception:
        pass

    # 2. Terminate active job subprocesses
    pids_to_kill: list[int] = list(_STARTED_OLLAMA_PIDS)
    try:
        with jobs_lock:
            for j in jobs.values():
                pid = j.get("pid")
                if pid and j.get("status") == "running":
                    pids_to_kill.append(int(pid))
    except Exception:
        pass

    creationflags = _hidden_creationflags()
    if os.name == "nt":
        for pid in set(pids_to_kill):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5, creationflags=creationflags, check=False,
                )
            except Exception:
                pass
        # Ensure Ollama and any Clipify-bundled FFmpeg processes do not linger in background
        for img in ("ollama.exe", "ollama_llama_server.exe", "ffmpeg.exe", "ffprobe.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", img, "/T"],
                    capture_output=True, timeout=5, creationflags=creationflags, check=False,
                )
            except Exception:
                pass
    else:
        import signal as _sig
        for pid in set(pids_to_kill):
            try:
                os.kill(pid, _sig.SIGTERM)
            except Exception:
                pass
        for proc_name in ("ollama", "ffmpeg", "ffprobe"):
            try:
                subprocess.run(["pkill", "-f", proc_name], capture_output=True, timeout=3, check=False)
            except Exception:
                pass


import atexit as _atexit
import signal as _signal
_atexit.register(_cleanup_all_child_processes)


def _handle_exit_signal(signum, frame):
    _cleanup_all_child_processes()
    os._exit(0)


for _sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
    _sig_val = getattr(_signal, _sig_name, None)
    if _sig_val is not None:
        try:
            _signal.signal(_sig_val, _handle_exit_signal)
        except Exception:
            pass


def _is_port_in_use(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


if __name__ == "__main__":
    _host, _port = APP_HOST, APP_PORT
    _connect_host = "127.0.0.1" if _host in ("0.0.0.0", "::", "") else _host
    with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
        _lf.write(f"[{datetime.now()}] Startup check: host={_host}, connect={_connect_host}, port={_port}\n")
    if _is_port_in_use(_connect_host, _port):
        with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
            _lf.write(f"[{datetime.now()}] Port {_port} is in use, checking health\n")
        is_healthy = False
        try:
            with urllib.request.urlopen(f"http://{_connect_host}:{_port}/api/health", timeout=1.2) as r:
                if r.status == 200:
                    is_healthy = True
        except Exception as _he:
            with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                _lf.write(f"[{datetime.now()}] Health check failed: {_he}\n")
            is_healthy = False

        if is_healthy:
            with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                _lf.write(f"[{datetime.now()}] Healthy already running! Opening browser and exiting 0\n")
            browser = _find_app_browser()
            if browser:
                si = subprocess.STARTUPINFO()
                try:
                    import ctypes
                    if ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF):
                        setattr(si, "lpDesktop", r"WinSta0\Default")
                except Exception:
                    pass
                try:
                    subprocess.Popen([browser, f"--app=http://{_connect_host}:{_port}/", "--window-size=1440,900"], startupinfo=si)
                except Exception:
                    import webbrowser
                    webbrowser.open(f"http://{_connect_host}:{_port}/")
            else:
                import webbrowser
                webbrowser.open(f"http://{_connect_host}:{_port}/")
            sys.exit(0)
        else:
            with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
                _lf.write(f"[{datetime.now()}] Unhealthy port occupant! Killing stale listener\n")
            try:
                import subprocess
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-NetTCPConnection -LocalPort {_port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"],
                    timeout=5, capture_output=True, check=False
                )
                time.sleep(1.0)
            except Exception:
                pass

    with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
        _lf.write(f"[{datetime.now()}] Starting Flask app on {_host}:{_port}\n")
    try:
        from clipify.platform.gpu_manager import apply_gpu_selection, get_active_gpu_id
        apply_gpu_selection(get_active_gpu_id())
    except Exception as _gpu_init_err:
        pass
    if os.environ.get("CLIPPEDAI_NO_BROWSER", "").strip() not in {"1", "true", "yes"}:
        _open_app_window(_connect_host, _port)
    try:
        try:
            from werkzeug.serving import ThreadedWSGIServer
            ThreadedWSGIServer.request_queue_size = 128
        except Exception:
            pass
        app.run(host=_host, port=_port, debug=False, threaded=True)
        with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
            _lf.write(f"[{datetime.now()}] app.run returned cleanly\n")
    except BaseException as _be:
        with open(os.path.join(ROOT, "app_startup.log"), "a", encoding="utf-8") as _lf:
            _lf.write(f"[{datetime.now()}] app.run exception: {type(_be).__name__}: {_be}\n")
            import traceback
            traceback.print_exc(file=_lf)
