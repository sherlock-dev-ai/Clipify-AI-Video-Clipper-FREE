from __future__ import annotations

import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit
from windows_process import clear_ffmpeg_report_environment, install_hidden_subprocess_defaults

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

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
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

APP_HOST = "127.0.0.1"
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
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024


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

    if (request_authority.username or request_authority.password
            or request_host not in {"127.0.0.1", "localhost"}
            or request_port != APP_PORT):
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
NARRATE = NarratePipeline(ROOT, USER_DATA_DIR)
narrate_jobs: dict[str, dict[str, Any]] = {}
narrate_jobs_lock = threading.Lock()


def is_allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_allowed_logo(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS


def emit(job_id: str, kind: str, message: str, **extra: Any) -> None:
    event = {"kind": kind, "message": message, **extra}
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["events"].append(event)
        job["last_message"] = message
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
         if "[fatal]" in line.lower() or "[error]" in line.lower()),
        "",
    )
    if failure_line:
        return failure_line[:1000]
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
    if "[1/5] trim" in low:
        return max(current, 67), "Cutting the source clip", text
    if "[2/5] resize" in low:
        return max(current, 73), "Creating 9:16 composition", text
    if "[3/5] render dynamic" in low or "[captions]" in low:
        return max(current, 78), "Rendering dynamic captions", text
    if "[4/5] generating" in low or "[title]" in low:
        return max(current, 92), "Generating Short title", text
    if "[5/5] saved" in low or "metadata" in low:
        return max(current, 96), "Saving Short metadata", text
    if "[done]" in low:
        return max(current, 98), "Short rendered", text
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
        raw = str(raw or "").strip()
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


def _try_start_ollama() -> None:
    """Best-effort local Ollama startup; never blocks the web app."""
    global _OLLAMA_AUTOSTART_ATTEMPTED
    if _OLLAMA_AUTOSTART_ATTEMPTED:
        return
    _OLLAMA_AUTOSTART_ATTEMPTED = True
    if any(str(x).startswith(("http://127.0.0.1", "http://localhost")) for x in _ollama_candidates()):
        try:
            binary = shutil.which("ollama") or shutil.which("ollama.exe")
            if binary:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, creationflags=creationflags,
                                 start_new_session=True)
                print("[Ollama] Server was not reachable; attempted local auto-start.")
        except Exception as exc:
            print(f"[Ollama] Auto-start skipped: {type(exc).__name__}: {exc}")


def _discover_ollama_models() -> tuple[list[str], str | None]:
    """Discover Ollama models with localhost/127.0.0.1 fallback and useful diagnostics."""
    global OLLAMA_RUNTIME_BASE_URL
    import urllib.request
    last_error = "Ollama is not reachable."
    for attempt in range(2):
        for base in _ollama_candidates():
            try:
                version_req = urllib.request.Request(f"{base}/api/version", headers={"Accept": "application/json"})
                with urllib.request.urlopen(version_req, timeout=2.5) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status}")
                tags_req = urllib.request.Request(f"{base}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(tags_req, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
                if not isinstance(data, dict) or not isinstance(data.get("models"), list):
                    last_error = f"Ollama at {base} returned an unexpected /api/tags response."
                    continue
                models = [str(x.get("name")) for x in data["models"] if isinstance(x, dict) and x.get("name")]
                if models:
                    OLLAMA_RUNTIME_BASE_URL = base
                    return models, None
                OLLAMA_RUNTIME_BASE_URL = base
                return [], f"Ollama is running at {base}, but no models are installed."
            except Exception as exc:
                last_error = f"{base}: {type(exc).__name__}: {exc}"
        if attempt == 0:
            _try_start_ollama()
            import time
            time.sleep(1.5)
    print(f"[Ollama] Model discovery failed: {last_error}")
    return [], f"Ollama unavailable. Tried localhost:11434 and 127.0.0.1:11434. {last_error}"


def _ollama_models() -> list[str]:
    """Compatibility wrapper for callers that only need the model names."""
    models, _error = _discover_ollama_models()
    return models


def _default_model(models: list[str]) -> str:
    for preferred in ("qwen3:8b", "qwen3:14b"):
        if preferred in models:
            return preferred
    qwen = [m for m in models if m.lower().startswith("qwen")]
    return qwen[0] if qwen else (models[0] if models else "")


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


def _yt_dlp_command() -> list[str] | None:
    """Locate yt-dlp without tying the video pipeline to a global Python."""
    bundled = ROOT / "yt-dlp.exe"
    if bundled.is_file():
        return [str(bundled)]
    binary = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if binary:
        return [binary]
    runtime = runtime_python()
    if runtime is not None:
        runtime_scripts_exe = runtime.parent / "yt-dlp.exe"
        if runtime_scripts_exe.is_file():
            return [str(runtime_scripts_exe)]
        return [str(runtime), "-m", "yt_dlp"]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
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


def _media_duration_seconds(path_value: str) -> float:
    """Return the duration of a media file in seconds, or 0.0 when unknown."""
    p = Path(str(path_value or ""))
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
    v = str(value or default).strip().lstrip("#")
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        v = default.lstrip("#")
    return v.upper()


def _ffmpeg_color(value: str, opacity: int = 100) -> str:
    alpha = max(0, min(255, round(max(0, min(100, int(opacity))) * 2.55)))
    return f"0x{_hex6(value)}@{alpha/255:.3f}"


def _position_expr(position: str, margin: int, item_w: str = "w", item_h: str = "h") -> tuple[str, str]:
    m = str(max(0, int(margin)))
    if position == "top-left": return m, m
    if position == "top-center": return f"(W-{item_w})/2", m
    if position == "top-right": return f"W-{item_w}-{m}", m
    if position == "center-left": return m, f"(H-{item_h})/2"
    if position == "center": return f"(W-{item_w})/2", f"(H-{item_h})/2"
    if position == "center-right": return f"W-{item_w}-{m}", f"(H-{item_h})/2"
    if position == "bottom-left": return m, f"H-{item_h}-{m}"
    if position == "bottom-center": return f"(W-{item_w})/2", f"H-{item_h}-{m}"
    return f"W-{item_w}-{m}", f"H-{item_h}-{m}"


def _resolve_logo(path_value: str) -> str | None:
    p = Path(str(path_value or "").strip().strip('"'))
    if p.is_file():
        return str(p)
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
    value = os.path.abspath(str(path_value)).replace("\\", "/")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def apply_branding_to_file(input_video: str, output_video: str, branding: dict[str, Any], font_name: str = "Arial") -> None:
    """Apply logo/text branding to an already-rendered Short without rerunning AI."""
    ffmpeg = _ffmpeg_path()
    logo = _resolve_logo(str(branding.get("logo_path", ""))) if branding.get("logo_enabled") else None
    text = str(branding.get("text", "")).strip() if branding.get("text_enabled") else ""
    if not logo and not text:
        shutil.copy2(input_video, output_video)
        return

    filters: list[str] = []
    inputs = ["-i", input_video]
    current = "0:v"
    if logo:
        inputs += ["-i", logo]
        size = max(3, min(20, int(branding.get("logo_size", 8))))
        opacity = max(10, min(100, int(branding.get("logo_opacity", 80))))
        pos = str(branding.get("logo_position", "top-right"))
        margin = max(5, min(500, int(branding.get("logo_margin", 40))))
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
        size = max(3, min(12, int(branding.get("text_size", 6))))
        fs = max(34, round(1080 * size / 100))
        font_path = _font_path_for_editor(font_name)
        font_expr = f":fontfile='{_ffmpeg_filter_path(font_path)}'" if font_path else ""
        box = 1 if branding.get("text_bg_enabled") else 0
        boxcolor = _ffmpeg_color(str(branding.get("text_bg_color", "#000000")), int(branding.get("text_bg_opacity", 65)))
        color = _hex6(str(branding.get("text_color", "#FFFFFF")))
        tf = _ffmpeg_filter_path(temp_text)
        filters.append(f"[{current}]drawtext=textfile='{tf}':fontsize={fs}:fontcolor=0x{color}{font_expr}:x={x}:y={y}:box={box}:boxcolor={boxcolor}:boxborderw=18:fix_bounds=true[vtext]")
        current = "vtext"

    fc = ";".join(filters)
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", f"[{current}]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", output_video]
    proc = _run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if temp_text:
        try: Path(temp_text).unlink()
        except OSError: pass
    if proc.returncode != 0 or not Path(output_video).exists() or Path(output_video).stat().st_size < 1024:
        raise RuntimeError(f"Branding render failed: {proc.stderr[-1800:]}")


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
job_id: str, mode: str, clips: int, model: str, font: str, min_duration: int, max_duration: int, branding: dict[str, Any], split_screen: bool = False) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job["status"] = "running"
        job["progress"] = 2
        job["stage"] = "Starting Clipify AI"
        job["detail"] = "Launching the local pipeline…"
        job["stage_started"] = __import__("time").time()

    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    env = os.environ.copy()
    env.update({
        "PYTHONUNBUFFERED": "1",
        "CLIPPEDAI_INPUT_DIR": str(input_dir),
        "CLIPPEDAI_OUTPUT_DIR": str(output_dir),
        "CLIPPEDAI_MODE": mode,
        "OLLAMA_MODEL": model,
        "OLLAMA_URL": str(OLLAMA_RUNTIME_BASE_URL or _ollama_base_url()),
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
        "CLIPPEDAI_SPLIT_SCREEN": "1" if split_screen else "0",
    })
    diagnostic_log = job_dir / "diagnostics" / "qwen-decisions.jsonl"
    diagnostic_log.parent.mkdir(parents=True, exist_ok=True)
    env["CLIPPEDAI_QWEN_DIAGNOSTIC_LOG"] = str(diagnostic_log)
    cmd = [*_pipeline_command(input_dir), "--auto", "--clips", str(clips),
           "--min-duration", str(min_duration), "--max-duration", str(max_duration)]
    emit(job_id, "log", f"Starting {mode} mode with {model}; captions: {font}…")

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
                if elapsed >= 3:
                    detail = f"{detail.split(' · ')[0]} · stage time {elapsed}s"
                job["detail"] = detail

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
        recent_lines: list[str] = []
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if line:
                recent_lines.append(line)
                if len(recent_lines) > 12:
                    recent_lines.pop(0)
            progress, stage, detail = progress_for_line(line, progress, stage)
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]["progress"] = progress
                    jobs[job_id]["stage"] = stage
                    jobs[job_id]["detail"] = detail
                    jobs[job_id]["stage_started"] = __import__("time").time()
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
            emit(job_id, "complete", f"Created {len(outputs)} professional Short(s).", progress=100)
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


@app.get("/api/narrate/videos")
def narrate_videos():
    videos = NARRATE.scan_videos()
    folders = NARRATE.library_folders()
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


@app.post("/api/narrate/extra-clips")
def narrate_toggle_extra_clips():
    """Enable or disable the extra background clips (narrate download)."""
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


@app.get("/api/narrate/voices")
def narrate_voices():
    voices = available_voices()
    # Every voice already reports its own engine. Reporting a flat "Windows
    # SAPI" here hid the fact that Kokoro voices were available alongside it.
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


def _strip_reasoning_blocks(raw: str) -> str:
    text = str(raw or "")
    text = re.sub(r"<think\b.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n\s*\n\s*(?:analysis|reasoning|thought process|thinking)\s*[:\-]*\n*.*?\n\s*\n", "\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = text.replace("```json", "").replace("```", "").strip()
    text = text.strip("`\n \t")
    return text


def _script_is_complete(script: str) -> bool:
    text = _strip_reasoning_blocks(script).strip()
    if not text:
        return False
    if len(text.split()) < 28:
        return False
    if re.search(r"(?m)^\s*\[[^\]]+\]\s*$", text):
        return False
    if re.search(r"(?im)^\s*(?:\*{1,2}|_{1,2})?\s*(?:narrator|voice(?:over)?|speaker\s*\d*)\b[^\n:]*:", text):
        return False
    if re.search(r"[*_`#]", text):
        return False
    if re.search(r"(?im)^\s*(?:analysis|reasoning|thought process|thinking|plan|here are|i will)\s*:", text):
        return False
    if text.count("...") > 2:
        return False
    if re.search(r"(?im)^\s*(?:json|title|metadata?|prompt|story idea)\s*:", text):
        return False
    if re.search(r"[.!?][\s\n]*$", text):
        return True
    return False


def _call_ollama_script_prompt(system_prompt: str, user_prompt: str, fallback: str, model: str = "") -> str:
    import urllib.request

    preferred_model = model.strip() or os.getenv("OLLAMA_MODEL", "qwen3:8b").strip()
    if not preferred_model:
        return fallback
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
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + retry_note},
                ],
            }).encode("utf-8")
            request = urllib.request.Request(
                f"{OLLAMA_RUNTIME_BASE_URL or _ollama_base_url()}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            cleaned = _strip_reasoning_blocks(str(data.get("message", {}).get("content", "") or ""))
            if _script_is_complete(cleaned):
                return cleaned
        except Exception:
            break
    return fallback


def _prompt_fallback(prompt: str, style: str, duration: int = 30) -> str:
    prompt_lower = prompt.lower()
    if "school" in prompt_lower and ("16" in prompt_lower or "sixteen" in prompt_lower):
        return (
            "At sixteen, I thought the hardest part of school was passing the test.\n\n"
            "Then our teacher asked one simple question, and I confidently gave the exact wrong answer. "
            "The whole room went silent for two seconds before my friend started laughing so hard they dropped their pencil. "
            "I tried to save myself with a joke, but accidentally made the teacher laugh too.\n\n"
            "So I did not pass the test, but I definitely passed the embarrassment to the entire class."
        )
    if "siddharth" in prompt_lower and ("rejected" in prompt_lower or "girls" in prompt_lower):
        if duration <= 27:
            return (
                "Siddharth had been rejected so many times, he treated it like a routine.\n\n"
                "His friends told him to give up, but he tried one last time and expected another no. "
                "Instead, she laughed and said yes. After all those rejections, Siddharth finally learned the problem was not his confidence. "
                "He had been asking the wrong people."
            )
        return (
            "Siddharth had been rejected so many times, he started treating it like a daily routine.\n\n"
            "Every time he tried to talk to a girl, the answer was the same: no chance. His friends kept telling him to give up, "
            "but Siddharth decided to try one last time. He walked over, said exactly what he wanted to say, and waited for the rejection.\n\n"
            "But this time, she laughed and said yes. After all those rejections, Siddharth finally realized the problem was not his confidence. "
            "He had just been asking the wrong people."
        )
    if "joshua" in prompt_lower and "bullied" in prompt_lower:
        return (
            "Joshua kept his head down whenever the same group waited for him outside class. "
            "One afternoon, they took his backpack and dumped everything across the hallway while everyone watched. "
            "Joshua picked up his things, walked to the teacher, and calmly explained exactly what had happened. "
            "The hallway went silent when the teacher checked the cameras and called the group back. "
            "For the first time, Joshua did not have to defend himself because the truth had already done it."
        )
    subject = prompt.strip().rstrip(".!?")
    subject = re.sub(r"\([^)]*\)", "", subject).strip()
    subject = re.sub(r"\b(make it|write|create|generate|actually happened|actually happened|a dramatic story about|a story about)\b", "", subject, flags=re.I).strip(" ,:-")
    if style == "funny":
        return f"I thought {subject} would be easy until the first thing went wrong. The plan failed in front of everyone, so I tried one desperate fix. That fix created an even bigger problem, and the room went completely quiet. Then one ridiculous detail exposed the mistake, turning an embarrassing failure into the funniest moment of the day."
    if style == "dramatic":
        return f"I still remember how {subject} began with one detail nobody noticed. By midnight, it had led me to a locked door and a choice with real consequences. My first attempt failed, but it revealed who had been hiding the truth. When the door finally opened, the discovery changed the meaning of everything that happened before it."
    if style == "viral":
        return f"The first thing anyone noticed about {subject} was the one detail that made no sense. I ignored it, which was a terrible decision, because five minutes later the entire plan had turned into a ridiculous mess. Every quick fix made the problem more obvious, and now everyone was watching me pretend I knew what I was doing. Then {subject} made one completely unexpected move, and the room went silent before everyone started laughing."
    return f"I thought {subject} would be easy until the first thing went wrong. The plan failed in front of everyone, so I tried one desperate fix. That fix created an even bigger problem, and the room went completely quiet. Then one ridiculous detail exposed the mistake, turning an embarrassing failure into the funniest moment of the day."


def _fit_script_to_duration(script: str, duration: int) -> str:
    target_words = max(40, int(round(duration * 3.2)))
    words = script.split()
    if len(words) >= int(target_words * 0.94):
        return script.strip()
    expansion = (
        "For a second, nobody knew what would happen next.",
        "The smallest detail changed the plan, and suddenly every choice mattered.",
        "The pressure kept rising because the obvious solution made the problem worse.",
        "Then one final decision exposed the truth and gave the story a clear ending.",
        "The room fell quiet, and I finally understood why everyone had warned me about that idea.",
        "I took a breath, tried again, and discovered the simplest answer had been right in front of me.",
        "For a moment I thought I had made things worse, but a tiny clue changed everything.",
        "My friends started laughing, then they helped me turn the awkward mistake into a better plan.",
        "The next few minutes were chaotic, but every surprise pushed the story toward its payoff.",
        "I kept going because stopping there would have made the whole strange effort pointless.",
        "By the end, the problem looked completely different from the way it had started.",
        "That was when I realized the funniest part was how confidently I had misunderstood everything.",
        "We tried one last time, and this time the result finally made sense to everyone watching.",
        "I still remember the reaction, because nobody expected that ordinary detail to matter so much.",
        "Afterward we retold the story all week, each time making the ending sound even more ridiculous.",
        "It started as a simple shortcut, but it became the moment everyone remembered from that day.",
    )
    result = script.strip()
    for sentence in expansion:
        if len(result.split()) >= target_words:
            break
        result = f"{result} {sentence}".strip()
    return result


def _format_script_sentences(script: str) -> str:
    clean = re.sub(r"\s+", " ", str(script or "")).strip()
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
    target_words = int(round(duration * 2.65))
    pacing = f"Write about {target_words}-{target_words + 12} words so the narration lasts close to {duration} seconds at a natural speaking pace of roughly 3.2 words per second. Do not make it shorter and do not pad it with filler."
    if any(word in prompt_lower for word in ("funny", "joke", "laugh", "roast", "chaos", "meme")):
        system_prompt = f"Write a short first-person anecdote for a vertical narrated video, in the style of someone telling a true story. Start with a specific situation or age, use concrete actions and details, build a problem step by step, and end with a memorable consequence or understated payoff. Make it funny but believable. Avoid generic commentary, film directions, labels, and phrases like 'the main character' or 'everything changed'. {pacing} Return only the story."
    elif any(word in prompt_lower for word in ("dramatic", "story", "tension", "reveal", "wow", "epic")):
        system_prompt = f"Write a short first-person anecdote for a vertical narrated video, in the style of someone calmly recounting something that actually happened. Open with a specific situation, include concrete actions and sensory details, let the tension rise naturally, and finish with a clear consequence or twist. Do not use generic commentary, film directions, labels, or phrases like 'the main character' or 'everything changed'. {pacing} Return only the story."
    else:
        system_prompt = f"Write a viral-feeling short-form story for a vertical narrated video, as if a funny, observant person is telling a friend what actually happened. Treat the user's idea as the story seed, not as a title. Open with an irresistible specific detail in the first sentence. Use concrete actions, a strange or funny complication, escalating consequences, and a payoff that makes people want to replay it. Keep the voice casual, human, slightly surprising, and addictive, never like an AI summary, movie trailer, motivational speech, or list. Do not use generic commentary, film directions, labels, or phrases like 'the main character' or 'everything changed'. {pacing} Return only the story."

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
    target_words = int(round(duration * 3.2))
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

    # Reuse a matching cached transcription from the shared input folder when available.
    cached = USER_DATA_DIR / "input" / f"{Path(safe_name).stem}_transcription.pkl"
    if cached.exists():
        shutil.copy2(cached, input_dir / cached.name)

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
    emit(job_id, "log", f"Uploaded {safe_name}")
    return jsonify({"job_id": job_id, "filename": safe_name})


@app.post("/api/import-youtube")
def import_youtube():
    """Start a background yt-dlp download and expose real progress through /api/status."""
    data = request.get_json(silent=True) or {}
    source_url = _normalize_youtube_url(data.get("url", ""))
    if source_url is None:
        return jsonify({"error": "Paste a valid YouTube or youtu.be video link."}), 400
    yt_dlp_cmd = _yt_dlp_command()
    if not yt_dlp_cmd:
        return jsonify({"error": "YouTube import requires yt-dlp. Install the web requirements, then restart Clipify AI."}), 503

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id, "filename": "", "source_url": source_url,
            "status": "downloading", "progress": 0, "stage": "Connecting to YouTube",
            "detail": "Starting yt-dlp…", "events": [], "outputs": [],
        }

    def worker() -> None:
        proc: subprocess.Popen[str] | None = None
        try:
            ffmpeg_path = _ffmpeg_path()
            output_template = str(input_dir / "youtube.%(ext)s")
            command = [*yt_dlp_cmd, "--no-playlist", "--no-warnings", "--newline", "--progress",
                       "--progress-template", "download:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.speed)s|%(progress.eta)s",
                       "--restrict-filenames", "--merge-output-format", "mp4", "--max-filesize", "4G",
                       "--socket-timeout", "20", "--retries", "3", "--fragment-retries", "3",
                       "--extractor-args", "youtube:player_client=android",
                       "-f", "best[height<=1080][ext=mp4]/best[height<=1080]/best",
                       "--ffmpeg-location", str(Path(ffmpeg_path).parent),
                       "-o", output_template, source_url]
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=_hidden_creationflags())
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                with jobs_lock:
                    job = jobs.get(job_id)
                    if not job:
                        return
                    if line.startswith("[download]") or line.startswith("download:"):
                        fields = line.split("|", 4) if line.startswith("download:") else []
                        pct_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                        pct = float(pct_match.group(1)) if pct_match else 0.0
                        if len(fields) >= 3:
                            try:
                                downloaded = int(fields[1])
                                total = int(fields[2])
                                if total > 0:
                                    pct = downloaded * 100 / total
                            except (TypeError, ValueError):
                                pass
                        job["progress"] = max(job["progress"], max(0, min(99, int(pct))))
                        job["stage"] = "Downloading video"
                        job["detail"] = line
                    elif line.startswith("[Merger]") or "merging" in line.lower():
                        job["progress"] = max(job["progress"], 98)
                        job["stage"] = "Finalizing download"
                        job["detail"] = "Merging video and audio…"
                    elif "destination:" in line.lower():
                        job["detail"] = line
                    job["events"].append({"kind":"log", "message":line})
            return_code = proc.wait()
            videos = []
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
                if probe.returncode == 0 and "video" in probe.stdout.lower() and "audio" in probe.stdout.lower():
                    videos.append(candidate)
            if return_code != 0 or not videos:
                last_error = ""
                with jobs_lock:
                    for event in reversed(jobs[job_id].get("events", [])):
                        message = str(event.get("message", ""))
                        if message.startswith("ERROR:"):
                            last_error = message
                            break
                detail = last_error or ("yt-dlp failed." if return_code != 0 else "yt-dlp finished but no video containing both video and audio was created.")
                with jobs_lock:
                    jobs[job_id].update(status="error", stage="YouTube download failed", detail=detail)
                    jobs[job_id]["events"].append({"kind":"error","message":detail})
                return
            target = max(videos, key=lambda p: p.stat().st_mtime)
            safe_name = secure_filename(target.name) or f"youtube_{job_id}.mp4"
            with jobs_lock:
                jobs[job_id].update(filename=safe_name, status="uploaded", progress=100,
                                    stage="Video ready", detail="YouTube download complete.")
                jobs[job_id]["events"].append({"kind":"complete","message":"YouTube download complete.","progress":100})
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
    return jsonify({"job_id": job_id, "filename": "", "size": 0, "status": "downloading"}), 202


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
    return jsonify({"ok": True, "path": str(target), "filename": target.name})


@app.post("/api/start")
def start():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()
    if payload and isinstance(payload.get("branding"), str):
        try:
            parsed = json.loads(payload["branding"])
            if isinstance(parsed, dict):
                payload["branding"] = parsed
        except (TypeError, ValueError):
            payload["branding"] = {}
    data = payload or {}
    split_screen = str(data.get("split_screen", data.get("splitScreen", "0"))).strip().lower() in {"1", "true", "yes", "on"}
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
    if max_duration < min_duration:
        max_duration = min_duration

    # A source shorter than the requested minimum can never yield a clip, and
    # the pipeline then fails with "No final captioned Shorts were produced."
    # Shorten the requested window to fit the footage instead, and say so.
    job_dir = _safe_job_directory(job_id)
    if job_dir is None or not job_dir.is_dir():
        return jsonify({"error": "Job not found."}), 404
    input_dir = job_dir / "input"
    if input_dir.is_dir():
        sources = sorted(p for p in input_dir.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"})
        if sources:
            source_seconds = _media_duration_seconds(str(sources[0]))
            if source_seconds and source_seconds < min_duration:
                fitted_max = max(5, int(source_seconds))
                fitted_min = max(5, min(fitted_max, int(source_seconds * 0.6)))
                if (fitted_min, fitted_max) != (min_duration, max_duration):
                    emit(job_id, "log", f"[Setup] Source is {source_seconds:.0f}s long; "
                                        f"clip length adjusted from {min_duration}-{max_duration}s "
                                        f"to {fitted_min}-{fitted_max}s to fit.")
                    min_duration, max_duration = fitted_min, fitted_max

    if mode not in MODES:
        return jsonify({"error": "Invalid editing mode."}), 400
    models, model_error = _discover_ollama_models()
    if not models:
        return jsonify({"error": model_error, "models": []}), 503
    if not model:
        model = _default_model(models)
    if models and model not in models:
        return jsonify({"error": f"Ollama model '{model}' is not installed.", "models": models}), 400
    allowed_fonts = ["Montserrat Extra Bold", "Arial", "Arial Black", "Segoe UI", "Segoe UI Black", "Impact", "Tahoma", "Trebuchet MS", "Verdana", "Calibri", "Aptos", "Comic Sans MS", "Georgia"]
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
        job.update({"mode": mode, "clips": clips, "model": model, "font": font,
                    "min_duration": min_duration, "max_duration": max_duration})
    branding_raw = data.get("branding") if isinstance(data.get("branding"), dict) else {}
    branding = {
        "logo_enabled": bool(branding_raw.get("logo_enabled", branding_raw.get("watermark_enabled", False))),
        "logo_path": str(branding_raw.get("logo_path", branding_raw.get("watermark_path", str(ROOT / "static" / "clipify-ai-mark.png")))).strip(),
        "logo_position": str(branding_raw.get("logo_position", branding_raw.get("watermark_position", "top-right"))),
        "logo_size": max(3, min(20, int(branding_raw.get("logo_size", branding_raw.get("watermark_size", 8))))),
        "logo_opacity": max(10, min(100, int(branding_raw.get("logo_opacity", branding_raw.get("watermark_opacity", 80))))),
        "logo_margin": max(5, min(200, int(branding_raw.get("logo_margin", branding_raw.get("watermark_margin", 40))))),
        "logo_x": max(0, min(100, float(branding_raw.get("logo_x", branding_raw.get("watermark_x", 92))))),
        "logo_y": max(0, min(100, float(branding_raw.get("logo_y", branding_raw.get("watermark_y", 8))))),
        "logo_bg_remove": bool(branding_raw.get("logo_bg_remove", branding_raw.get("watermark_bg_remove", False))),
        "logo_bg_color": "#" + _hex6(str(branding_raw.get("logo_bg_color", branding_raw.get("watermark_bg_color", "#9B5CFF")))),
        "logo_bg_similarity": max(0.01, min(1.0, float(branding_raw.get("logo_bg_similarity", branding_raw.get("watermark_bg_similarity", 0.22))))),
        "logo_bg_blend": max(0.0, min(1.0, float(branding_raw.get("logo_bg_blend", 0.05)))),
        "text_enabled": bool(branding_raw.get("text_enabled", False)),
        "text": str(branding_raw.get("text", "")).strip()[:100],
        "text_position": str(branding_raw.get("text_position", "bottom-center")),
        "text_size": max(3, min(12, int(branding_raw.get("text_size", 6)))),
        "text_color": str(branding_raw.get("text_color", "#FFFFFF")),
        "text_bg_enabled": bool(branding_raw.get("text_bg_enabled", True)),
        "text_bg_color": str(branding_raw.get("text_bg_color", "#000000")),
        "text_bg_opacity": max(0, min(100, int(branding_raw.get("text_bg_opacity", 65)))),
        "text_margin": max(20, min(500, int(branding_raw.get("text_margin", 110)))),
        "text_x": max(0, min(100, float(branding_raw.get("text_x", 50)))),
        "text_y": max(0, min(100, float(branding_raw.get("text_y", 75)))),
    }
    if branding["logo_position"] not in BRANDING_POSITIONS:
        branding["logo_position"] = "top-right"
    if branding["text_position"] not in BRANDING_POSITIONS:
        branding["text_position"] = "bottom-center"
    with jobs_lock:
        jobs[job_id]["branding"] = branding
        jobs[job_id]["split_screen"] = split_screen
    threading.Thread(target=run_job, args=(job_id, mode, clips, model, font, min_duration, max_duration, branding, split_screen), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "model": model, "font": font, "min_duration": min_duration, "max_duration": max_duration, "branding": branding, "split_screen": split_screen})



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

    b = data.get("branding") if isinstance(data.get("branding"), dict) else {}
    branding = {
        "logo_enabled": bool(b.get("logo_enabled")),
        "logo_path": str(b.get("logo_path", "")).strip(),
        "logo_position": str(b.get("logo_position", "top-right")),
        "logo_size": max(3, min(20, int(b.get("logo_size", 8)))),
        "logo_opacity": max(10, min(100, int(b.get("logo_opacity", 80)))),
        "logo_margin": max(5, min(500, int(b.get("logo_margin", 40)))),
        "logo_x": max(0, min(100, float(b.get("logo_x", 92)))),
        "logo_y": max(0, min(100, float(b.get("logo_y", 8)))),
        "logo_bg_remove": bool(b.get("logo_bg_remove")),
        "logo_bg_color": "#" + _hex6(str(b.get("logo_bg_color", "#9B5CFF"))),
        "logo_bg_similarity": max(0.01, min(1.0, float(b.get("logo_bg_similarity", 0.22)))),
        "logo_bg_blend": max(0.0, min(1.0, float(b.get("logo_bg_blend", 0.05)))),
        "text_enabled": bool(b.get("text_enabled")),
        "text": str(b.get("text", "")).strip()[:100],
        "text_position": str(b.get("text_position", "bottom-center")),
        "text_size": max(3, min(12, int(b.get("text_size", 6)))),
        "text_color": "#" + _hex6(str(b.get("text_color", "#FFFFFF"))),
        "text_bg_enabled": bool(b.get("text_bg_enabled")),
        "text_bg_color": "#" + _hex6(str(b.get("text_bg_color", "#000000"))),
        "text_bg_opacity": max(0, min(100, int(b.get("text_bg_opacity", 65)))),
        "text_margin": max(20, min(500, int(b.get("text_margin", 110)))),
        "text_x": max(0, min(100, float(b.get("text_x", 50)))),
        "text_y": max(0, min(100, float(b.get("text_y", 75)))),
    }
    if branding["logo_position"] not in BRANDING_POSITIONS:
        branding["logo_position"] = "top-right"
    if branding["text_position"] not in BRANDING_POSITIONS:
        branding["text_position"] = "bottom-center"

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
        return jsonify({"ok": False, "error": "Metadata not found."}), 404
    try:
        return jsonify({"ok": True, **json.loads(meta.read_text(encoding="utf-8"))})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Metadata read failed: {exc}"}), 500

@app.get("/api/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(
            {
                "id": job["id"],
                "filename": job["filename"],
                "status": job["status"],
                "progress": job["progress"],
                "stage": job["stage"],
                "outputs": job.get("outputs", []),
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
            with jobs_lock:
                job = jobs.get(job_id)
                if job:
                    new_events = job["events"][sent:]
                    sent = len(job["events"])
                    done = job["status"] in {"done", "error"}
                    snapshot = {
                        "kind": "status",
                        "status": job["status"],
                        "progress": job["progress"],
                        "stage": job["stage"],
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

@app.get("/api/health")
def health():
    installed, error = _discover_ollama_models()
    return jsonify({
        "ok": True,
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
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
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
            import subprocess
            _fr = subprocess.run(
                [FFMPEG_BIN, "-version"],
                capture_output=True, text=True, timeout=10, check=False
            )
            if _fr.returncode == 0:
                ffmpeg_ok = True
                ffmpeg_version = (_fr.stdout or "").splitlines()[0] if _fr.stdout else ""
        except Exception as fe:
            ffmpeg_version = str(fe)
        report["ffmpeg"] = {
            "path": FFMPEG_BIN,
            "exists": os.path.isfile(FFMPEG_BIN),
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
                cuda_version = torch.version.cuda or ""
        except Exception as te:
            gpu_name = str(te)
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
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = _os.environ.get(var)
        if not base:
            continue
        # Edge is the browser guaranteed on Windows 11 and on any current
        # Windows 10, and it is the same engine as the WebView2 runtime that
        # pywebview would use anyway.
        candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
        candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    # Chromium/Chrome, for machines that removed Edge but kept Chrome.
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = _os.environ.get(var)
        if not base:
            continue
        candidates.extend(
            glob.glob(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        )
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
    """Create the launcher shortcut that gives the app window its own icon.

    The window is a Chromium app-mode process, so by default Windows shows
    Edge's globe for it in the taskbar, the Alt+Tab list and the title bar. A
    shortcut whose AppUserModelID matches ``--app-id`` makes Windows adopt the
    shortcut's own icon for the window instead, which is the standard way to
    brand a Chromium app window. The shortcut is reused, and rebuilt when the
    arguments change.

    Returns the shortcut path, or an empty string when it could not be made.
    """
    import os as _os
    import subprocess

    try:
        programs = _os.path.join(
            _os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"
        )
        _os.makedirs(programs, exist_ok=True)
        link = _os.path.join(programs, "Clipify AI.lnk")
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

    # Always rewritten rather than cached: a stale shortcut would keep launching
    # the old profile or miss a flag, and the COM call is cheap at startup.
    # WScript.Shell is the only COM API available without extra dependencies.
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
    import urllib.error
    import urllib.request

    url = f"http://{host}:{port}/"

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
        opened = False
        if browser:
            args = [
                browser,
                f"--app={url}",
                "--window-size=1440,900",
                "--no-default-browser-check",
                "--no-first-run",
            ]
            if profile:
                args.append(f"--user-data-dir={profile}")
            try:
                subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                opened = True
            except Exception:
                opened = False

        if not opened:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

    threading.Thread(target=wait_then_open, name="clipify-open-window", daemon=True).start()


def _is_port_in_use(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


if __name__ == "__main__":
    _host, _port = APP_HOST, APP_PORT
    if _is_port_in_use(_host, _port):
        # Already running: surface the app in the browser rather than failing on bind
        try:
            import webbrowser
            webbrowser.open(f"http://{_host}:{_port}/")
        except Exception:
            pass
        sys.exit(0)

    if os.environ.get("CLIPPEDAI_NO_BROWSER", "").strip() not in {"1", "true", "yes"}:
        _open_app_window(_host, _port)
    app.run(host=_host, port=_port, debug=False, threaded=True)
