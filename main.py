"""Main script to process videos and create YouTube Shorts using AI-powered transcription and clip detection."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import pickle
import re
import shutil
import socket
import statistics
import subprocess
import sys
import string
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
from windows_process import install_hidden_subprocess_defaults

install_hidden_subprocess_defaults()

def _run_hidden(*args, **kwargs):
    """Run bundled CLI tools without spawning a console window on Windows."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(*args, **kwargs)


def _check_output_hidden(*args, **kwargs):
    if os.name == "nt":
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.check_output(*args, **kwargs)



# Locate and expose the ClippedAI ML runtime before any heavy import happens.
# In a compiled build the ML tier (torch, whisperx, clipsai, ...) is installed
# separately; in development the interpreter's own site-packages already has it.
from clippedai_runtime import (  # noqa: E402
    MISSING_MESSAGE as _MISSING_RUNTIME_HINT,
    bootstrap as bootstrap_runtime,
    frozen as _compiled_build,
    require_runtime as _require_runtime,
    runtime_status,
)

_socket_timeout = float(os.environ.get("CLIPPEDAI_SOCKET_TIMEOUT", "12"))
try:
    socket.setdefaulttimeout(_socket_timeout)
except Exception:
    pass

try:
    import cv2
except Exception:
    # OpenCV belongs to the ML runtime tier. In a compiled build the runtime is
    # not on sys.path yet at import time, so this is re-resolved by
    # _ensure_cv2() once _init_ml_runtime() has bootstrapped it. Failing here is
    # not an error: `main.exe --help` must work before the runtime exists.
    cv2 = None
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PIL import ImageFont
except Exception:
    ImageFont = None

from dotenv import load_dotenv


def _ensure_cv2():
    """Resolve the module-level ``cv2`` handle after the runtime is bootstrapped.

    The camera/framing code reads the module global ``cv2`` directly. It is None
    at import time in a compiled build, because the ML runtime is only added to
    sys.path later by _init_ml_runtime(). Without this re-resolution the camera
    silently degrades to "Center fallback; samples=0".
    """
    global cv2
    if cv2 is None:
        try:
            import cv2 as _cv2

            cv2 = _cv2
        except Exception as exc:
            print(f"  [Framing] OpenCV unavailable: {type(exc).__name__}: {exc}")
    return cv2


def _clip_class():
    """ClipsAI's Clip type, imported on first use.

    ClipsAI belongs to the ML runtime tier, so it cannot be imported at module
    level without breaking `main.exe --help` on a machine that has no runtime
    installed yet.
    """
    from clipsai.clip.clip import Clip

    return Clip


def _init_torch() -> None:
    """Register the safe globals WhisperX checkpoints need.

    Torch belongs to the ML runtime tier, so it is imported lazily: a compiled
    main.exe must still be able to print --help before the runtime exists.
    """
    try:
        import torch
    except Exception:
        return
    try:
        from omegaconf.nodes import AnyNode
        torch.serialization.add_safe_globals([AnyNode])
    except Exception:
        pass


def _nltk_resource_available(nltk_data, resources) -> bool:
    """Return whether any NLTK resource path is already available locally."""
    for resource in resources:
        try:
            nltk_data.find(resource)
            return True
        except LookupError:
            continue
        except Exception:
            continue
    return False


def _init_nltk() -> None:
    """Patch NLTK downloads to be offline-first, then make punkt available.

    NLTK belongs to the ML runtime tier, so it is imported lazily.
    """
    try:
        import nltk
    except Exception:
        return

    if not getattr(nltk, "_clippedai_patched", False):
        original_download = nltk.download

        def _safe_nltk_download(info_or_id=None, download_dir=None, quiet=False,
                                force=False, raise_on_error=False, **kwargs):
            try:
                if info_or_id:
                    _lookup = {
                        "punkt": (
                            "tokenizers/punkt",
                            "tokenizers/punkt/english.pickle",
                            "tokenizers/punkt_tab/english/",
                        ),
                        "punkt_tab": (
                            "tokenizers/punkt_tab",
                            "tokenizers/punkt_tab/english/",
                        ),
                    }
                    paths = _lookup.get(info_or_id)
                    if paths and _nltk_resource_available(nltk.data, paths):
                        return True
            except Exception:
                pass
            try:
                return original_download(
                    info_or_id=info_or_id, download_dir=download_dir,
                    quiet=True if not quiet else quiet, force=force,
                    raise_on_error=False, **kwargs,
                )
            except Exception:
                return False

        nltk.download = _safe_nltk_download
        try:
            import nltk.downloader as _nltk_dl
            _nltk_dl.download = _safe_nltk_download
            _nltk_dl._clippedai_patched = True
        except Exception:
            pass
        nltk._clippedai_patched = True

    _ensure_nltk_punkt()


def _init_ml_runtime(feature: str = "The Clipify AI video pipeline") -> None:
    """Prepare the ML runtime tier. Fails loudly when it is genuinely absent."""
    if _compiled_build:
        _require_runtime(feature)
    bootstrap_runtime()
    _init_torch()
    _init_nltk()
    _ensure_cv2()

# Suppress unnecessary warnings
import warnings

warnings.filterwarnings("ignore", message="Model was trained with pyannote.audio")
warnings.filterwarnings("ignore", message="Model was trained with torch")
warnings.filterwarnings("ignore", message="Lightning automatically upgraded")
warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype() is deprecated")
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")
warnings.filterwarnings("ignore", message="torchaudio._backend.list_audio_backends has been deprecated")

# Suppress unnecessary warnings via environment variables
# Keep FFmpeg from writing a global report beside the installed executable.
# The app captures worker output as per-job diagnostics.
os.environ.pop("FFREPORT", None)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Load environment variables
load_dotenv()

# Ensure required NLTK data is available (safe offline-first check)
def _ensure_nltk_punkt() -> bool:
    try:
        import nltk
    except Exception:
        return False
    punkt_resources = (
        "tokenizers/punkt",
        "tokenizers/punkt/english.pickle",
        "tokenizers/punkt_tab/english/",
    )
    if _nltk_resource_available(nltk.data, punkt_resources):
        return True
    try:
        nltk.download("punkt", quiet=True, raise_on_error=False)
    except Exception:
        pass
    try:
        nltk.download("punkt_tab", quiet=True, raise_on_error=False)
    except Exception:
        pass
    return _nltk_resource_available(nltk.data, punkt_resources)

# --- Directories ---
INPUT_DIR = os.getenv("CLIPPEDAI_INPUT_DIR", "input")
OUTPUT_DIR = os.getenv("CLIPPEDAI_OUTPUT_DIR", "output")
FONT_DIR = os.getenv("CLIPPEDAI_FONT_DIR", "fonts")
EDIT_MODE = os.getenv("CLIPPEDAI_MODE", "viral").strip().lower()

# Create output directory if it does not exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Hugging Face ---
HUGGINGFACE_TOKEN = os.getenv(
    "HUGGINGFACE_TOKEN",
    "your_huggingface_token_here"
)

# --- Clip Duration ---
# Hard Shorts bounds. Ignore legacy .env values of 45/120 from the old pipeline.
def _env_duration(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        val = int(str(raw).split()[0])
    except (TypeError, ValueError):
        val = default
    # Old project defaults were 45 / 120 — those are no longer valid for Shorts.
    if name == "MIN_CLIP_DURATION" and val == 45:
        val = default
    if name == "MAX_CLIP_DURATION" and val == 120:
        val = default
    return max(5, min(60, val))


MIN_CLIP_DURATION = _env_duration("MIN_CLIP_DURATION", 25)
MAX_CLIP_DURATION = _env_duration("MAX_CLIP_DURATION", 60)
if MAX_CLIP_DURATION < MIN_CLIP_DURATION:
    MAX_CLIP_DURATION = 60
PREFERRED_MIN_CLIP_DURATION = max(MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, _env_duration("PREFERRED_MIN_CLIP_DURATION", 30)))
PREFERRED_MAX_CLIP_DURATION = max(PREFERRED_MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, _env_duration("PREFERRED_MAX_CLIP_DURATION", 55)))

# --- Ollama Configuration ---
def normalize_ollama_base_url(value: Optional[str]) -> str:
    """Return the Ollama server base URL, never an API endpoint.

    Older ClippedAI environment files used ``/api/chat`` as OLLAMA_URL.
    Accept that legacy form by removing the endpoint once, then construct each
    endpoint explicitly.  This prevents paths such as ``/api/chat/api/chat``.
    """
    raw_value = (value or "http://localhost:11434").strip()
    parsed = urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "OLLAMA_URL must be an http(s) server URL, for example "
            "http://localhost:11434"
        )

    path = parsed.path.rstrip("/")
    for endpoint in ("/api/chat", "/api/generate", "/api/tags", "/api/version"):
        if path.lower().endswith(endpoint):
            path = path[:-len(endpoint)]
            break

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


OLLAMA_BASE_URL = normalize_ollama_base_url(os.getenv("OLLAMA_URL"))
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")
CAPTION_FONT = os.getenv("CLIPPEDAI_FONT", "Montserrat Extra Bold")
CAPTION_FONT_SIZE = int(os.getenv("CLIPPEDAI_FONT_SIZE", "78"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))

# --- Transcription ---
TRANSCRIPTION_MODEL = os.getenv(
    "TRANSCRIPTION_MODEL",
    "large-v1"
)

# --- Resizing ---
ASPECT_RATIO_WIDTH = int(
    os.getenv("ASPECT_RATIO_WIDTH", "9")
)

ASPECT_RATIO_HEIGHT = int(
    os.getenv("ASPECT_RATIO_HEIGHT", "16")
)

# --- Optional branding overlays ---
BRANDING_POSITIONS = {"top-left","top-center","top-right","center-left","center","center-right","bottom-left","bottom-center","bottom-right","custom"}
SPLIT_SCREEN = os.getenv("CLIPPEDAI_SPLIT_SCREEN", "0").strip().lower() in {"1", "true", "yes", "on"}
WATERMARK_ENABLED = os.getenv("CLIPPEDAI_WATERMARK_ENABLED", "0") == "1"
WATERMARK_PATH = os.getenv(
    "CLIPPEDAI_WATERMARK_PATH",
    str(Path(__file__).resolve().parent / "static" / "clipify-ai-mark.png"),
)
WATERMARK_POSITION = os.getenv("CLIPPEDAI_WATERMARK_POSITION", "top-right") if os.getenv("CLIPPEDAI_WATERMARK_POSITION", "top-right") in BRANDING_POSITIONS else "top-right"
WATERMARK_SIZE = max(3, min(20, int(os.getenv("CLIPPEDAI_WATERMARK_SIZE", "8"))))
WATERMARK_OPACITY = max(10, min(100, int(os.getenv("CLIPPEDAI_WATERMARK_OPACITY", "80"))))
WATERMARK_MARGIN = max(5, min(200, int(os.getenv("CLIPPEDAI_WATERMARK_MARGIN", "40"))))
WATERMARK_X = max(0.0, min(100.0, float(os.getenv("CLIPPEDAI_WATERMARK_X", "92"))))
WATERMARK_Y = max(0.0, min(100.0, float(os.getenv("CLIPPEDAI_WATERMARK_Y", "8"))))
WATERMARK_BG_REMOVE = os.getenv("CLIPPEDAI_WATERMARK_BG_REMOVE", "0") == "1"
WATERMARK_BG_COLOR = os.getenv("CLIPPEDAI_WATERMARK_BG_COLOR", "#9B5CFF")
WATERMARK_BG_SIMILARITY = max(0.01, min(1.0, float(os.getenv("CLIPPEDAI_WATERMARK_BG_SIMILARITY", "0.22"))))
WATERMARK_BG_BLEND = max(0.0, min(1.0, float(os.getenv("CLIPPEDAI_WATERMARK_BG_BLEND", "0.05"))))
TEXT_ENABLED = os.getenv("CLIPPEDAI_TEXT_ENABLED", "0") == "1"
TEXT_OVERLAY = os.getenv("CLIPPEDAI_TEXT", "").strip()
TEXT_POSITION = os.getenv("CLIPPEDAI_TEXT_POSITION", "bottom-center") if os.getenv("CLIPPEDAI_TEXT_POSITION", "bottom-center") in BRANDING_POSITIONS else "bottom-center"
TEXT_SIZE = max(3, min(12, int(os.getenv("CLIPPEDAI_TEXT_SIZE", "6"))))
TEXT_COLOR = os.getenv("CLIPPEDAI_TEXT_COLOR", "#FFFFFF")
TEXT_BG_ENABLED = os.getenv("CLIPPEDAI_TEXT_BG_ENABLED", "1") == "1"
TEXT_BG_COLOR = os.getenv("CLIPPEDAI_TEXT_BG_COLOR", "#000000")
TEXT_BG_OPACITY = max(0, min(100, int(os.getenv("CLIPPEDAI_TEXT_BG_OPACITY", "65"))))
TEXT_MARGIN = max(20, min(500, int(os.getenv("CLIPPEDAI_TEXT_MARGIN", "110"))))
TEXT_X = max(0.0, min(100.0, float(os.getenv("CLIPPEDAI_TEXT_X", "50"))))
TEXT_Y = max(0.0, min(100.0, float(os.getenv("CLIPPEDAI_TEXT_Y", "75"))))

# --- Groq API ---
GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY",
    "your_groq_api_key_here"
)

# --- Subtitles ---
SUBTITLE_FONT = "Montserrat Extra Bold"
SUBTITLE_FONT_SIZE = 80
SUBTITLE_ALIGNMENT = 8  # Top center
SUBTITLE_MARGIN_V = 120

SUBTITLE_STYLES = {
    "Default": {
        "Fontname": SUBTITLE_FONT,
        "Fontsize": SUBTITLE_FONT_SIZE,
        "PrimaryColour": "&H00FFFFFF",
        "SecondaryColour": "&H000000FF",
        "OutlineColour": "&H40000000",
        "BackColour": "&HFF000000",
        "Bold": -1,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 2,
        "Angle": 0,
        "BorderStyle": 1,
        "Outline": 15,
        "Shadow": 0,
        "Alignment": SUBTITLE_ALIGNMENT,
        "MarginL": 30,
        "MarginR": 30,
        "MarginV": SUBTITLE_MARGIN_V,
        "Encoding": 1,
    },
    "Yellow": {
        "Fontname": SUBTITLE_FONT,
        "Fontsize": SUBTITLE_FONT_SIZE,
        "PrimaryColour": "&H0000FFFF",
        "SecondaryColour": "&H000000FF",
        "OutlineColour": "&H40000000",
        "BackColour": "&HFF000000",
        "Bold": -1,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 2,
        "Angle": 0,
        "BorderStyle": 1,
        "Outline": 15,
        "Shadow": 0,
        "Alignment": SUBTITLE_ALIGNMENT,
        "MarginL": 30,
        "MarginR": 30,
        "MarginV": SUBTITLE_MARGIN_V,
        "Encoding": 1,
    },
}


def get_transcription_file_path(input_path: str) -> str:
    """Generate the transcription file path based on input video path."""
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(
        INPUT_DIR,
        f"{base_name}_transcription.pkl"
    )


def load_existing_transcription(transcription_path: str):
    """Load existing transcription if it exists."""

    if os.path.exists(transcription_path):
        print(f"Found existing transcription: {transcription_path}")

        try:
            with open(transcription_path, "rb") as f:
                transcription = pickle.load(f)

            print("Successfully loaded existing transcription!")
            return transcription

        except Exception as e:
            print(f"Error loading existing transcription: {e}")
            return None

    return None


def save_transcription(transcription, transcription_path: str):
    """Save transcription to file."""

    try:
        with open(transcription_path, "wb") as f:
            pickle.dump(transcription, f)

        print(f"Transcription saved to: {transcription_path}")

    except Exception as e:
        print(f"Error saving transcription: {e}")


def ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format."""

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds % 1) * 100)

    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centisecs:02d}"


def safe_filename(s: str) -> str:
    """Remove characters not allowed in filenames, but keep spaces, punctuation, and emojis."""

    safe_chars = string.ascii_letters + string.digits + " -_."
    safe_chars += "!?,:;@#$%^&+=[]{}"

    emoji_chars = (
        "".join(chr(i) for i in range(0x1F600, 0x1F64F))
        + "".join(chr(i) for i in range(0x1F300, 0x1F5FF))
        + "".join(chr(i) for i in range(0x1F900, 0x1F9FF))
        + "".join(chr(i) for i in range(0x1FA70, 0x1FAFF))
    )

    valid_chars = safe_chars + emoji_chars

    return "".join(c for c in s if c in valid_chars)


def safe_get(d: Any, key: Any, default: Any = None, validator=None) -> Any:
    """Safely get a value from a dict with optional type/range validation."""
    if not isinstance(d, dict):
        return default
    val = d.get(key, default)
    if val is None:
        return default
    if validator is not None:
        try:
            if not validator(val):
                return default
        except Exception:
            return default
    return val


def clamp_score(val: Any, lo: float = 0.0, hi: float = 10.0, default: float = 5.0) -> float:
    """Clamp a numeric AI score to [lo, hi], returning default on non-numeric."""
    try:
        v = float(val)
        if v < lo or v > hi:
            return max(lo, min(hi, v))
        return v
    except (TypeError, ValueError):
        return default


def sanitize_ai_json_response(raw: str) -> Any:
    """Strip markdown fences / extra text from AI response and parse JSON.

    Returns parsed dict/list on success; None on unrecoverable failure.
    """
    if not raw:
        return None

    text = raw.strip()
    # Qwen3 "thinking" models wrap chain-of-thought in <think> tags.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        candidate = text

    parser = json.JSONDecoder()
    attempts = []

    first_brace = candidate.find("{")
    first_bracket = candidate.find("[")
    if first_brace != -1:
        attempts.append(candidate[first_brace:])
    if first_bracket != -1:
        attempts.append(candidate[first_bracket:])
    if not attempts:
        attempts.append(candidate)

    last_brace = candidate.rfind("}")
    last_bracket = candidate.rfind("]")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        attempts.append(candidate[first_brace : last_brace + 1])
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        attempts.append(candidate[first_bracket : last_bracket + 1])

    for attempt in attempts:
        a = attempt.strip()
        if not a:
            continue
        try:
            parsed, _ = parser.raw_decode(a)
            if parsed is not None:
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    try:
        return json.loads(candidate)
    except Exception:
        return None


def resolve_ffmpeg_binaries() -> Tuple[str, str]:
    """Locate ffmpeg/ffprobe. Prefer PATH, then project-local tools/, then common folders.

    Never forces CPU/CUDA. Video encode is FFmpeg's job; AI runs in Ollama.
    """
    names = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
    found = {"ffmpeg": None, "ffprobe": None}

    def consider(directory: str) -> None:
        if not directory or not os.path.isdir(directory):
            return
        for key, fname in (("ffmpeg", names[0]), ("ffprobe", names[1])):
            if found[key]:
                continue
            candidate = os.path.join(directory, fname)
            if os.path.isfile(candidate):
                found[key] = candidate

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        consider(d)

    here = os.path.abspath(os.path.dirname(__file__)) if "__file__" in globals() else os.getcwd()
    search_roots = [
        os.path.join(here, "tools", "ffmpeg"),
        os.path.join(here, "tools"),
        os.path.join(os.getcwd(), "tools", "ffmpeg"),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
    ]
    extra_bins = []
    for root in search_roots:
        if os.path.isdir(root):
            extra_bins.append(root)
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    if "ffmpeg.exe" in filenames or "ffmpeg" in filenames:
                        extra_bins.append(dirpath)
                        break
            except OSError:
                pass
    for d in extra_bins:
        consider(d)

    ffmpeg = found["ffmpeg"] or "ffmpeg"
    ffprobe = found["ffprobe"] or "ffprobe"
    ffmpeg_dir = os.path.dirname(ffmpeg) if os.path.isabs(ffmpeg) else ""
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg, ffprobe


FFMPEG_BIN, FFPROBE_BIN = resolve_ffmpeg_binaries()


def get_ffmpeg_path() -> str:
    """Compatibility helper used by branding/post-render code."""
    return FFMPEG_BIN


def ffmpeg_ass_filter(ass_path: str) -> str:
    """Build a Windows-safe FFmpeg ass= filter. Never use raw backslashes in f-strings."""
    ass_abs = os.path.abspath(ass_path).replace("\\", "/")
    fonts_abs = os.path.abspath(FONT_DIR).replace("\\", "/")
    ass_esc = ass_abs.replace(":", "\\:")
    fonts_esc = fonts_abs.replace(":", "\\:")
    return "ass='" + ass_esc + "':fontsdir='" + fonts_esc + "'"


def call_ollama(
    messages: List[Dict[str, str]],
    task_name: str = "general",
    format_json: bool = False,
    timeout: Optional[int] = None,
    max_retries: int = 1,
) -> Optional[str]:
    """Call local Ollama chat API with qwen3:8b.

    Returns raw content string on success, None on total failure.
    Does not raise exceptions.
    """
    if timeout is None:
        timeout = OLLAMA_TIMEOUT

    payload: Dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
        },
    }
    if format_json:
        payload["format"] = "json"

    data_bytes = json.dumps(payload).encode("utf-8")

    for attempt in range(max_retries + 1):
        t0 = time.time()
        tag = "" if attempt == 0 else f" (retry {attempt}/{max_retries})"
        print(f"[Ollama] Calling {OLLAMA_MODEL} [{task_name}]{tag}...")
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                content = parsed.get("message", {}).get("content", "")
                dur = time.time() - t0
                content_preview = (
                    content[:120].replace("\n", " ") if isinstance(content, str) else ""
                )
                try:
                    print(
                        f"[Ollama] OK [{task_name}] ({dur:.1f}s) "
                        f"preview: {content_preview}{'...' if len(content) > 120 else ''}"
                    )
                except UnicodeEncodeError:
                    print(f"[Ollama] OK [{task_name}] ({dur:.1f}s)")
                return content
        except urllib.error.URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            print(f"[Ollama] Connection error [{task_name}]: {reason}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            print(
                f"[Ollama] HTTP error [{task_name}]: status={e.code} body={body}"
            )
        except json.JSONDecodeError as e:
            print(f"[Ollama] Malformed JSON response [{task_name}]: {e}")
        except Exception as e:  # noqa: BLE001 - must not crash
            print(f"[Ollama] Unexpected error [{task_name}]: {type(e).__name__}: {e}")

        if attempt < max_retries:
            print(f"[Ollama] Sleeping 2s before retry...")
            time.sleep(2)

    print(f"[Ollama] FAILED [{task_name}] after {max_retries + 1} attempt(s). Will use fallback.")
    return None


def normalize_path_for_ffmpeg(p: str) -> str:
    """Normalize Windows path to forward-slash form safe for FFmpeg filter paths."""
    return os.path.abspath(p).replace("\\", "/")


def cleanup_temp_files(paths: List[str]) -> None:
    """Best-effort cleanup of temporary files. Never raises."""
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception as e:  # noqa: BLE001
            print(f"[Warn] Could not remove temp file {p}: {e}")


def get_font_path(font_name: str) -> str:
    """Get the path to a font file in the font directory."""

    for ext in [".ttf", ".otf", ".TTF", ".OTF"]:

        font_path = os.path.join(
            FONT_DIR,
            f"{font_name}{ext}"
        )

        if os.path.exists(font_path):
            return font_path

    return os.path.join(
        FONT_DIR,
        font_name
    )


def _load_whisperx_alignment_resource(resource, loader=None, data_find=None, tokenizer_factory=None):
    """Load WhisperX's Punkt resource across old and new NLTK cache layouts.

    The pinned WhisperX alignment code requests ``punkt_tab/<language>.pickle``,
    while current NLTK releases store the same tables in a language directory.
    Use that directory only when the exact legacy lookup is absent; other
    resource failures remain visible to the caller.
    """
    if loader is None:
        from nltk.data import load as loader

    try:
        return loader(resource)
    except LookupError:
        match = re.fullmatch(r"tokenizers/punkt_tab/([A-Za-z0-9_-]+)\.pickle", str(resource))
        if not match:
            raise

        language = match.group(1)
        if data_find is None:
            from nltk.data import find as data_find
        try:
            data_find(f"tokenizers/punkt_tab/{language}/")
        except LookupError:
            raise

        if tokenizer_factory is None:
            from nltk.tokenize.punkt import PunktTokenizer
            tokenizer_factory = PunktTokenizer
        return tokenizer_factory(language)


def transcribe_with_progress(audio_file_path, transcriber):
    """Transcribe with progress tracking and safely handle a ClipsAI/WhisperX alignment edge case."""
    print("Transcribing video...")

    try:
        probe_cmd = [
            FFPROBE_BIN, "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", audio_file_path,
        ]
        duration = float(_check_output_hidden(probe_cmd, stderr=subprocess.DEVNULL).decode().strip())
        print(f"Video duration: {duration:.2f} seconds")
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        duration = 0
        print(f"Could not determine video duration for progress tracking: {e}")

    def progress_callback(current_time):
        if duration > 0:
            progress = (current_time / duration) * 100
            print(f"Transcription progress: {progress:.1f}% ({current_time:.1f}s / {duration:.1f}s)")
        else:
            print(f"Transcription progress: {current_time:.1f}s processed")

    print("Starting transcription (progress updates may be limited)...")

    # ClipsAI's Transcriber.transcribe() assumes aligned_transcription["segments"][0]["chars"][0]
    # exists and removes that first character. WhisperX can occasionally return a malformed
    # leading segment with chars=[], causing: IndexError: list assignment index out of range.
    # Patch whisperx.align only during this call so ClipsAI's normal Transcription construction,
    # word timestamps, and caption pipeline remain intact.
    original_align = None
    alignment_module = None
    original_nltk_load = None
    try:
        import whisperx
        import whisperx.alignment as alignment_module
        original_align = whisperx.align
        original_nltk_load = alignment_module.nltk_load

        def compatible_nltk_load(resource):
            return _load_whisperx_alignment_resource(resource, loader=original_nltk_load)

        alignment_module.nltk_load = compatible_nltk_load

        def safe_align(*args, **kwargs):
            aligned = original_align(*args, **kwargs)
            if not isinstance(aligned, dict):
                return aligned

            segments = aligned.get("segments")
            if not isinstance(segments, list) or not segments:
                raise RuntimeError("WhisperX alignment returned no segments.")

            first_valid_index = None
            for index, segment in enumerate(segments):
                if isinstance(segment, dict) and isinstance(segment.get("chars"), list) and segment.get("chars"):
                    first_valid_index = index
                    break

            if first_valid_index is None:
                raise RuntimeError("WhisperX alignment returned no usable character timestamps.")

            # Drop only malformed leading alignment segments. The failed run's repeated-B segment
            # is exactly this case; valid speech segments are retained.
            if first_valid_index > 0:
                skipped = first_valid_index
                aligned["segments"] = segments[first_valid_index:]
                print(f"  [Transcribe] WhisperX skipped {skipped} malformed leading alignment segment(s).")
            else:
                aligned["segments"] = segments

            first_segment = aligned["segments"][0]
            first_chars = first_segment.get("chars")
            if not isinstance(first_chars, list):
                first_chars = []
                first_segment["chars"] = first_chars

            # ClipsAI blindly deletes chars[0], expecting a leading space. If WhisperX's first
            # real character is not a space, insert a synthetic zero-duration space so no real
            # transcript character is lost.
            first_char_value = ""
            if first_chars and isinstance(first_chars[0], dict):
                first_char_value = str(first_chars[0].get("char", ""))

            if first_char_value != " ":
                try:
                    if first_chars and isinstance(first_chars[0], dict):
                        first_start = float(first_chars[0].get("start", 0.0) or 0.0)
                    else:
                        first_start = float(first_segment.get("start", 0.0) or 0.0)
                except Exception:
                    first_start = 0.0
                first_chars.insert(0, {"char": " ", "start": first_start, "end": first_start})

            return aligned

        whisperx.align = safe_align
        transcription = transcriber.transcribe(
            audio_file_path=audio_file_path,
            iso6391_lang_code="en",
        )
    finally:
        if original_align is not None:
            try:
                whisperx.align = original_align
            except Exception:
                pass
        if alignment_module is not None and original_nltk_load is not None:
            try:
                alignment_module.nltk_load = original_nltk_load
            except Exception:
                pass

    print("Transcription completed!")
    return transcription


class ResourceManager:
    """Hardware-aware resource management for video processing.

    Detects available VRAM / RAM at startup and provides safe batch sizes
    and an OOM-retry wrapper.  A single module-level instance (RESOURCE_MANAGER)
    is used throughout the pipeline so detection only runs once.
    """

    def __init__(self) -> None:
        self.vram_gb: float = self._detect_vram()
        self.ram_gb: float = self._detect_ram()
        self.cuda_available: bool = self._check_cuda()

    def _detect_vram(self) -> float:
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.get_device_properties(0).total_memory / 1e9
        except Exception:
            pass
        return 0.0

    def _detect_ram(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().total / 1e9
        except Exception:
            return 8.0  # safe default

    def _check_cuda(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def recommended_batch_size(self, frame_w: int = 960, frame_h: int = 540) -> int:
        """Return a safe MTCNN batch size for the detected hardware.

        Each PIL frame at detection scale costs roughly w*h*3 bytes in CPU
        memory and a comparable amount in VRAM when MTCNN runs on CUDA.
        We target ≤60 % VRAM usage, capped at 16 for safety on 8 GB cards.
        """
        frame_mb = max(1.0, (frame_w * frame_h * 3) / 1e6)

        if self.cuda_available and self.vram_gb > 0:
            # Whisper already occupies ~1.5–3 GB; leave the rest for MTCNN.
            reserved_for_whisper_gb = 3.0
            usable_mb = max(256.0, (self.vram_gb - reserved_for_whisper_gb) * 1000 * 0.60)
            batch = max(1, int(usable_mb / frame_mb))
            # Hard ceiling: 8 GB RTX 4060 → 8 or fewer after Whisper headroom
            return min(batch, 8 if self.vram_gb < 10 else 16)
        else:
            # CPU path: conservatively use 30 % of RAM
            usable_mb = self.ram_gb * 1000 * 0.30
            return max(1, min(int(usable_mb / frame_mb), 4))

    def process_with_retry(self, fn, *args, **kwargs):
        """Run *fn* with automatic batch-size reduction on CUDA OOM."""
        batch_key = "batch_size"
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except RuntimeError as exc:
                if "out of memory" in str(exc).lower() and attempt < 2:
                    if batch_key in kwargs:
                        kwargs[batch_key] = max(1, kwargs[batch_key] // 2)
                        print(
                            f"  [ResourceManager] CUDA OOM — retrying with "
                            f"batch_size={kwargs[batch_key]}"
                        )
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    continue
                raise

    def whisperx_compute_params(self) -> dict:
        """Return the WhisperX compute_type / device best suited for this GPU.

        RTX 4060 (8 GB) can run large-v3 in float16, but if VRAM is tighter
        (e.g. another model is already loaded) int8 on CUDA is a safe fallback.
        On CPU we always use int8.
        """
        if self.cuda_available:
            if self.vram_gb >= 6:
                return {"device": "cuda", "compute_type": "float16"}
            elif self.vram_gb >= 3:
                return {"device": "cuda", "compute_type": "int8"}
        return {"device": "cpu", "compute_type": "int8"}

    def release_gpu_memory(self) -> None:
        """Best-effort CUDA cache flush between pipeline stages."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


# Module-level singleton — constructed lazily on first pipeline run so that
# --help works without an ML runtime installed.
RESOURCE_MANAGER: Optional["ResourceManager"] = None


def _get_resource_manager() -> "ResourceManager":
    global RESOURCE_MANAGER
    if RESOURCE_MANAGER is None:
        RESOURCE_MANAGER = ResourceManager()
        print(
            f"  [ResourceManager] VRAM={RESOURCE_MANAGER.vram_gb:.1f} GB  "
            f"RAM={RESOURCE_MANAGER.ram_gb:.1f} GB  "
            f"CUDA={RESOURCE_MANAGER.cuda_available}  "
            f"recommended_mtcnn_batch={RESOURCE_MANAGER.recommended_batch_size()}"
        )
    return RESOURCE_MANAGER


def create_transcriber(model_size: str) -> "Transcriber":
    """Create ClipsAI's transcriber with a VAD backend that works on Windows CPU installs.

    ClipsAI currently lets WhisperX default to Pyannote. Newer Pyannote releases
    route audio through TorchCodec, which fails here when the installed FFmpeg
    major version is outside TorchCodec's supported range. Silero uses WhisperX's
    in-memory audio path and avoids that native decoder dependency.

    The WhisperX model is loaded with a compute_type appropriate for the detected
    GPU (float16 on CUDA with ≥6 GB VRAM, int8 otherwise) to avoid OOM on 8 GB
    cards such as the RTX 4060.
    """
    import whisperx

    rm = _get_resource_manager()
    compute_params = rm.whisperx_compute_params()

    original_load_model = whisperx.load_model

    def load_model_with_silero(*args, **kwargs):
        kwargs.setdefault("vad_method", os.getenv("WHISPERX_VAD_METHOD", "silero"))
        # Apply hardware-aware compute settings; env vars can still override.
        kwargs.setdefault("device", compute_params["device"])
        kwargs.setdefault("compute_type", compute_params["compute_type"])
        print(
            f"  [WhisperX] Loading model '{model_size}' on "
            f"{kwargs['device']} with compute_type={kwargs['compute_type']} …"
        )
        return original_load_model(*args, **kwargs)

    whisperx.load_model = load_model_with_silero
    try:
        from clipsai import Transcriber

        return Transcriber(model_size=model_size)
    finally:
        whisperx.load_model = original_load_model


def _is_important_word(word: str) -> bool:
    """Heuristic: should this word be highlighted yellow in captions?"""
    w = word.strip()
    if not w:
        return False
    stripped = w.strip(string.punctuation)
    lower = stripped.lower()
    if any(c.isdigit() for c in w):
        return True
    if any(sym in w for sym in ("$", "£", "€", "¥", "%", "#", "!", "?")):
        return True
    if len(stripped) >= 5 and stripped.isupper() and any(c.isalpha() for c in stripped):
        return True
    if lower in IMPORTANT_WORDS_HIGHLIGHT:
        return True
    return False


def _ass_encode_text(text: str) -> str:
    """Escape ASS special characters in plain dialogue text."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\n", "\\N")
    return text


def _group_words_into_beats(word_info_local: List[Dict]) -> List[List[Dict]]:
    """Group clip-local word_info entries into 2-5 word beats.

    Each beat is a list of word_info dicts with local (clip-relative) start/end.
    """
    beats: List[List[Dict]] = []
    current: List[Dict] = []
    last_end: Optional[float] = None
    for w in word_info_local:
        ws = float(w["start_time"])
        we = float(w["end_time"])
        start_new = False
        if not current:
            start_new = True
        elif len(current) >= 5:
            start_new = True
        elif last_end is not None and (ws - last_end) >= 0.45:
            start_new = True
        else:
            # End-of-sentence cues: word ends with .!? or closing quote
            tail = w["word"].rstrip()
            if tail and tail[-1] in ".!?\"'":
                # Add this word first then start new beat
                current.append(w)
                beats.append(current)
                current = []
                last_end = we
                continue
        if start_new and current:
            beats.append(current)
            current = []
        current.append(w)
        last_end = we
    if current:
        beats.append(current)
    return beats


def _dialogue_line(start: str, end: str, style: str, layer: int, text: str) -> str:
    return f"Dialogue: {layer},{start},{end},{style},,0,0,0,,{text}\n"


def resolve_caption_font_name(requested: str) -> str:
    """Return a safe ASS font family name. Prefer the requested installed font."""
    requested = (requested or "Montserrat Extra Bold").strip()
    allowed = {
        "Montserrat Extra Bold", "Arial", "Arial Black", "Segoe UI",
        "Segoe UI Black", "Impact", "Tahoma", "Trebuchet MS", "Verdana",
        "Calibri", "Aptos", "Comic Sans MS", "Georgia",
    }
    if requested in allowed:
        return requested
    return "Montserrat Extra Bold"


def _caption_font_candidates(font_name: str) -> List[str]:
    names = [font_name]
    aliases = {
        "Montserrat Extra Bold": ["Montserrat-ExtraBold.ttf", "Montserrat Extra Bold.otf"],
        "Arial Black": ["ariblk.ttf"],
        "Arial": ["arial.ttf"],
        "Segoe UI": ["segoeui.ttf"],
        "Segoe UI Black": ["seguibl.ttf"],
        "Impact": ["impact.ttf"],
        "Tahoma": ["tahoma.ttf"],
        "Trebuchet MS": ["trebuc.ttf"],
        "Verdana": ["verdana.ttf"],
        "Calibri": ["calibri.ttf"],
        "Aptos": ["Aptos.ttf"],
        "Comic Sans MS": ["comic.ttf"],
        "Georgia": ["georgia.ttf"],
    }
    roots = [FONT_DIR, os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    out = []
    for root in roots:
        for name in names:
            out.append(os.path.join(root, name + ".ttf"))
            out.append(os.path.join(root, name + ".otf"))
        for alias in aliases.get(font_name, []):
            out.append(os.path.join(root, alias))
    return out


def _caption_font_path() -> str:
    """Resolve the selected caption font for PIL width measurement."""
    font_name = resolve_caption_font_name(CAPTION_FONT)
    for path in _caption_font_candidates(font_name):
        if os.path.isfile(path):
            return path
    # Known Montserrat file names are common in this project.
    for path in _caption_font_candidates("Montserrat Extra Bold"):
        if os.path.isfile(path):
            return path
    return ""

def _measure_caption_text(text: str, font_size: int = 78) -> float:
    """Measure text width in pixels; use a conservative fallback if PIL/font is unavailable."""
    if not text:
        return 0.0
    if ImageFont is not None:
        try:
            fp = _caption_font_path()
            if fp:
                font = ImageFont.truetype(fp, font_size)
                box = font.getbbox(text)
                return float(box[2] - box[0])
        except Exception:
            pass
    # Conservative approximation: bold captions average about 0.55em per character.
    return len(text) * font_size * 0.55


def _wrap_caption_words(words: List[Dict], max_width: int = 900, font_size: int = 78) -> List[List[Dict]]:
    """Split a 2-5 word beat into at most two balanced lines by rendered width."""
    if not words:
        return []
    if len(words) <= 1:
        return [words]

    def width(group: List[Dict]) -> float:
        return _measure_caption_text(" ".join(str(w.get("word", "")).strip() for w in group), font_size)

    whole = width(words)
    if whole <= max_width:
        return [words]

    # Find the split with the most balanced two line widths while keeping both lines readable.
    best = None
    for cut in range(1, len(words)):
        left, right = words[:cut], words[cut:]
        lw, rw = width(left), width(right)
        if lw > max_width or rw > max_width:
            continue
        balance = abs(lw - rw)
        score = balance + (0 if 2 <= len(left) <= 3 else 30)
        if best is None or score < best[0]:
            best = (score, left, right)
    if best is not None:
        return [best[1], best[2]]

    # Rare fallback: split long words across the beat, never producing 3+ lines.
    mid = max(1, len(words) // 2)
    return [words[:mid], words[mid:]]


def _caption_line_text(words: List[Dict], active_idx: Optional[int] = None) -> str:
    """Build one ASS caption line with stable layout and no duplicate overlays."""
    parts = []
    for i, w in enumerate(words):
        raw = _ass_encode_text(str(w.get("word", "")).strip())
        if not raw:
            continue
        important = _is_important_word(str(w.get("word", "")))
        if i == active_idx:
            # Active word: yellow + slightly stronger outline. No scaling, so it cannot overlap neighbours.
            parts.append("{\\c&H00FFFF&\\3c&H000000&\\bord4}" + raw + "{\\rBase}")
        elif important:
            parts.append("{\\c&H00FFFF&}" + raw + "{\\rBase}")
        else:
            parts.append(raw)
    return " ".join(parts)


def create_animated_subtitles(video_path, transcription, clip, output_path):
    """Burn word-level Shorts captions into the video and fail loudly if rendering fails."""
    print(f"[Captions] Building dynamic captions (font={resolve_caption_font_name(CAPTION_FONT)})...")
    word_info_raw = transcription.get_word_info() if transcription is not None else []
    clip_words_local: List[Dict] = []
    for w in word_info_raw or []:
        try:
            ws = float(w.get("start_time") or 0.0)
            we = float(w.get("end_time") or ws)
        except Exception:
            continue
        if we < clip.start_time:
            continue
        if ws > clip.end_time:
            break
        word = str(w.get("word", "")).strip()
        if not word:
            continue
        clip_words_local.append({
            "word": word,
            "start_time": max(0.0, ws - clip.start_time),
            "end_time": max(0.05, we - clip.start_time),
        })

    # WhisperX/ClipsAI can occasionally expose segment timestamps without word timestamps.
    # In that case, create evenly distributed word timings inside each segment so captions
    # are still burned into the Short rather than silently returning a plain video.
    if not clip_words_local:
        try:
            segments = transcription.get_segments() if transcription is not None else []
        except Exception:
            segments = []
        for seg in segments or []:
            try:
                ss = float(seg.get("start", seg.get("start_time", 0.0)))
                ee = float(seg.get("end", seg.get("end_time", ss)))
            except Exception:
                continue
            if ee < clip.start_time or ss > clip.end_time:
                continue
            text = str(seg.get("text", "")).strip()
            words = [x for x in text.split() if x]
            if not words:
                continue
            a = max(0.0, ss - clip.start_time)
            b = min(float(clip.end_time - clip.start_time), ee - clip.start_time)
            if b <= a:
                continue
            step = max(0.05, (b - a) / len(words))
            for i, word in enumerate(words):
                clip_words_local.append({
                    "word": word,
                    "start_time": a + i * step,
                    "end_time": min(b, a + (i + 1) * step),
                })
        clip_words_local.sort(key=lambda x: (x["start_time"], x["end_time"]))

    if not clip_words_local:
        raise RuntimeError("No usable transcript timing is available for captions.")

    beats = _group_words_into_beats(clip_words_local)
    font_name = resolve_caption_font_name(CAPTION_FONT)
    font_size = max(48, min(110, CAPTION_FONT_SIZE))
    print(f"  [Captions] {len(clip_words_local)} words -> {len(beats)} beats; font={font_name}, size={font_size}")

    ass_file = os.path.abspath(os.path.join(OUTPUT_DIR, "temp_subtitles.ass"))
    final_output = os.path.abspath(output_path.replace(".mp4", "_with_subtitles.mp4"))
    style_header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Base,{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,70,70,300,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    try:
        with open(ass_file, "w", encoding="utf-8-sig") as f:
            f.write(style_header)
            for beat in beats:
                lines = _wrap_caption_words(beat, max_width=900, font_size=font_size)
                beat_start = max(0.0, float(beat[0]["start_time"]))
                beat_end = max(beat_start + 0.12, float(beat[-1]["end_time"]))
                for active_idx, active_word in enumerate(beat):
                    start = max(beat_start, float(active_word["start_time"]))
                    end = beat_end if active_idx == len(beat) - 1 else min(beat_end, float(beat[active_idx + 1]["start_time"]))
                    if end <= start:
                        continue
                    line_texts = []
                    for line in lines:
                        local_active = next((i for i, item in enumerate(line) if item is active_word), None)
                        line_texts.append(_caption_line_text(line, local_active))
                    text = "\\N".join(line_texts)
                    f.write(_dialogue_line(ass_time(start), ass_time(end), "Base", 0, text))

        if not os.path.isfile(ass_file) or os.path.getsize(ass_file) < 200:
            raise RuntimeError("Caption ASS file was not created correctly.")

        cmd = [
            FFMPEG_BIN, "-hide_banner", "-y", "-i", video_path,
            "-map", "0:v:0", "-map", "0:a?", "-vf", ffmpeg_ass_filter(ass_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", final_output,
        ]
        print("  [Captions] Burning ASS captions with FFmpeg...")
        result = _run_hidden(cmd, check=False, capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-20:]
            raise RuntimeError("FFmpeg caption render failed: " + " | ".join(tail)[-3000:])
        if not os.path.isfile(final_output) or os.path.getsize(final_output) < 1024:
            raise RuntimeError("FFmpeg reported success but captioned output is missing/empty.")
        print(f"  [Captions] SUCCESS → {final_output}")
        return final_output
    except Exception:
        # Do not silently return the uncaptioned video. The caller will mark this Short failed.
        print("  [Captions] FAILED; refusing to publish an uncaptioned Short.")
        raise


# ============================================================
# LOCAL AI TITLE GENERATION (Ollama/qwen3:8b)
# ============================================================

EMOJI_RANGE = (
    list(range(0x1F600, 0x1F64F))
    + list(range(0x1F300, 0x1F5FF))
    + list(range(0x1F900, 0x1F9FF))
    + list(range(0x1FA70, 0x1FAFF))
    + list(range(0x2600, 0x27BF))
    + list(range(0x1F1E6, 0x1F1FF))
)


def _count_emojis(title: str) -> int:
    return sum(1 for ch in title if ord(ch) in EMOJI_RANGE)


def _clean_title(raw: str) -> Optional[str]:
    """Validate and clean an AI-generated title to the rules:
    max 7 words, max 1 emoji, no hashtags, no quotes.
    Returns None if invalid even after cleaning.
    """
    if not raw:
        return None
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    # Take first non-empty line that isn't a label prefix
    title = None
    for ln in lines:
        low = ln.lower()
        if low.startswith("title:"):
            ln = ln[6:].strip()
        if low.startswith('"') and low.endswith('"'):
            ln = ln[1:-1]
        if ln:
            title = ln
            break
    if not title:
        return None
    # Strip outer quotes / hashtags / explanation
    title = title.strip(" \t\"'`")
    # Remove hashtag tokens
    title = re.sub(r"#\S+", "", title).strip()
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None
    # Word count (split on whitespace)
    # Exclude emojis that are standalone tokens toward the word count -- actually count them.
    words = title.split(" ")
    if len(words) > 7:
        # Truncate to 7 words
        title = " ".join(words[:7]).strip()
        # Re-append trailing emoji if it got separated? Not needed - too complex.
    emoji_count = _count_emojis(title)
    if emoji_count > 1:
        # Keep first emoji, strip others
        first_idx = None
        for i, ch in enumerate(title):
            if ord(ch) in EMOJI_RANGE:
                first_idx = i
                break
        if first_idx is not None:
            kept_emoji = title[first_idx]
            cleaned_chars = [c for c in title if ord(c) not in EMOJI_RANGE]
            new_title = "".join(cleaned_chars).rstrip()
            title = (new_title + " " + kept_emoji).strip()
    # Drop leading punctuation-only words if weird
    title = title.strip(" ,;:.-_")
    if len(title) < 3:
        return None
    return title


def get_viral_title_locally(clip_text: str) -> str:
    """Generate a Shorts title using local Ollama/qwen3:8b.

    Falls back to a reasonable default if AI is unavailable.
    """
    fallback_titles = [
        "You Won't Believe This 😮",
        "Wait For It... 😳",
        "This Is Wild 🤯",
        "Unbelievable Moment 😱",
        "The Ending Shocked Me 😵",
    ]
    # Don't send huge clip text
    text = clip_text.strip()
    if len(text) > 1500:
        text = text[:1500] + " ..."

    sys_msg = (
        "You write YouTube Shorts titles. Rules:\n"
        "- Max 7 words total\n"
        "- Exactly 1 emoji (prefer 😱 🤯 😳 🔥 💸 😮)\n"
        "- No hashtags, no quotes, no explanation\n"
        "- Curiosity-driven, natural English\n"
        "- Mention the specific subject/event from the clip; never use generic titles like Unbelievable Moment\n"
        "- Relevant to the actual clip content\n"
        f"- Match the selected editing mode: {EDIT_MODE}\n"
        "- Do NOT exaggerate beyond what the transcript says\n"
        "- Output ONLY JSON: {\"title\": \"Your Title Here 😳\"}\n"
    )
    user_msg = "Transcript excerpt:\n" + text + "\n\nOutput JSON now."
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]
    raw = call_ollama(messages, task_name="title_gen", format_json=True, max_retries=1)
    if raw:
        parsed = sanitize_ai_json_response(raw)
        if isinstance(parsed, dict):
            candidate = safe_get(parsed, "title", "", validator=lambda v: isinstance(v, str))
            cleaned = _clean_title(str(candidate))
            if cleaned:
                print(f"  [Title] AI: {cleaned}")
                return cleaned
        # Sometimes model returns freeform despite JSON request; try as freeform
        cleaned = _clean_title(raw)
        if cleaned:
            print(f"  [Title] AI (freeform): {cleaned}")
            return cleaned

    # Last-resort fallback: deterministic
    title = fallback_titles[int(time.time()) % len(fallback_titles)]
    try:
        print(f"  [Title] Fallback (AI unavailable): {title}")
    except UnicodeEncodeError:
        print("  [Title] Fallback (AI unavailable)")
    return title


def get_viral_title(
    transcript_text,
    groq_api_key,
):
    """Legacy Groq title generator. Kept as a last-resort option if Ollama fails."""
    print("  [Title] Attempting legacy Groq path...")
    import requests

    examples = [
        "She was almost dead 😵",
        "He made $1,000,000 in 1 hour 💸",
        "This changed everything... 😲",
        "They couldn't believe what happened! 😱",
        "He risked it all for this 😬",
    ]

    prompt = (
        "Given the following transcript, generate "
        "a catchy, viral YouTube Shorts title "
        "(max 7 words). "
        "ALWAYS include an emoji in the title. "
        "ONLY output the title, nothing else. "
        "Do NOT use hashtags. "
        "Do NOT explain. "
        "Do NOT repeat the prompt. "
        "Do NOT add quotes. "
        "The title should be in the style of "
        "these examples: "
        + ", ".join(examples)
        + ".\n\nTranscript:\n"
        + transcript_text[:2000]
    )

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": 40,
        "temperature": 0.7,
        "top_p": 0.9,
    }

    try:
        default_key = "your_groq_api_key_here"
        if not groq_api_key or groq_api_key == default_key:
            print("  [Title] Groq key not configured.")
            return "Untitled Clip"

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30,
        )

        response.raise_for_status()

        result = response.json()

        content = (
            result["choices"][0]["message"]["content"]
        )

        cleaned = _clean_title(content)
        if cleaned:
            print(f"  [Title] Groq: {cleaned}")
            return cleaned

        return "Untitled Clip"

    except requests.exceptions.HTTPError as e:
        print(f"  [Title] Groq HTTP error: {e}")
        return "Untitled Clip"

    except Exception as e:
        print(f"  [Title] Groq unexpected error: {e}")
        return "Untitled Clip"



def _fallback_hashtags(text: str, mode: str = "viral") -> list[str]:
    """Create conservative hashtags without inventing specific people/topics."""
    base = ["#shorts", "#youtubeShorts", "#clips"]
    low = text.lower()
    if any(x in low for x in ("podcast", "interview", "host", "guest")):
        base.append("#podcast")
    mode_tag = {
        "funny": "#funny", "dramatic": "#story", "educational": "#education",
        "meme": "#meme", "story": "#story", "viral": "#viral",
    }.get(str(mode).lower())
    if mode_tag:
        base.append(mode_tag)
    return list(dict.fromkeys(base))[:8]


def _fallback_tags(text: str) -> list[str]:
    """Extract a small set of useful plain-text tags from transcript words."""
    stop = {
        "this","that","with","have","from","they","them","what","when","where",
        "would","could","should","there","their","about","really","just","like",
        "you","your","into","were","been","will","than","then","because","very",
        "also","some","more","only","know","think","said","say","yeah","okay",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", text.lower())
    counts: dict[str,int] = {}
    for w in words:
        w = w.strip("'-")
        if w in stop or len(w) < 4:
            continue
        counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [w for w, _ in ranked[:12]]


def _clean_metadata_list(value: Any, prefix: str = "", limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out=[]
    for item in value:
        if not isinstance(item, str):
            continue
        x=re.sub(r"\s+", " ", item.strip())
        if not x:
            continue
        if prefix and not x.startswith(prefix):
            x=prefix+x.lstrip("#")
        if x not in out:
            out.append(x)
        if len(out)>=limit:
            break
    return out


def generate_short_metadata_locally(clip_text: str, title: str) -> dict[str, Any]:
    """Generate the YouTube-facing description/hashtags/tags with local Ollama."""
    fallback_hash=_fallback_hashtags(clip_text, EDIT_MODE)
    fallback_tags=_fallback_tags(clip_text)
    result={
        "title": title,
        "description": clip_text[:280].strip(),
        "hashtags": fallback_hash,
        "tags": fallback_tags,
    }
    text=clip_text.strip()
    if len(text)>2200:
        text=text[:2200]+" ..."
    if not text:
        return result
    sys_msg=(
        "Create YouTube Shorts metadata from the transcript.\n"
        "Return ONLY JSON with keys: description, hashtags, tags.\n"
        "description: 1-3 natural sentences, accurate to the transcript, no fake claims.\n"
        "hashtags: 4-8 relevant hashtags, each beginning with #. Include #shorts.\n"
        "tags: 6-12 relevant YouTube search tags, plain phrases without #.\n"
        "Do not invent names, facts, events or context that is not supported by the transcript.\n"
    )
    raw=call_ollama([
        {"role":"system","content":sys_msg},
        {"role":"user","content":f"Title: {title}\nTranscript:\n{text}\n\nOutput JSON only."},
    ], task_name="metadata_gen", format_json=True, max_retries=1)
    if raw:
        parsed=sanitize_ai_json_response(raw)
        if isinstance(parsed,dict):
            desc=str(parsed.get("description","")).strip()
            hashtags=_clean_metadata_list(parsed.get("hashtags"), prefix="#", limit=8)
            tags=_clean_metadata_list(parsed.get("tags"), limit=12)
            if desc:
                result["description"]=desc[:1000]
            if hashtags:
                if "#shorts" not in [h.lower() for h in hashtags]:
                    hashtags.insert(0,"#shorts")
                result["hashtags"]=hashtags[:8]
            if tags:
                result["tags"]=tags[:12]
            print(f"  [Metadata] description + {len(result['hashtags'])} hashtags + {len(result['tags'])} tags")
    return result

# ============================================================
# AI CLIP ANALYSIS & RANKING (Ollama/Qwen3)
# ============================================================

IMPORTANT_WORDS_HIGHLIGHT = {
    "insane", "crazy", "wow", "never", "million", "billion", "thousand",
    "killed", "destroyed", "impossible", "ripped", "shocking", "unbelievable",
    "finally", "instantly", "suddenly", "secretly", "actually", "literally",
    "guaranteed", "free", "rich", "broke", "dead", "alive", "biggest",
    "smallest", "fastest", "worst", "best", "first", "last", "hundred",
    "profit", "lost", "win", "won", "failed", "disaster", "incredible",
    "amazing", "game", "changed", "secret", "truth", "lie", "exposed",
}


def words_for_clip(clip, transcription, padding_words: int = 0):
    """Return list of word_info dicts within clip, optionally with padding."""
    try:
        all_words = transcription.get_word_info()
    except Exception:
        return []
    if not all_words:
        return []
    # Find indices of first/last word within clip times
    start_idx = 0
    end_idx = len(all_words) - 1
    for i, w in enumerate(all_words):
        wt = w.get("start_time") or 0
        if wt >= clip.start_time:
            start_idx = i
            break
    for i in range(len(all_words) - 1, -1, -1):
        wt = all_words[i].get("end_time") or 0
        if wt <= clip.end_time:
            end_idx = i
            break
    lo = max(0, start_idx - padding_words)
    hi = min(len(all_words) - 1, end_idx + padding_words)
    return all_words[lo : hi + 1]


def transcript_text(words) -> str:
    """Join word list to plain text."""
    return " ".join(w.get("word", "") for w in words).strip()


def extract_candidate_transcript(cand_idx: int, clip, transcription, context_words: int = 4):
    """Return (snippet_text, words_inside) with context marked [CONTEXT...]."""
    inner = words_for_clip(clip, transcription, padding_words=0)
    if not inner:
        return "", []
    with_ctx = words_for_clip(clip, transcription, padding_words=context_words)
    inner_set_ids = set(id(w) for w in inner)
    # First pass: build text with context markers
    ctx_tokens = []
    in_inner = False
    prev_was_ctx = False
    for w in with_ctx:
        is_inner = id(w) in inner_set_ids
        if is_inner and not in_inner:
            if prev_was_ctx:
                ctx_tokens.append("[CONTEXT END]")
            ctx_tokens.append("[CLIP START]")
            in_inner = True
        elif not is_inner and in_inner:
            ctx_tokens.append("[CLIP END]")
            in_inner = False
            ctx_tokens.append("[CONTEXT START]")
            prev_was_ctx = True
        elif not is_inner and not in_inner and not prev_was_ctx:
            ctx_tokens.append("[CONTEXT START]")
            prev_was_ctx = True
        ctx_tokens.append(w.get("word", ""))
    if in_inner:
        ctx_tokens.append("[CLIP END]")
    elif prev_was_ctx:
        ctx_tokens.append("[CONTEXT END]")
    snippet = " ".join(t for t in ctx_tokens if t != "").strip()
    return snippet, inner


def build_clip_analysis_prompt(candidate_batch: List[Tuple[int, Clip, List[Dict], str]]):
    """Build a strict editorial-analysis prompt for Qwen3 8B."""
    sys_msg = """You are the final editorial brain for a YouTube Shorts generator.
Evaluate each candidate as an editor for the selected mode, using only the supplied clip.
Keep a candidate when it is a publishable, coherent moment with an identifiable hook and payoff; it need not be a perfect or exceptional viral hit.
A podcast or roast can have a complete payoff through setup, punchline or reveal, and the hosts' reaction; it does not need a conventional story arc.
Reject only when the clip is genuinely incoherent, needs essential missing context, has no meaningful moment or payoff, or ends before the thought resolves.
Moderate scores (around 5–6) are not an automatic rejection; judge whether the excerpt is useful in its selected format.
Penalize clips that jump between unrelated topics, need lots of missing context, start weakly, or end abruptly.
Score every dimension from 0 to 10:
- hook: first 1-3 seconds stop scrolling
- curiosity: creates a reason to keep watching
- emotion: strong human reaction, tension, humor, shock, awe, etc.
- surprise: unexpected reveal/outcome
- story: clear setup -> escalation -> resolution
- payoff: satisfying reveal/result/punchline
- pacing: energetic with little dead time
- standalone: understandable without the source video
- rewatch: likely to reward a second viewing
- conflict: stakes, challenge, competition, danger, disagreement
- coherence: one focused moment/topic from beginning to end

Do NOT reward generic phrases such as 'crazy', 'insane', or 'this is wild' by themselves.
The decision must agree with the scores and reason. The overall score must reflect the dimensions, not a random guess.
Return ONLY valid JSON in this exact shape:
{"candidates":[{"candidate_id":0,"decision":"keep","hook":8,"curiosity":7,"emotion":6,"surprise":8,"story":8,"payoff":9,"pacing":8,"standalone":8,"rewatch":7,"conflict":6,"coherence":9,"reason":"One focused discovery with a clear reveal and payoff."}]}
Use decision 'reject' when the candidate is fundamentally unsuitable. Keep reason under 18 words."""
    mode_guidance = {
        "viral": "Prioritize scroll-stopping hooks, curiosity, surprise, stakes, and a satisfying payoff. For podcast comedy, a clear punchline and reaction can provide that payoff without a full story arc.",
        "funny": "Prioritize genuine humor, punchlines, awkwardness, reactions, comedic timing, and unexpected moments. A setup, punchline, and reaction can be a complete moment without a conventional story arc. Do not call something funny merely because it says crazy or insane.",
        "dramatic": "Prioritize tension, danger, suspense, emotional escalation, reveals, and strong reactions.",
        "educational": "Prioritize useful explanations, surprising facts, clear teaching moments, and a self-contained takeaway.",
        "story": "Prioritize a complete mini-story with setup, escalation, turning point, and payoff.",
        "meme": "Prioritize absurd, chaotic, highly reactive, remixable moments with strong visual or comedic timing.",
        "gaming": "Prioritize clutch plays, reveals, accusations, reactions, fails, wins, losses, and moments that make sense with gameplay visuals. Favor self-contained moments with a clear setup and payoff.",
    }.get(EDIT_MODE, "Prioritize overall Shorts retention, coherence, and payoff.")
    sys_msg = sys_msg.replace(
        "Evaluate each candidate as an editor for the selected mode, using only the supplied clip.",
        "Evaluate each candidate as an editor for the selected mode, using only the supplied clip.\n"
        f"The selected editing mode is: {EDIT_MODE}. {mode_guidance}"
    )
    user_lines = ["Evaluate these candidate clips independently:"]
    for cid, clip, inner, snippet in candidate_batch:
        dur = clip.end_time - clip.start_time
        trimmed = snippet if len(snippet) <= 1700 else snippet[:1700] + " ...[truncated]"
        user_lines.append(f"\n--- candidate_id={cid} | duration={dur:.1f}s | words={len(inner)} ---\n{trimmed}")
    user_lines.append("\nReturn JSON only.")
    return [{"role":"system","content":sys_msg},{"role":"user","content":"".join(user_lines)}]


def _default_ai_scores() -> Dict[str, float]:
    return {
        "score": 0.0, "hook": 0.0, "curiosity": 0.0, "emotion": 0.0,
        "surprise": 0.0, "story": 0.0, "payoff": 0.0, "pacing": 0.0,
        "standalone": 0.0, "rewatch": 0.0, "conflict": 0.0, "coherence": 0.0,
        "reason": "", "decision": "reject", "ai_valid": False,
    }


def parse_ai_clip_scores(raw_content: str, expected_ids: List[int]) -> Dict[int, Dict[str, float]]:
    """Parse only genuinely returned/valid Qwen candidates; never pretend defaults are AI scores."""
    results: Dict[int, Dict[str, float]] = {}
    if not raw_content:
        return results
    parsed = sanitize_ai_json_response(raw_content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
        return results
    dims = ["hook","curiosity","emotion","surprise","story","payoff","pacing","standalone","rewatch","conflict","coherence"]
    for entry in parsed["candidates"]:
        if not isinstance(entry, dict):
            continue
        raw_cid = entry.get("candidate_id")
        if isinstance(raw_cid, bool) or not isinstance(raw_cid, int):
            continue
        cid = raw_cid
        if cid not in expected_ids:
            continue
        decision = str(entry.get("decision", "")).strip().lower()
        if decision not in {"keep", "reject"}:
            # A missing/unknown decision is malformed, never an implicit approval.
            continue
        dimensions: Dict[str, float] = {}
        valid_dimensions = True
        for dimension in dims:
            value = entry.get(dimension)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                valid_dimensions = False
                break
            number = float(value)
            if not math.isfinite(number) or number < 0.0 or number > 10.0:
                valid_dimensions = False
                break
            dimensions[dimension] = number
        if not valid_dimensions:
            continue
        score = _default_ai_scores()
        score.update(dimensions)
        score["decision"] = decision
        score["reason"] = str(entry.get("reason", ""))[:180]
        # Recompute the overall score from dimensions so Qwen cannot make the score arbitrary.
        weights = {
            "hook":0.15, "curiosity":0.11, "emotion":0.08, "surprise":0.09,
            "story":0.09, "payoff":0.14, "pacing":0.07, "standalone":0.08,
            "rewatch":0.05, "conflict":0.05, "coherence":0.09,
        }
        score["score"] = sum(score[k] * v for k,v in weights.items()) * 10.0
        score["ai_valid"] = True
        results[cid] = score
    return results


_QWEN_DIAGNOSTIC_SECRET_PATTERNS = (
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)([\"']?(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)[\"']?\s*[:=]\s*[\"']?)([^\"'\\s,;}]+)"),
)


def _redact_qwen_diagnostic_text(value: str) -> str:
    for pattern in _QWEN_DIAGNOSTIC_SECRET_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    return value


def _record_qwen_diagnostic(
    task_name: str,
    expected_ids: List[int],
    raw_content: Optional[str],
    parsed_scores: Dict[int, Dict[str, Any]],
    error: Optional[str] = None,
) -> None:
    """Persist bounded Qwen response evidence without saving prompts/transcripts."""
    target = os.getenv("CLIPPEDAI_QWEN_DIAGNOSTIC_LOG", "").strip()
    if not target:
        return
    parsed_ids = sorted(parsed_scores)
    parsed = []
    for candidate_id in parsed_ids:
        score = parsed_scores[candidate_id]
        parsed.append({
            "candidate_id": candidate_id,
            "decision": score.get("decision"),
            "score": score.get("score"),
            "reason": _redact_qwen_diagnostic_text(str(score.get("reason", "")))[:240],
        })
    if raw_content is None:
        response_state = "unavailable"
    elif not parsed:
        response_state = "malformed_or_unscored"
    elif len(parsed_ids) < len(expected_ids):
        response_state = "partial"
    else:
        response_state = "parsed"
    record = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "qwen_response",
        "task": task_name,
        "model": OLLAMA_MODEL,
        "expected_candidate_ids": list(expected_ids),
        "response_state": response_state,
        "missing_or_invalid_candidate_ids": [cid for cid in expected_ids if cid not in parsed_scores],
        "raw_response": _redact_qwen_diagnostic_text(raw_content[:20000]) if raw_content is not None else None,
        "parsed_candidates": parsed,
        "error": _redact_qwen_diagnostic_text(error)[:500] if error else None,
    }
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        keep_count = sum(1 for row in parsed if row["decision"] == "keep")
        reject_count = sum(1 for row in parsed if row["decision"] == "reject")
        print(f"  [QwenDiagnostic] {task_name}: state={response_state}, keep={keep_count}, reject={reject_count}, missing_or_invalid={len(record['missing_or_invalid_candidate_ids'])}.")
    except OSError as exc:
        print(f"  [QwenDiagnostic] Could not persist {task_name}: {type(exc).__name__}: {exc}")


def analyze_candidates_with_ai(candidates, transcription, batch_size: int = 3):
    """Analyze candidates with Qwen3 8B. Missing AI responses are retried individually."""
    if not candidates:
        return {}
    aggregated: Dict[int, Dict[str, float]] = {}
    batches = []
    for start in range(0, len(candidates), batch_size):
        batch = []
        for i in range(start, min(start + batch_size, len(candidates))):
            snippet, inner = extract_candidate_transcript(i, candidates[i], transcription)
            batch.append((i, candidates[i], inner, snippet))
        batches.append(batch)
    for bi, batch in enumerate(batches, 1):
        expected = [x[0] for x in batch]
        print(f"  [AI] Batch {bi}/{len(batches)} → {OLLAMA_MODEL}")
        raw = call_ollama(build_clip_analysis_prompt(batch), task_name=f"clip_ranking_{bi}", format_json=True, max_retries=1)
        try:
            parsed = parse_ai_clip_scores(raw or "", expected)
        except Exception as exc:
            _record_qwen_diagnostic(f"clip_ranking_{bi}", expected, raw, {}, f"parse failed: {type(exc).__name__}: {exc}")
            raise
        _record_qwen_diagnostic(f"clip_ranking_{bi}", expected, raw, parsed)
        if parsed:
            aggregated.update(parsed)
        else:
            print(f"  [AI] Batch {bi}: no valid structured scores returned.")
    # Retry any candidate not successfully scored, one at a time.
    missing = [i for i in range(len(candidates)) if i not in aggregated]
    for i in missing:
        snippet, inner = extract_candidate_transcript(i, candidates[i], transcription)
        print(f"  [AI] Retry candidate {i+1}/{len(candidates)} individually...")
        raw = call_ollama(build_clip_analysis_prompt([(i, candidates[i], inner, snippet)]), task_name=f"clip_retry_{i+1}", format_json=True, max_retries=0)
        try:
            parsed = parse_ai_clip_scores(raw or "", [i])
        except Exception as exc:
            _record_qwen_diagnostic(f"clip_retry_{i+1}", [i], raw, {}, f"parse failed: {type(exc).__name__}: {exc}")
            raise
        _record_qwen_diagnostic(f"clip_retry_{i+1}", [i], raw, parsed)
        aggregated.update(parsed)
    return aggregated


def compute_final_score(idx: int, clip, transcription, ai_scores: Optional[Dict]) -> Tuple[float, Dict]:
    """AI is primary. Deterministic rules only sanity-check valid AI scores."""
    rule_norm = calculate_engagement_score(clip, transcription) * 100.0
    ai = ai_scores.get(idx) if isinstance(ai_scores, dict) else None
    if not ai or not ai.get("ai_valid"):
        fallback = _default_ai_scores()
        fallback["reason"] = "AI score unavailable for this candidate."
        fallback["rule_score"] = rule_norm
        return rule_norm, fallback
    final = float(ai.get("score", 0.0)) * 0.90 + rule_norm * 0.10
    dur = clip.end_time - clip.start_time
    if dur < MIN_CLIP_DURATION or dur > MAX_CLIP_DURATION:
        final -= 15.0
    elif PREFERRED_MIN_CLIP_DURATION <= dur <= PREFERRED_MAX_CLIP_DURATION:
        final += 3.0
    if ai.get("coherence", 0.0) < 4.5:
        final -= 20.0
    if ai.get("standalone", 0.0) < 4.0:
        final -= 10.0
    if ai.get("payoff", 0.0) < 4.0:
        final -= 10.0
    if ai.get("decision") == "reject":
        # Keep the penalty for ranking diagnostics; the decision gate below excludes it.
        final -= 12.0
    if ai.get("coherence", 0.0) < 4.5:
        final -= 8.0
    return max(0.0, min(100.0, final)), ai


def rank_candidates(candidates, transcription, ai_results):
    ranked = []
    for i, clip in enumerate(candidates):
        score, ai = compute_final_score(i, clip, transcription, ai_results)
        ranked.append((i, clip, score, ai))
    ranked.sort(key=lambda x: x[2], reverse=True)
    return ranked


def gate_ranked_candidates_by_qwen_decision(ranked):
    """Only candidates with an explicit valid Qwen ``keep`` may reach render.

    A rejected candidate cannot be rescued by boundary or duration checks. Those
    checks refine already-approved candidates. Malformed, missing, or unavailable
    Qwen responses are not approval and cannot fall through to deterministic
    rendering.
    Returns (eligible_rows, status): status is qwen_approved, qwen_rejected_all,
    or qwen_unavailable.
    """
    valid_decisions = [
        row for row in ranked
        if isinstance(row[3], dict)
        and row[3].get("ai_valid")
        and row[3].get("decision") in {"keep", "reject"}
    ]
    if not valid_decisions:
        return [], "qwen_unavailable"
    approved = [row for row in valid_decisions if row[3]["decision"] == "keep"]
    if not approved:
        return [], "qwen_rejected_all"
    return approved, "qwen_approved"


def selection_provenance(ai_meta: Optional[Dict]) -> Dict[str, Any]:
    """Preserve the actual decision and whether output used explicit Qwen approval."""
    if isinstance(ai_meta, dict) and ai_meta.get("ai_valid"):
        decision = str(ai_meta.get("decision", "unknown")).strip().lower()
        if decision not in {"keep", "reject"}:
            decision = "unknown"
        recovery_used = False
        if decision == "reject":
            note = "Qwen explicitly rejected this candidate; it is not eligible for output."
        else:
            note = "Qwen explicitly approved this candidate; boundary and duration checks are applied next."
        return {
            "method": "qwen",
            "model": OLLAMA_MODEL,
            "decision": decision,
            "recovery_used": recovery_used,
            "note": note,
        }
    return {
        "method": "unavailable",
        "model": None,
        "decision": None,
        "recovery_used": False,
        "note": "No valid Qwen keep decision was available; this candidate is not eligible for rendering.",
    }


# ============================================================
# SMART BOUNDARY ADJUSTMENT + DURATION ENFORCEMENT
# ============================================================


def _word_has_payoff_signal(word_text: str) -> bool:
    """Heuristic: does a word look like a payoff/climax marker."""
    w = word_text.lower().strip(string.punctuation)
    if any(c.isdigit() for c in w) or "$" in word_text or "!" in word_text or "?" in word_text:
        return True
    if w in IMPORTANT_WORDS_HIGHLIGHT:
        return True
    return False


def adjust_clip_boundaries_to_sentences(clip, transcription, verbose: bool = True):
    """Adjust clip start/end using sentence and word info:
    - Start near first spoken word (avoid leading silence)
    - End after sentence boundary (don't cut mid-sentence)
    - Keep durational changes modest
    """
    try:
        all_words = transcription.get_word_info()
        all_sents = transcription.get_sentence_info()
    except Exception:
        return clip
    if not all_words:
        return clip

    # First word inside-or-right-after clip.start_time
    first_word_idx = None
    last_word_idx = None
    for i, w in enumerate(all_words):
        ws = w.get("start_time") or 0
        we = w.get("end_time") or ws
        if first_word_idx is None and we >= clip.start_time:
            first_word_idx = i
        if ws <= clip.end_time:
            last_word_idx = i
        if ws > clip.end_time:
            break
    if first_word_idx is None or last_word_idx is None:
        return clip

    first_word = all_words[first_word_idx]
    last_word = all_words[last_word_idx]

    # Find sentence containing first_word_idx's char range
    new_start = float(clip.start_time)
    new_end = float(clip.end_time)
    fws = first_word.get("start_time") or new_start
    # Snap start to first_word (unless it jumps way too early)
    if 0.0 <= fws <= clip.start_time + 2.0:
        new_start = fws
    # Snap end to last_word end (no later than original end + 0.8s)
    lwe = last_word.get("end_time") or new_end
    if lwe <= clip.end_time + 1.5:
        new_end = lwe

    # Try to align to sentence boundaries if available
    if all_sents:
        first_char = first_word.get("start_char") or 0
        last_char = last_word.get("end_char") or 0
        start_sent_idx = None
        end_sent_idx = None
        for si, s in enumerate(all_sents):
            ss = s.get("start_char", 0)
            se = s.get("end_char", 0)
            if ss <= first_char < se:
                start_sent_idx = si
            if ss <= last_char < se:
                end_sent_idx = si
        if start_sent_idx is not None:
            sst = all_sents[start_sent_idx].get("start_time")
            if isinstance(sst, (int, float)) and sst <= new_start + 1.5:
                new_start = float(sst)
        if end_sent_idx is not None:
            set_ = all_sents[end_sent_idx].get("end_time")
            if isinstance(set_, (int, float)) and set_ >= new_end - 1.5:
                new_end = float(set_)

    # Don't extend beyond transcript
    try:
        t_end = transcription.end_time
        if new_end > t_end:
            new_end = float(t_end)
    except Exception:
        pass
    if new_start < 0.0:
        new_start = 0.0
    if new_end - new_start < 1.0:
        return clip

    if verbose and (abs(new_start - clip.start_time) > 0.05 or abs(new_end - clip.end_time) > 0.05):
        print(
            f"  [Boundary] {clip.start_time:.1f}-{clip.end_time:.1f} -> "
            f"{new_start:.1f}-{new_end:.1f} "
            f"({(new_end-new_start):.1f}s) [sentence/word align]"
        )

    return _clip_class()(
        start_time=new_start,
        end_time=new_end,
        start_char=clip.start_char,
        end_char=clip.end_char,
    )


def enforce_duration_bounds(
    clip,
    transcription,
    min_dur: Optional[int] = None,
    max_dur: Optional[int] = None,
    pref_min: Optional[int] = None,
    pref_max: Optional[int] = None,
    verbose: bool = True,
):
    """Extend short clips, trim long clips using transcript boundaries.

    Returns adjusted Clip or None if clip cannot be made valid.
    """
    min_dur = MIN_CLIP_DURATION if min_dur is None else min_dur
    max_dur = MAX_CLIP_DURATION if max_dur is None else max_dur
    pref_min = PREFERRED_MIN_CLIP_DURATION if pref_min is None else pref_min
    pref_max = PREFERRED_MAX_CLIP_DURATION if pref_max is None else pref_max
    if transcription is None:
        return clip
    try:
        all_words = transcription.get_word_info()
        all_sents = transcription.get_sentence_info()
    except Exception:
        all_words = []
        all_sents = []

    dur = clip.end_time - clip.start_time
    orig = (clip.start_time, clip.end_time, dur)

    # 1. Already in range: keep
    if min_dur <= dur <= max_dur:
        # Try to push into preferred range if near
        if dur > pref_max:
            # Try trim to ~pref_max by ending on a payoff/sentence boundary
            target_upper = clip.start_time + pref_max + 3.0  # allow up to pref_max+3
            hard_upper = clip.start_time + max_dur
            # Search last_word <= hard_upper, prefer <= target_upper but with payoff signal
            best_end = None
            if all_words:
                for i, w in enumerate(all_words):
                    we = w.get("end_time") or 0
                    if we < clip.start_time + 1.0:
                        continue
                    if we > hard_upper:
                        break
                    candidate_end = we
                    if candidate_end - clip.start_time < min_dur:
                        continue
                    # Prefer sentence-ending words
                    is_sent_end = False
                    if all_sents:
                        endc = w.get("end_char") or 0
                        for s in all_sents:
                            se = s.get("end_char", 0)
                            if abs(endc - se) <= 1:
                                is_sent_end = True
                                break
                    payoff = _word_has_payoff_signal(w.get("word", ""))
                    fits_pref = candidate_end <= clip.start_time + pref_max
                    score = (
                        (10 if fits_pref else 0)
                        + (8 if is_sent_end else 0)
                        + (5 if payoff else 0)
                    )
                    if best_end is None or score >= best_end[0]:
                        best_end = (score, candidate_end, is_sent_end)
                if best_end is not None:
                    return _clip_class()(
                        start_time=clip.start_time,
                        end_time=best_end[1],
                        start_char=clip.start_char,
                        end_char=clip.end_char,
                    )
        return clip

    # 2. Too long: trim
    if dur > max_dur:
        hard_upper = clip.start_time + max_dur
        pref_upper = clip.start_time + pref_max
        best = None  # (score, end_time)
        if all_words:
            for i, w in enumerate(all_words):
                we = w.get("end_time") or 0
                if we < clip.start_time + min(min_dur, pref_min):
                    continue
                if we > hard_upper:
                    break
                cand = we
                # End-of-sentence bonus
                is_sent_end = False
                if all_sents:
                    endc = w.get("end_char") or 0
                    for s in all_sents:
                        se = s.get("end_char", 0)
                        if abs(endc - se) <= 1:
                            is_sent_end = True
                            break
                payoff = _word_has_payoff_signal(w.get("word", ""))
                in_pref = cand <= pref_upper
                score = (
                    (20 if in_pref else 0)
                    + (15 if is_sent_end else 0)
                    + (10 if payoff else 0)
                    - abs(cand - pref_upper) * 0.5
                )
                if best is None or score > best[0]:
                    best = (score, cand)
        new_end = best[1] if best else hard_upper
        # Clip lives in the ML runtime tier and is only imported on demand, so
        # it cannot be a module-level global. Referencing the bare name here
        # raised "NameError: name 'Clip' is not defined" on every candidate that
        # reached this branch, and the caller discarded the clip as a result, so
        # long videos silently produced zero Shorts.
        new_clip = _clip_class()(
            start_time=clip.start_time,
            end_time=new_end,
            start_char=clip.start_char,
            end_char=clip.end_char,
        )
        nd = new_clip.end_time - new_clip.start_time
        if nd < min_dur:
            return None
        if verbose:
            print(
                f"  [Trim long] {orig[0]:.1f}-{orig[1]:.1f} ({orig[2]:.1f}s) -> "
                f"{new_clip.start_time:.1f}-{new_clip.end_time:.1f} ({nd:.1f}s)"
            )
        return new_clip

    # 3. Too short: extend using surrounding sentences
    if dur < min_dur:
        needed = min_dur - dur
        # Find first/last word indices inside current clip
        first_idx = None
        last_idx = None
        if all_words:
            for i, w in enumerate(all_words):
                ws = w.get("start_time") or 0
                we = w.get("end_time") or 0
                if we >= clip.start_time and first_idx is None:
                    first_idx = i
                if ws <= clip.end_time:
                    last_idx = i
                if ws > clip.end_time and last_idx is not None:
                    break
        new_start = float(clip.start_time)
        new_end = float(clip.end_time)
        # Extend forward first (toward the story)
        remaining = needed
        if all_words and last_idx is not None:
            j = last_idx + 1
            while remaining > 0 and j < len(all_words):
                w = all_words[j]
                we = w.get("end_time") or 0
                if we > clip.start_time + max_dur:
                    break
                new_end = we
                j += 1
                remaining -= 0.5
        # Still short? try extending start backward
        if (new_end - new_start) < min_dur and all_words and first_idx is not None:
            remaining2 = min_dur - (new_end - new_start)
            j = first_idx - 1
            while remaining2 > 0 and j >= 0:
                w = all_words[j]
                ws = w.get("start_time") or 0
                if new_end - ws > max_dur:
                    break
                new_start = ws
                j -= 1
                remaining2 -= 0.5
        # Snap to sentence boundaries
        if all_sents:
            for s in all_sents:
                st = s.get("start_time")
                et = s.get("end_time")
                if isinstance(st, (int, float)) and st <= new_start + 0.5:
                    sc = s.get("start_char", 0)
                    sec = s.get("end_char", 0)
                    if sc <= (first_idx and all_words[first_idx].get("start_char", 0) or 0) <= sec:
                        # Use sentence start if within max bounds
                        if new_end - float(st) <= max_dur:
                            new_start = float(st)
                            break
            for s in reversed(all_sents):
                et = s.get("end_time")
                if isinstance(et, (int, float)) and et >= new_end - 0.5:
                    if float(et) - new_start <= max_dur and float(et) - new_start >= min_dur * 0.9:
                        new_end = float(et)
                        break
        final_dur = new_end - new_start
        if final_dur < min_dur or final_dur > max_dur:
            return None
        if verbose:
            print(
                f"  [Extend short] {orig[0]:.1f}-{orig[1]:.1f} ({orig[2]:.1f}s) -> "
                f"{new_start:.1f}-{new_end:.1f} ({final_dur:.1f}s)"
            )
        return _clip_class()(
            start_time=new_start,
            end_time=new_end,
            start_char=clip.start_char,
            end_char=clip.end_char,
        )

    return clip


def trim_leading_trailing_silence_conservative(clip, transcription):
    """Conservative dead-air trim: remove obvious leading/trailing silence only.

    Does NOT touch internal pauses to avoid desync.
    Safe and simple; always returns a valid Clip if possible.
    """
    try:
        all_words = transcription.get_word_info()
    except Exception:
        return clip
    if not all_words:
        return clip
    # Find first word whose start_time >= clip.start
    first_idx = None
    last_idx = None
    for i, w in enumerate(all_words):
        ws = w.get("start_time") or 0
        we = w.get("end_time") or 0
        if first_idx is None and we >= clip.start_time:
            first_idx = i
        if ws <= clip.end_time:
            last_idx = i
        if ws > clip.end_time and last_idx is not None:
            break
    if first_idx is None or last_idx is None:
        return clip
    fws = all_words[first_idx].get("start_time") or clip.start_time
    lwe = all_words[last_idx].get("end_time") or clip.end_time
    # Keep up to 0.4s of leading silence (natural breathing)
    new_start = max(clip.start_time, fws - 0.15)
    # Keep up to 0.5s of trailing silence
    new_end = min(clip.end_time, lwe + 0.35)
    if new_end - new_start < 1.0:
        return clip
    return _clip_class()(
        start_time=new_start,
        end_time=new_end,
        start_char=clip.start_char,
        end_char=clip.end_char,
    )


def _detect_person_trajectory(input_path: str, target_w: int, target_h: int,
                              zoom: float, sample_fps: float = 5.0,
                              role_centroids: tuple[float, ...] | None = None,
                              role_index: int = 0,
                              hold_on_loss: bool = False,
                              initial_hint: tuple[float, float] | None = None) -> tuple[list[dict], dict]:
    """Track visible faces and build a stable, crop-safe visual-only camera path.

    When ``role_centroids`` is supplied the detections are reduced to the single
    person nearest to ``role_centroids[role_index]`` before tracking. Split-screen
    passes one centroid per speaker so each panel reuses this whole pipeline -
    target selection, loss hold, transitions, smoothing and the hard face clamp -
    instead of a second, weaker framing implementation.

    ``hold_on_loss`` keeps the last good framing instead of snapping to the centre
    when the assigned speaker is not visible in a shot. Split-screen needs this:
    with two panels on cut-heavy footage the missing speaker would otherwise fall
    back to the same centred crop, putting the same person in both panels.

    ``initial_hint`` is a normalised (cx, cy) used before this speaker has ever
    been seen. The frame centre is a poor stand-in for a split panel: it sits
    between the two speakers, so the panel ends up framed on whoever is nearer
    and both panels show the same person.
    """
    _ensure_cv2()
    if cv2 is None:
        return [], {}
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return [], {}
    try:
        source_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or target_w)
        source_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or target_h)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        step = max(1, int(round(fps / max(1.0, sample_fps))))
        scaled_h = max(target_h, target_h * zoom)
        scaled_w = max(target_w, max(target_w * zoom, scaled_h * source_w / max(1, source_h)))
        max_x = max(0.0, scaled_w - target_w)
        max_y = max(0.0, scaled_h - target_h)

        detector_name = "haar"
        mtcnn = None
        try:
            from facenet_pytorch import MTCNN
            import torch
            mtcnn = MTCNN(keep_all=True, device="cuda:0" if torch.cuda.is_available() else "cpu")
            detector_name = "mtcnn"
        except Exception as exc:
            print(f"  [Framing] MTCNN unavailable; using Haar fallback: {type(exc).__name__}: {exc}")

        haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        sampled_items = []
        frame_index = 0
        while frame_index < total:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if frame_index % step == 0:
                sample = frame
                detection_scale = min(1.0, 960.0 / max(1, source_w))
                if detection_scale < 1.0:
                    sample = cv2.resize(frame, None, fx=detection_scale, fy=detection_scale, interpolation=cv2.INTER_AREA)
                sampled_items.append((frame_index, sample))
            frame_index += 1
        cap.release()

        scene_ids = []
        scene_id = 0
        previous_gray = None
        previous_histogram = None
        cut_indices = set()
        for sample_index, (_frame_idx, sample) in enumerate(sampled_items):
            small = cv2.resize(sample, (320, 180), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            histogram = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
            cv2.normalize(histogram, histogram)
            if previous_gray is not None:
                mean_change = float(cv2.absdiff(gray, previous_gray).mean())
                histogram_distance = float(cv2.compareHist(previous_histogram, histogram, cv2.HISTCMP_BHATTACHARYYA))
                if mean_change > 28.0 and histogram_distance > 0.12 or mean_change > 48.0:
                    scene_id += 1
                    cut_indices.add(sample_index)
            scene_ids.append(scene_id)
            previous_gray = gray
            previous_histogram = histogram

        from PIL import Image
        detection_items = []
        if mtcnn is not None:
            for batch_start in range(0, len(sampled_items), 8):
                batch = sampled_items[batch_start:batch_start + 8]
                images = [Image.fromarray(cv2.cvtColor(item[1], cv2.COLOR_BGR2RGB)) for item in batch]
                boxes_batch, probabilities_batch = mtcnn.detect(images, landmarks=False)
                for (_, sample), boxes, probabilities in zip(batch, boxes_batch, probabilities_batch):
                    detections = []
                    if boxes is not None:
                        for box, probability in zip(boxes.tolist(), probabilities.tolist()):
                            probability = float(probability or 0.0)
                            if probability < 0.78:
                                continue
                            x1, y1, x2, y2 = box[:4]
                            detections.append({
                                "cx": ((x1 + x2) / 2.0) / sample.shape[1],
                                "cy": ((y1 + y2) / 2.0) / sample.shape[0],
                                "w": max(1.0, x2 - x1) / sample.shape[1],
                                "h": max(1.0, y2 - y1) / sample.shape[0],
                                "quality": probability,
                                "kind": "face",
                            })
                    detection_items.append(detections)
        else:
            for _, sample in sampled_items:
                gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
                faces = haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
                detection_items.append([
                    {
                        "cx": (x + w / 2.0) / sample.shape[1],
                        "cy": (y + h / 2.0) / sample.shape[0],
                        "w": w / sample.shape[1],
                        "h": h / sample.shape[0],
                        "quality": 0.65,
                        "kind": "face",
                    }
                    for x, y, w, h in faces
                ])

        if role_centroids:
            # Keep only the face belonging to this speaker's horizontal slot, so
            # tracking, selection and smoothing below all operate on one person.
            def _nearest_role(cx: float) -> int:
                return min(range(len(role_centroids)),
                           key=lambda i: abs(cx - role_centroids[i]))

            wanted = role_centroids[role_index] if role_index < len(role_centroids) else 0.0
            detection_items = [
                [d for d in detections if _nearest_role(d["cx"]) == role_index]
                for detections in detection_items
            ]
            print(f"  [Framing] Role {role_index} (anchor cx={wanted:.2f}): "
                  f"{sum(len(d) for d in detection_items)} detections kept")

        tracks: list[dict] = []
        next_track_id = 1
        points: list[dict] = []
        for sample_index, ((frame_idx, _sample), detections, current_scene_id) in enumerate(
            zip(sampled_items, detection_items, scene_ids)
        ):
            if not detections:
                for track in tracks:
                    if track["scene_id"] == current_scene_id:
                        track["misses"] += 1
                points.append({"frame": frame_idx, "time": frame_idx / max(1.0, fps), "tracks": [],
                               "scene_id": current_scene_id, "scene_cut": sample_index in cut_indices,
                               "detector": detector_name})
                continue

            for track in tracks:
                if track["scene_id"] == current_scene_id:
                    track["misses"] += 1

            for detection in detections:
                matched = None
                for track in tracks:
                    if track["scene_id"] != current_scene_id or track["misses"] > 2:
                        continue
                    dx = abs(track["cx"] - detection["cx"])
                    dy = abs(track["cy"] - detection["cy"])
                    dist = (dx * dx + dy * dy) ** 0.5
                    size_delta = abs(track["w"] - detection["w"]) / max(track["w"], detection["w"], 0.01)
                    if dist <= 0.18 + track["w"] * 0.8 and size_delta <= 0.45:
                        matched = track
                        break
                if matched is not None:
                    matched["cx"] = detection["cx"]
                    matched["cy"] = detection["cy"]
                    matched["w"] = detection["w"]
                    matched["h"] = detection["h"]
                    matched["quality"] = max(matched["quality"], detection["quality"])
                    matched["last_seen"] = frame_idx
                    matched["misses"] = 0
                    matched["visible"] += 1
                    matched["detections"].append((frame_idx, detection))
                else:
                    tracks.append({
                        "track_id": next_track_id,
                        "cx": detection["cx"],
                        "cy": detection["cy"],
                        "w": detection["w"],
                        "h": detection["h"],
                        "quality": detection["quality"],
                        "last_seen": frame_idx,
                        "misses": 0,
                        "visible": 1,
                        "scene_id": current_scene_id,
                        "detector": detector_name,
                        "detections": [(frame_idx, detection)],
                    })
                    next_track_id += 1

            tracks = [track for track in tracks if track["misses"] <= 4 or track["scene_id"] != current_scene_id]
            visible = [track for track in tracks if track["last_seen"] == frame_idx]
            for track in visible:
                area_score = min(1.0, (track["w"] * track["h"]) / 0.035)
                continuity = min(1.0, track["visible"] / max(1, int(sample_fps * 2.0)))
                track["score"] = track["quality"] * 0.62 + continuity * 0.30 + area_score * 0.08
            points.append({
                "frame": frame_idx,
                "time": frame_idx / max(1.0, fps),
                "tracks": [dict(track) for track in visible],
                "scene_id": current_scene_id,
                "scene_cut": sample_index in cut_indices,
                "detector": detector_name,
            })

        if not points:
            return [], {"source_w": source_w, "source_h": source_h, "fps": fps, "scaled_w": scaled_w, "scaled_h": scaled_h, "max_x": max_x, "max_y": max_y, "detector": detector_name}

        if not any(point.get("tracks") for point in points):
            return [], {"source_w": source_w, "source_h": source_h, "fps": fps, "scaled_w": scaled_w,
                        "scaled_h": scaled_h, "max_x": max_x, "max_y": max_y, "detector": detector_name}

        def crop_for_track(track: dict) -> tuple[float, float]:
            face_left = (track["cx"] - track["w"] * 1.15) * scaled_w
            face_right = (track["cx"] + track["w"] * 1.15) * scaled_w
            face_top = (track["cy"] - track["h"] * 1.25) * scaled_h
            face_bottom = (track["cy"] + track["h"] * 1.40) * scaled_h
            desired_x = track["cx"] * scaled_w - target_w / 2.0
            desired_y = track["cy"] * scaled_h - target_h * 0.31
            margin_x = max(54.0, scaled_w * 0.022)
            safe_min_x = max(0.0, face_right + margin_x - target_w)
            safe_max_x = min(max_x, face_left - margin_x)
            if safe_min_x <= safe_max_x:
                desired_x = max(safe_min_x, min(safe_max_x, desired_x))
            desired_x = max(0.0, min(max_x, desired_x))
            safe_max_y = min(max_y, face_top - max(20.0, scaled_h * 0.010))
            safe_min_y = max(0.0, face_bottom - target_h * 0.62)
            if safe_min_y <= safe_max_y:
                desired_y = max(safe_min_y, min(safe_max_y, desired_y))
            return max(0.0, min(max_x, desired_x)), max(0.0, min(max_y, desired_y))

        def is_crop_valid_for_face(cx: float, track: dict) -> bool:
            """Require the detected face box to remain inside a safe crop margin."""
            face_left_px = (track["cx"] - track["w"] / 2.0) * scaled_w - cx
            face_right_px = (track["cx"] + track["w"] / 2.0) * scaled_w - cx
            margin = max(32.0, target_w * 0.04)
            return margin <= face_left_px and face_right_px <= target_w - margin

        sample_interval = step / max(1.0, fps)
        loss_hold = max(1.50, sample_interval * 4.0)
        confirmation = max(1.00, sample_interval * 3.0)
        initial_confirm = max(0.50, sample_interval * 2.0)
        transition_duration = 0.80
        # Use -1 as "no position yet" sentinel so first acquisition jumps directly to
        # the target face instead of drifting from the video center.
        _NO_POS = -1.0
        current_x, current_y = _NO_POS, _NO_POS
        # Last framing that actually had the assigned speaker in it. Retained
        # across shot changes when hold_on_loss is set.
        held_x, held_y = None, None
        smooth_dx, smooth_dy = 0.0, 0.0
        current_track_id = None
        current_scene_id = None
        last_target_visible = None
        pending_track_id = None
        pending_since = None
        initial_track_id = None
        initial_since = None
        transition_start = None
        transition_from = None
        transition_to = None
        has_acquired = False
        current_held_since = None
        keyframes = None
        switch_events = []
        # --- Proactive switch state ---
        # challenger_track_id / challenger_since track a competing visible face while the
        # current target is still detected.  A switch fires when the challenger has been
        # consistently better for challenger_confirm seconds AND the camera has not just
        # switched (switch_cooldown).
        challenger_track_id: int | None = None
        challenger_since: float | None = None
        last_switch_time: float = -999.0
        # Conservative thresholds — all must be met simultaneously:
        #   challenger_confirm : challenger must hold the advantage for this many seconds
        #   proactive_score_gap: challenger's base score must beat current target by this
        #   proactive_sep_px   : challenger's crop destination must be at least this many
        #                        pixels away from the current crop (prevents micro-jumps)
        #   switch_cooldown    : seconds after any switch before another is allowed
        challenger_confirm  = max(1.50, sample_interval * 7.0)  # ~1.5 s at 5 fps
        proactive_score_gap = 0.18   # challenger score must beat current by ≥18 %
        proactive_sep_px    = max(target_w * 0.25, 100.0)       # ≥25 % of frame width
        switch_cooldown     = max(3.00, sample_interval * 15.0) # ≥3 s between switches
        last_camera_move_time = None
        last_meaningful_movement_time = None

        for point in points:
            time_sec = point["time"]
            frame_start_x, frame_start_y = current_x, current_y
            visible = point["tracks"]
            scene_changed = point.get("scene_cut", False) or (
                current_scene_id is not None and point["scene_id"] != current_scene_id
            )
            if scene_changed:
                current_track_id = None
                current_held_since = None
                last_target_visible = time_sec - loss_hold
                pending_track_id = None
                pending_since = None
                initial_track_id = None
                initial_since = None
                transition_start = None
                transition_from = None
                transition_to = None
                smooth_dx, smooth_dy = 0.0, 0.0
                # Reset position sentinel so the next acquisition jumps directly
                # to the new target face rather than drifting from the old position.
                # With hold_on_loss the framing is carried over instead, so a shot
                # where this speaker is off-camera keeps pointing at them.
                if not (hold_on_loss and held_x is not None):
                    current_x, current_y = _NO_POS, _NO_POS
                challenger_track_id = None
                challenger_since = None
            current_scene_id = point.get("scene_id")
            visible_by_id = {track["track_id"]: track for track in visible}
            selected = visible_by_id.get(current_track_id) if current_track_id is not None else None
            action = "HOLD"
            reason = "face temporarily missing; hold last crop"

            # --- FRAMING FAILURE DETECTION ---
            # Check whether any currently visible face is actually inside the crop.
            # Used both to trigger an immediate switch when the crop shows no person,
            # and to force-correct the crop before smoothing kicks in.
            current_crop_has_face = False
            if visible and current_x != _NO_POS:
                for _t in visible:
                    if is_crop_valid_for_face(current_x, _t):
                        current_crop_has_face = True
                        break
            # A framing failure is when we have visible faces but the crop shows none.
            framing_failure = bool(visible) and (not current_crop_has_face) and (current_x != _NO_POS)

            if selected is not None:
                last_target_visible = time_sec
                if current_held_since is None:
                    current_held_since = time_sec
                pending_track_id = None
                pending_since = None
                initial_track_id = None
                initial_since = None
                desired_x, desired_y = crop_for_track(selected)

                # FIX: If the position is unset (sentinel) or the face is outside the
                # current crop, jump directly to the correct position instead of
                # smoothly approaching from whatever the current position is.
                if current_x == _NO_POS:
                    current_x, current_y = desired_x, desired_y
                    smooth_dx, smooth_dy = 0.0, 0.0
                    transition_start = transition_from = transition_to = None
                    action = "SNAP"
                    reason = ("SCENE_CUT: acquire new visible subject" if scene_changed
                              else "TARGET_REACQUIRE: acquire visible subject")
                    challenger_track_id = None
                    challenger_since = None
                elif transition_start is not None and transition_from is not None and transition_to is not None:
                    progress = min(1.0, max(0.0, (time_sec - transition_start) / transition_duration))
                    eased = progress * progress * (3.0 - 2.0 * progress)
                    current_x = transition_from[0] + (transition_to[0] - transition_from[0]) * eased
                    current_y = transition_from[1] + (transition_to[1] - transition_from[1]) * eased
                    action = "SWITCH" if progress < 1.0 else "TRACK"
                    if progress >= 1.0:
                        transition_start = transition_from = transition_to = None
                        smooth_dx, smooth_dy = 0.0, 0.0
                else:
                    deadzone_x = max(18.0, max_x * 0.022)
                    deadzone_y = max(18.0, max_y * 0.022)
                    gain_x = 0.40
                    gain_y = 0.34
                    dx = desired_x - current_x
                    dy = desired_y - current_y
                    adx = abs(dx)
                    ady = abs(dy)

                    tlw = selected["w"] * scaled_w
                    tlh = selected["h"] * scaled_h
                    fl = (selected["cx"] - selected["w"] * 1.15) * scaled_w - current_x
                    fr = (selected["cx"] + selected["w"] * 1.15) * scaled_w - (current_x + target_w)
                    ft = (selected["cy"] - selected["h"] * 1.25) * scaled_h - current_y
                    fb = (selected["cy"] + selected["h"] * 1.40) * scaled_h - (current_y + target_h)
                    urg = 0.0
                    if fl < 54.0: urg = max(urg, 1.0 - fl / 54.0)
                    if fr > -54.0: urg = max(urg, 1.0 + fr / 54.0)
                    if max_y > 0.0 and ft < 30.0: urg = max(urg, 1.0 - ft / 30.0)
                    if fb > -30.0: urg = max(urg, 1.0 + fb / 30.0)
                    urg = min(1.0, urg)
                    gx = gain_x + (0.78 - gain_x) * urg
                    gy = gain_y + (0.68 - gain_y) * urg
                    vel_w = 0.30 + urg * 0.45

                    # A deadzone is a true hold: do not feed a decaying velocity
                    # back into the camera after the subject settles.  The old
                    # momentum term kept moving even with step_x/step_y at zero.
                    # Increase response only when the face approaches a crop edge;
                    # otherwise detector jitter cannot move the camera.
                    face_outside_safe_crop = not is_crop_valid_for_face(current_x, selected)

                    def follow_axis(delta: float, absolute_delta: float,
                                    deadzone: float, base_gain: float) -> float:
                        if absolute_delta <= deadzone and urg < 0.45 and not face_outside_safe_crop:
                            return 0.0
                        gain = min(0.88, base_gain + urg * 0.30 +
                                   (0.20 if face_outside_safe_crop else 0.0))
                        return delta * gain

                    step_x = follow_axis(dx, adx, deadzone_x, gain_x)
                    step_y = follow_axis(dy, ady, deadzone_y, gain_y)
                    smooth_dx = smooth_dy = 0.0
                    current_x += step_x
                    current_y += step_y

                    moved = abs(step_x) >= 0.5 or abs(step_y) >= 0.5
                    action = "FOLLOWING" if moved else "LOCKED"
                    reason = ("SUBJECT_MOVED: safe-area follow" if moved
                              else "LOCKED: subject inside deadzone")
                if keyframes is None:
                    keyframes = [{"time": 0.0, "x": current_x, "y": current_y}]

                # --- PROACTIVE SWITCH EVALUATION ---
                # While the current target is still detected and smoothly tracked, check
                # whether any other visible face has consistently outscored it.  If a
                # challenger satisfies all three guards (score gap, spatial separation,
                # cooldown) for at least challenger_confirm seconds, commit a transition
                # using the same transition_start/from/to mechanism as normal switches.
                # This lets the camera change subjects without waiting for the current
                # target to disappear from the frame.
                if (has_acquired
                        and transition_start is None          # not already mid-transition
                        and current_x != _NO_POS
                        and len(visible) >= 2                 # must have an alternative
                        and (time_sec - last_switch_time) >= switch_cooldown):

                    # Score the current target.
                    cur_score = float(selected.get("score", selected.get("quality", 0.5)))

                    # Find the best alternative face (different track) on screen.
                    best_alt = None
                    best_alt_score = -1.0
                    for alt in visible:
                        if alt["track_id"] == current_track_id:
                            continue
                        # Must have been visible long enough to be real (≥2 samples).
                        if alt.get("visible", 0) < 2:
                            continue
                        alt_score = float(alt.get("score", alt.get("quality", 0.5)))
                        if alt_score > best_alt_score:
                            best_alt_score = alt_score
                            best_alt = alt

                    if best_alt is not None:
                        alt_x, alt_y = crop_for_track(best_alt)
                        separation = abs(alt_x - current_x)
                        score_advantage = best_alt_score - cur_score

                        # Check all three guards.
                        if (score_advantage >= proactive_score_gap
                                and separation >= proactive_sep_px):
                            # Challenger is meaningful — accumulate confirmation time.
                            if challenger_track_id == best_alt["track_id"]:
                                held = time_sec - (challenger_since or time_sec)
                                if held >= challenger_confirm:
                                    # All conditions met for long enough — commit switch.
                                    previous_track_id = current_track_id
                                    current_track_id = best_alt["track_id"]
                                    current_held_since = time_sec
                                    transition_start = time_sec
                                    transition_from = (current_x, current_y)
                                    transition_to = (alt_x, alt_y)
                                    last_target_visible = time_sec
                                    last_switch_time = time_sec
                                    smooth_dx, smooth_dy = 0.0, 0.0
                                    challenger_track_id = None
                                    challenger_since = None
                                    action, reason = "PROACTIVE_SWITCH", (
                                        f"SUBJECT_SWITCH: sustained visual challenger "
                                        f"track {best_alt['track_id']}, score +{score_advantage:.2f}, "
                                        f"separation {separation:.0f}px for {held:.1f}s"
                                    )
                                    switch_events.append({
                                        "time": round(time_sec, 3),
                                        "from_track": previous_track_id,
                                        "to_track": current_track_id,
                                        "reason": reason,
                                    })
                            else:
                                # New challenger — start timing.
                                challenger_track_id = best_alt["track_id"]
                                challenger_since = time_sec
                        else:
                            # No challenger clears the bar — reset.
                            challenger_track_id = None
                            challenger_since = None
                    else:
                        challenger_track_id = None
                        challenger_since = None
            else:
                if last_target_visible is None:
                    last_target_visible = time_sec - loss_hold
                # Current target is gone — cancel any pending proactive challenger.
                challenger_track_id = None
                challenger_since = None
                # FIX: If the crop is showing no person at all (framing failure), switch
                # immediately without waiting for loss_hold / confirmation delays.
                need_immediate = framing_failure or current_x == _NO_POS
                if visible and (need_immediate or not has_acquired or time_sec - last_target_visible >= loss_hold):
                    candidates = visible
                    if current_track_id is not None and not scene_changed and not need_immediate:
                        candidates = [track for track in visible if track["visible"] >= 3]
                    if not candidates:
                        candidates = visible
                    if candidates:
                        held_seconds = 0.0
                        if current_held_since is not None and current_track_id is not None:
                            held_seconds = max(0.0, last_target_visible - current_held_since)
                        held_bonus_cap = min(1.2, held_seconds / 4.0)
                        def ranked_score(t: dict) -> tuple[float, float, float, float]:
                            vis_cap = min(t.get("visible", 1), int(sample_fps * 3.0))
                            size = min(1.0, (t["w"] * t["h"]) / 0.040)
                            base = float(t.get("score", t.get("quality", 0.5)))
                            bonus = 0.0
                            if current_track_id is not None and not scene_changed:
                                if t["track_id"] == current_track_id:
                                    bonus += 0.70
                                    bonus += held_bonus_cap
                            tx, ty = crop_for_track(t)
                            # FIX: Proximity bonus reduced from 0.35 to 0.10 so it only
                            # acts as a tiebreaker rather than rewarding the near-center
                            # track over a higher-quality far-side track.  Also skip the
                            # bonus entirely when current_x is the sentinel (no position).
                            if has_acquired and current_x != _NO_POS:
                                dist = ((tx - current_x) ** 2 + (ty - current_y) ** 2) ** 0.5
                                max_d = (max_x ** 2 + max_y ** 2) ** 0.5
                                prox = 1.0 - min(1.0, dist / max(1.0, max_d * 0.35))
                                bonus += prox * 0.10
                            return (vis_cap + bonus, base + bonus * 0.75, size, bonus)
                        candidate = max(candidates, key=ranked_score)
                        if not has_acquired:
                            first_quality_ok = candidate.get("quality", 0.0) >= 0.55 and (candidate["w"] * candidate["h"]) >= 0.008
                            if first_quality_ok and initial_track_id is None:
                                current_track_id = candidate["track_id"]
                                current_x, current_y = crop_for_track(candidate)
                                last_target_visible = time_sec
                                current_held_since = time_sec
                                has_acquired = True
                                smooth_dx, smooth_dy = 0.0, 0.0
                                keyframes = [{"time": 0.0, "x": current_x, "y": current_y}]
                                action, reason = "ACQUIRE", "initial clear visible face (fast acquire)"
                            elif initial_track_id != candidate["track_id"]:
                                initial_track_id = candidate["track_id"]
                                initial_since = time_sec
                            elif initial_since is not None and time_sec - initial_since >= initial_confirm:
                                current_track_id = candidate["track_id"]
                                current_x, current_y = crop_for_track(candidate)
                                last_target_visible = time_sec
                                current_held_since = time_sec
                                has_acquired = True
                                smooth_dx, smooth_dy = 0.0, 0.0
                                if keyframes is None:
                                    keyframes = [{"time": 0.0, "x": current_x, "y": current_y}]
                                action, reason = "ACQUIRE", "initial persistent visible face"
                        elif need_immediate:
                            # FIX: Framing failure — switch to best candidate immediately
                            # without waiting for the confirmation window.
                            previous_track_id = current_track_id
                            current_track_id = candidate["track_id"]
                            current_held_since = time_sec
                            # Jump directly to correct position; no slow transition when
                            # the crop is already showing wrong content.
                            current_x, current_y = crop_for_track(candidate)
                            last_target_visible = time_sec
                            pending_track_id = pending_since = None
                            smooth_dx, smooth_dy = 0.0, 0.0
                            action = "SNAP"
                            reason = ("SCENE_CUT: reacquire visible subject" if scene_changed
                                      else "TARGET_REACQUIRE: crop lost the selected face")
                            if previous_track_id != current_track_id:
                                switch_events.append({"time": round(time_sec, 3), "from_track": previous_track_id,
                                                      "to_track": current_track_id, "reason": reason})
                        elif candidate["track_id"] == current_track_id:
                            pending_track_id = None
                            pending_since = None
                        elif candidate["track_id"] != pending_track_id:
                            pending_track_id, pending_since = candidate["track_id"], time_sec
                        elif pending_since is not None and time_sec - pending_since >= confirmation:
                            previous_track_id = current_track_id
                            current_track_id = candidate["track_id"]
                            current_held_since = time_sec
                            transition_start = time_sec
                            transition_from = (current_x, current_y)
                            transition_to = crop_for_track(candidate)
                            last_target_visible = time_sec
                            last_switch_time = time_sec
                            pending_track_id = pending_since = None
                            smooth_dx, smooth_dy = 0.0, 0.0
                            action, reason = "SWITCH", "SUBJECT_SWITCH: confirmed replacement track"
                            switch_events.append({"time": round(time_sec, 3), "from_track": previous_track_id,
                                                  "to_track": current_track_id, "reason": reason})
                    else:
                        pending_track_id = pending_since = None
                        initial_track_id = None
                        initial_since = None

            # If position is still the sentinel (no face ever seen), fall back to
            # center. With hold_on_loss, keep the last framing that had this
            # speaker instead: a centred fallback would be identical in both
            # split-screen panels and show the same person twice.
            if current_x == _NO_POS:
                if hold_on_loss and held_x is not None:
                    current_x, current_y = held_x, held_y
                elif hold_on_loss and initial_hint is not None:
                    # Frame the speaker we were told to look for, not the middle
                    # of the shot.
                    hint_cx, hint_cy = initial_hint
                    current_x = hint_cx * scaled_w - target_w / 2.0
                    current_y = hint_cy * scaled_h - target_h * 0.31
                else:
                    current_x, current_y = max_x / 2.0, max_y / 2.0

            current_x = max(0.0, min(max_x, current_x))
            current_y = max(0.0, min(max_y, current_y))

            # FIX: Hard pixel clamp — if the selected track's face has drifted outside
            # the crop due to smoothing, correct immediately.  This is the final safety
            # net so the rendered video never shows the selected person cut off.
            if selected is not None:
                face_left_px = (selected["cx"] - selected["w"] / 2.0) * scaled_w
                face_right_px = (selected["cx"] + selected["w"] / 2.0) * scaled_w
                face_margin = max(32.0, target_w * 0.04)
                if face_right_px - face_left_px <= target_w - 2 * face_margin:
                    if face_left_px < current_x + face_margin:
                        current_x = max(0.0, face_left_px - face_margin)
                    elif face_right_px > current_x + target_w - face_margin:
                        current_x = min(max_x, face_right_px - (target_w - face_margin))
                else:
                    # At an extreme close-up, full face containment can be
                    # geometrically impossible. Keep the complete face centered.
                    current_x = max(0.0, min(max_x,
                                             (face_left_px + face_right_px) / 2.0 - target_w / 2.0))
            if selected is not None:
                # Remember a framing that genuinely contained this speaker.
                held_x, held_y = current_x, current_y
            delta_x = 0.0 if frame_start_x == _NO_POS else current_x - frame_start_x
            delta_y = 0.0 if frame_start_y == _NO_POS else current_y - frame_start_y
            if abs(delta_x) >= 1.0 or abs(delta_y) >= 1.0:
                last_camera_move_time = time_sec
                if action in {"FOLLOWING", "SWITCH", "PROACTIVE_SWITCH", "SNAP"}:
                    last_meaningful_movement_time = time_sec
            active_lock = visible_by_id.get(current_track_id) if current_track_id is not None else None
            camera_state = ("SWITCHING" if transition_start is not None
                            else "FOLLOWING" if action == "FOLLOWING"
                            else "REACQUIRING" if active_lock is None
                            else "LOCKED")
            face_box = None
            if active_lock is not None:
                face_box = [
                    round(active_lock["cx"] - active_lock["w"] / 2.0, 6),
                    round(active_lock["cy"] - active_lock["h"] / 2.0, 6),
                    round(active_lock["cx"] + active_lock["w"] / 2.0, 6),
                    round(active_lock["cy"] + active_lock["h"] / 2.0, 6),
                ]
            point.update({"target_id": current_track_id, "x": int(round(current_x)), "y": int(round(current_y)),
                          "action": action, "state": camera_state, "reason": reason,
                          "camera_delta": [round(delta_x, 2), round(delta_y, 2)],
                          "active_lock": {
                              "track_id": current_track_id,
                              "face_bbox_norm": face_box,
                              "center_norm": ([round(active_lock["cx"], 6), round(active_lock["cy"], 6)]
                                               if active_lock is not None else None),
                              "width_norm": round(active_lock["w"], 6) if active_lock is not None else None,
                              "height_norm": round(active_lock["h"], 6) if active_lock is not None else None,
                              "confidence": round(float(active_lock.get("quality", 0.0)), 4)
                                             if active_lock is not None else 0.0,
                              "last_reliable_detection_time": time_sec if active_lock is not None
                                                              else last_target_visible,
                              "last_meaningful_movement_time": last_meaningful_movement_time,
                              "target_crop": [round(current_x, 2), round(current_y, 2)],
                          },
                          "last_camera_move_time": last_camera_move_time,
                          "challenger_id": challenger_track_id,
                          "challenger_since": challenger_since,
                          "scene_cut": bool(scene_changed),
                          "crop_valid": 0.0 <= current_x <= max_x and 0.0 <= current_y <= max_y})
            if keyframes is None:
                keyframes = [{"time": 0.0, "x": current_x, "y": current_y}]
            if abs(current_x - keyframes[-1]["x"]) > 0.5 or abs(current_y - keyframes[-1]["y"]) > 0.5:
                # Sparse keyframes represent a held crop between observations.
                # Add a hold anchor before a delayed move/snap so FFmpeg does not
                # interpolate toward a future keyframe across the entire idle gap.
                if time_sec - keyframes[-1]["time"] > sample_interval * 1.5:
                    # Same-time duplicate creates a true hold until the change
                    # timestamp; expression interpolation then starts there.
                    hold_time = time_sec
                    if hold_time > keyframes[-1]["time"] + 1e-3:
                        keyframes.append({"time": hold_time,
                                          "x": keyframes[-1]["x"],
                                          "y": keyframes[-1]["y"],
                                          "state": "LOCKED"})
                keyframes.append({"time": time_sec, "x": current_x, "y": current_y,
                                  "state": action, "reason": reason})

        final_x, final_y = current_x, current_y
        print(f"  [Framing] Visual-only target changes={len(switch_events)}; keyframes={len(keyframes)}; detector={detector_name}")
        return points, {"source_w": source_w, "source_h": source_h, "fps": fps,
                        "scaled_w": scaled_w, "scaled_h": scaled_h, "max_x": max_x, "max_y": max_y,
                        "detector": detector_name, "keyframes": keyframes,
                        "target_track": current_track_id, "target_x": final_x, "target_y": final_y,
                        "switch_events": switch_events, "sample_fps": fps / step}
    except Exception as exc:
        cap.release()
        print(f"  [Framing] Person detection unavailable: {type(exc).__name__}: {exc}")
        return [], {}


def _analyze_speaker_visual_tracks(input_path: str, speaker_segments: list[dict],
                                   sample_fps: float = 5.0) -> tuple[list[dict], dict]:
    """Map diarized voices to persistent visual identities using lip activity and face features."""
    return [], {}
    if cv2 is None or not speaker_segments:
        return [], {}
    model_path = Path(__file__).resolve().parent / "models" / "face_landmarker.task"
    if not model_path.is_file():
        print(f"  [Framing] Face-landmark model missing: {model_path}")
        return [], {}

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return [], {}
    try:
        import numpy as np

        source_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
        source_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        step = max(1, int(round(fps / max(1.0, sample_fps))))
        sample_scale = min(1.0, 960.0 / max(1, source_w))

        from PIL import Image
        from facenet_pytorch import MTCNN
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        import mediapipe as mp

        detector = MTCNN(keep_all=True, device="cuda:0" if torch.cuda.is_available() else "cpu")
        landmarker_options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=8,
            min_face_detection_confidence=0.2,
            min_face_presence_confidence=0.2,
        )
        sift = cv2.SIFT_create(nfeatures=500)
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        identities: list[dict] = []
        points: list[dict] = []
        next_identity = 1
        frame_index = 0

        def process_batch(batch: list[tuple[int, Any]], landmarker) -> None:
            nonlocal next_identity
            if not batch:
                return
            images = [Image.fromarray(cv2.cvtColor(item[1], cv2.COLOR_BGR2RGB)) for item in batch]
            boxes_batch, probs_batch, landmarks_batch = detector.detect(images, landmarks=True)
            for (sample_frame, sample), boxes, probabilities, landmarks in zip(
                batch, boxes_batch, probs_batch, landmarks_batch
            ):
                time_sec = sample_frame / max(1.0, fps)
                detections = []
                used_ids: set[int] = set()
                if boxes is not None:
                    for box, probability, facial_points in zip(boxes, probabilities, landmarks):
                        probability = float(probability or 0.0)
                        if probability < 0.78:
                            continue
                        x1, y1, x2, y2 = [float(value) for value in box[:4]]
                        box_w, box_h = max(1.0, x2 - x1), max(1.0, y2 - y1)
                        cx, cy = (x1 + x2) / (2.0 * sample.shape[1]), (y1 + y2) / (2.0 * sample.shape[0])
                        if cy < 0.16 or box_w * box_h / (sample.shape[0] * sample.shape[1]) < 0.002:
                            continue

                        source_points = np.asarray(facial_points[:3], dtype=np.float32)
                        target_points = np.asarray([[82, 92], [174, 92], [128, 145]], dtype=np.float32)
                        transform = cv2.getAffineTransform(source_points, target_points)
                        aligned = cv2.warpAffine(
                            sample,
                            transform,
                            (256, 256),
                            flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REPLICATE,
                        )
                        descriptors = sift.detectAndCompute(cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY), None)[1]
                        padding_x, padding_y = int(box_w * 0.25), int(box_h * 0.25)
                        crop_x1 = max(0, int(round(x1)) - padding_x)
                        crop_y1 = max(0, int(round(y1)) - padding_y)
                        crop_x2 = min(sample.shape[1], int(round(x2)) + padding_x)
                        crop_y2 = min(sample.shape[0], int(round(y2)) + padding_y)
                        mouth_crop = cv2.resize(
                            sample[crop_y1:crop_y2, crop_x1:crop_x2],
                            (256, 256),
                            interpolation=cv2.INTER_CUBIC,
                        )
                        landmark_image = mp.Image(
                            image_format=mp.ImageFormat.SRGB,
                            data=cv2.cvtColor(mouth_crop, cv2.COLOR_BGR2RGB),
                        )
                        landmark_result = landmarker.detect(landmark_image)
                        if not landmark_result.face_landmarks:
                            aperture = None
                        else:
                            face_landmarks = landmark_result.face_landmarks[0]
                            face_y = [point.y for point in face_landmarks]
                            aperture = abs(face_landmarks[13].y - face_landmarks[14].y) / max(
                                0.001, max(face_y) - min(face_y)
                            )

                        best_identity = None
                        best_matches = 0
                        best_continuity_distance = float("inf")
                        if descriptors is not None:
                            for identity in identities:
                                identity_id = identity["track_id"]
                                if identity_id in used_ids:
                                    continue
                                for reference in identity.get("descriptor_bank", []):
                                    try:
                                        pairs = matcher.knnMatch(descriptors, reference, k=2)
                                        good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
                                    except cv2.error:
                                        good = []
                                    if len(good) > best_matches:
                                        best_identity, best_matches = identity, len(good)

                        if best_matches < 5:
                            best_identity = None
                            for identity in identities:
                                identity_id = identity["track_id"]
                                previous = identity.get("last_observation")
                                if identity_id in used_ids or previous is None:
                                    continue
                                elapsed = time_sec - previous["time"]
                                if elapsed > max(0.65, 3.0 / max(1.0, sample_fps)):
                                    continue
                                dx = abs(previous["cx"] - cx)
                                dy = abs(previous["cy"] - cy)
                                size_delta = abs(previous["w"] - box_w / sample.shape[1]) / max(
                                    previous["w"], box_w / sample.shape[1], 0.01
                                )
                                continuity_distance = (dx * dx + dy * dy) ** 0.5
                                if continuity_distance <= 0.12 + previous["w"] * 0.7 and size_delta <= 0.55 and continuity_distance < best_continuity_distance:
                                    best_identity = identity
                                    best_continuity_distance = continuity_distance
                        if best_identity is not None and (best_matches >= 5 or best_continuity_distance < float("inf")):
                            identity_id = best_identity["track_id"]
                        else:
                            identity_id = next_identity
                            next_identity += 1
                            best_identity = {
                                "track_id": identity_id,
                                "descriptors": descriptors,
                                "descriptor_bank": [descriptors] if descriptors is not None else [],
                                "observations": [],
                                "last_observation": None,
                            }
                            identities.append(best_identity)
                        used_ids.add(identity_id)
                        if descriptors is not None and (best_identity.get("descriptors") is None or best_matches >= 5):
                            best_identity["descriptors"] = descriptors
                            if len(best_identity["descriptor_bank"]) < 8:
                                best_identity["descriptor_bank"].append(descriptors)

                        observation = {
                            "frame": sample_frame,
                            "track_id": identity_id,
                            "cx": cx,
                            "cy": cy,
                            "w": box_w / sample.shape[1],
                            "h": box_h / sample.shape[0],
                            "quality": probability,
                            "mouth_aperture": aperture,
                            "identity_matches": best_matches,
                            "_face_descriptors": descriptors,
                        }
                        best_identity["observations"].append({"time": time_sec, **observation})
                        best_identity["last_observation"] = {"time": time_sec, **observation}
                        detections.append(observation)
                points.append({"frame": sample_frame, "time": time_sec, "tracks": detections})

        with mp_vision.FaceLandmarker.create_from_options(landmarker_options) as landmarker:
            batch: list[tuple[int, Any]] = []
            while frame_index < total:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                if frame_index % step == 0:
                    sample = frame
                    if sample_scale < 1.0:
                        sample = cv2.resize(frame, None, fx=sample_scale, fy=sample_scale, interpolation=cv2.INTER_AREA)
                    batch.append((frame_index, sample))
                    if len(batch) == 8:
                        process_batch(batch, landmarker)
                        batch = []
                frame_index += 1
            process_batch(batch, landmarker)
        cap.release()

        parent = {identity["track_id"]: identity["track_id"] for identity in identities}
        members = {identity["track_id"]: {identity["track_id"]} for identity in identities}
        co_visible_pairs = set()
        for point in points:
            visible_ids = sorted({track["track_id"] for track in point["tracks"]})
            for first_index, first_id in enumerate(visible_ids):
                for second_id in visible_ids[first_index + 1:]:
                    co_visible_pairs.add((first_id, second_id))

        def root_identity(identity_id: int) -> int:
            while parent[identity_id] != identity_id:
                parent[identity_id] = parent[parent[identity_id]]
                identity_id = parent[identity_id]
            return identity_id

        for index, first_identity in enumerate(identities):
            for second_identity in identities[index + 1:]:
                first_id = root_identity(first_identity["track_id"])
                second_id = root_identity(second_identity["track_id"])
                if first_id == second_id:
                    continue
                if any(
                    tuple(sorted((first_member, second_member))) in co_visible_pairs
                    for first_member in members[first_id]
                    for second_member in members[second_id]
                ):
                    continue
                maximum_matches = 0
                for first_descriptors in first_identity.get("descriptor_bank", []):
                    for second_descriptors in second_identity.get("descriptor_bank", []):
                        try:
                            pairs = matcher.knnMatch(first_descriptors, second_descriptors, k=2)
                            maximum_matches = max(
                                maximum_matches,
                                sum(first.distance < 0.72 * second.distance for first, second in pairs),
                            )
                        except cv2.error:
                            continue
                        if maximum_matches >= 5:
                            break
                    if maximum_matches >= 5:
                        break
                if maximum_matches >= 5:
                    merged_root = min(first_id, second_id)
                    removed_root = max(first_id, second_id)
                    parent[removed_root] = merged_root
                    members[merged_root].update(members.pop(removed_root))

        track_samples: dict[int, list[dict]] = {}
        for point in points:
            for track in point.get("tracks", []):
                track_samples.setdefault(track["track_id"], []).append(track)

        if not track_samples:
            return [], {}

        def crop_for_track(track: dict) -> tuple[float, float]:
            face_left = (track["cx"] - track["w"] * 0.7) * scaled_w
            face_right = (track["cx"] + track["w"] * 0.7) * scaled_w
            face_top = (track["cy"] - track["h"] * 0.8) * scaled_h
            face_bottom = (track["cy"] + track["h"] * 0.8) * scaled_h
            desired_x = track["cx"] * scaled_w - target_w / 2.0
            desired_y = track["cy"] * scaled_h - target_h * 0.28
            margin_x = max(18.0, scaled_w * 0.008)
            safe_min_x = max(0.0, face_right + margin_x - target_w)
            safe_max_x = min(max_x, face_left - margin_x)
            if safe_min_x <= safe_max_x:
                desired_x = max(safe_min_x, min(safe_max_x, desired_x))
            desired_x = max(0.0, min(max_x, desired_x))
            safe_max_y = min(max_y, face_top - max(6.0, scaled_h * 0.003))
            safe_min_y = max(0.0, face_bottom - target_h * 0.72)
            if safe_min_y <= safe_max_y:
                desired_y = max(safe_min_y, min(safe_max_y, desired_y))
            desired_y = max(0.0, min(max_y, desired_y))
            return desired_x, desired_y

        sample_interval = 1.0 / max(1.0, sample_fps)
        loss_hold = max(0.55, sample_interval * 1.5)
        confirmation = max(0.30, sample_interval)
        transition_duration = 0.45
        current_x, current_y = max_x / 2.0, max_y / 2.0
        current_track_id = None
        current_scene_id = None
        last_target_visible = None
        pending_track_id = None
        pending_since = None
        transition_start = None
        transition_from = None
        transition_to = None
        keyframes = [{"time": 0.0, "x": current_x, "y": current_y}]
        switch_events = []

        for point in points:
            time_sec = point["time"]
            visible = point["tracks"]
            scene_changed = point.get("scene_cut", False) or (
                current_scene_id is not None and point["scene_id"] != current_scene_id
            )
            if current_scene_id is None:
                current_scene_id = point["scene_id"]
            if scene_changed:
                current_track_id = None
                last_target_visible = time_sec - loss_hold
                pending_track_id = None
                pending_since = None
                transition_start = None
                current_scene_id = point["scene_id"]

            tracks_by_id = {track["track_id"]: track for track in visible}
            chosen = tracks_by_id.get(current_track_id) if current_track_id is not None else None
            action = "HOLD"
            reason = "target face temporarily missing; retain last legal crop"

            if chosen is not None:
                last_target_visible = time_sec
                pending_track_id = None
                pending_since = None
                desired_x, desired_y = crop_for_track(chosen)
                if transition_start is not None and transition_from is not None and transition_to is not None:
                    progress = min(1.0, max(0.0, (time_sec - transition_start) / transition_duration))
                    eased = progress * progress * (3.0 - 2.0 * progress)
                    current_x = transition_from[0] + (transition_to[0] - transition_from[0]) * eased
                    current_y = transition_from[1] + (transition_to[1] - transition_from[1]) * eased
                    action = "SWITCH" if progress < 1.0 else "TRACK"
                    if progress >= 1.0:
                        transition_start = None
                        transition_from = None
                        transition_to = None
                else:
                    deadzone_x = max(28.0, max_x * 0.03)
                    deadzone_y = max(28.0, max_y * 0.03)
                    if abs(desired_x - current_x) > deadzone_x:
                        current_x += (desired_x - current_x) * 0.18
                    if abs(desired_y - current_y) > deadzone_y:
                        current_y += (desired_y - current_y) * 0.16
                    action = "TRACK"
                    reason = "persistent visible face track"
            else:
                if last_target_visible is None:
                    last_target_visible = time_sec - loss_hold
                if time_sec - last_target_visible >= loss_hold and visible:
                    candidates = visible
                    if current_track_id is not None and not scene_changed:
                        candidates = [track for track in visible if track["visible"] >= 2]
                    if candidates:
                        candidate = max(
                            candidates,
                            key=lambda track: (
                                min(track["visible"], int(sample_fps * 2.0)),
                                track.get("score", 0.0),
                            ),
                        )
                        if candidate["track_id"] != pending_track_id:
                            pending_track_id = candidate["track_id"]
                            pending_since = time_sec
                        elif pending_since is not None and time_sec - pending_since >= confirmation:
                            old_track_id = current_track_id
                            current_track_id = candidate["track_id"]
                            last_target_visible = time_sec
                            desired_x, desired_y = crop_for_track(candidate)
                            transition_start = time_sec
                            transition_from = (current_x, current_y)
                            transition_to = (desired_x, desired_y)
                            action = "SWITCH" if old_track_id is not None else "ACQUIRE"
                            reason = "new persistent visual track after cut/loss"
                            switch_events.append({"time": round(time_sec, 3), "from_track": old_track_id,
                                                  "to_track": current_track_id, "reason": reason})
                    else:
                        pending_track_id = None
                        pending_since = None

            current_x = max(0.0, min(max_x, current_x))
            current_y = max(0.0, min(max_y, current_y))
            selected_track = tracks_by_id.get(current_track_id) if current_track_id is not None else None
            point.update({
                "target_id": current_track_id,
                "x": int(round(current_x)),
                "y": int(round(current_y)),
                "action": action,
                "reason": reason,
                "crop_valid": 0.0 <= current_x <= max_x and 0.0 <= current_y <= max_y,
                "face_confidence": selected_track.get("quality") if selected_track else None,
            })
            keyframes.append({"time": time_sec, "x": current_x, "y": current_y})

        final_x, final_y = current_x, current_y
        print(f"  [Framing] Visual-only target changes={len(switch_events)}; keyframes={len(keyframes)}; detector={detector_name}")
        return points, {"source_w": source_w, "source_h": source_h, "fps": fps,
                        "scaled_w": scaled_w, "scaled_h": scaled_h, "max_x": max_x, "max_y": max_y,
                        "detector": detector_name, "keyframes": keyframes,
                        "target_track": current_track_id, "target_x": final_x, "target_y": final_y,
                        "switch_events": switch_events, "sample_fps": fps / step}

        anchor_evidence = {}
        if len(speaker_ids) == 2:
            anchor_speaker = min(speaker_ids, key=lambda item: speaker_durations[item])
            turn_scores: dict[int, list[float]] = {}
            for point in points:
                if not speaker_is_active(anchor_speaker, point["time"]) or len(point["tracks"]) < 2:
                    continue
                for track in point["tracks"]:
                    aperture = track.get("mouth_aperture")
                    if aperture is not None:
                        turn_scores.setdefault(track["track_id"], []).append(float(aperture))
            if len(turn_scores) >= 2:
                ranked_tracks = sorted(
                    turn_scores,
                    key=lambda track_id: sum(turn_scores[track_id]) / len(turn_scores[track_id]),
                    reverse=True,
                )
                speaker_to_track[anchor_speaker] = ranked_tracks[0]
                other_speaker = next(speaker for speaker in speaker_ids if speaker != anchor_speaker)
                speaker_to_track[other_speaker] = ranked_tracks[1]
                anchor_evidence = {
                    "anchor_speaker": anchor_speaker,
                    "turn_mean_mouth_aperture": {
                        str(track_id): round(sum(values) / len(values), 4)
                        for track_id, values in turn_scores.items()
                    },
                }
        if len(speaker_to_track) != len(speaker_ids):
            speaker_to_track = {}
            available_tracks = set(identity["track_id"] for identity in candidate_tracks)
            for speaker in sorted(speaker_ids, key=lambda item: speaker_durations[item]):
                scores = mapping_scores.get(speaker, {})
                choices = [track_id for track_id in scores if int(track_id) in available_tracks]
                if choices:
                    chosen_text = max(choices, key=scores.get)
                    chosen = int(chosen_text)
                    speaker_to_track[speaker] = chosen
                    available_tracks.discard(chosen)

        identities_by_id = {identity["track_id"]: identity for identity in identities}
        anchor_speaker = anchor_evidence.get("anchor_speaker")
        anchor_window = [
            segment for segment in speaker_segments
            if str(segment["speaker"]) == anchor_speaker
        ]
        anchor_ids_to_speakers = {track_id: speaker for speaker, track_id in speaker_to_track.items()}
        anchor_descriptor_banks = {speaker: [] for speaker in speaker_to_track}
        for point in points:
            in_anchor_turn = any(
                float(segment["start"]) - 0.25 <= point["time"] <= float(segment["end"]) + 0.25
                for segment in anchor_window
            )
            if not in_anchor_turn or len(point["tracks"]) < 2:
                continue
            for track in point["tracks"]:
                speaker = anchor_ids_to_speakers.get(track["track_id"])
                descriptors = track.get("_face_descriptors")
                if speaker and descriptors is not None:
                    anchor_descriptor_banks[speaker].append(descriptors)
        for speaker, track_id in speaker_to_track.items():
            if not anchor_descriptor_banks[speaker] and track_id in identities_by_id:
                anchor_descriptor_banks[speaker] = identities_by_id[track_id].get("descriptor_bank", [])

        def diarized_speaker_at(time_sec: float) -> Optional[str]:
            active_segments = [
                segment for segment in speaker_segments
                if float(segment["start"]) <= time_sec < float(segment["end"])
            ]
            if not active_segments:
                return None
            active_segment = max(
                active_segments,
                key=lambda segment: (float(segment["start"]), -float(segment["end"])),
            )
            return str(active_segment["speaker"])

        for point in points:
            for track in point["tracks"]:
                best_speaker = anchor_ids_to_speakers.get(track["track_id"])
                best_matches = 0
                speaker_match_scores = {}
                descriptors = track.get("_face_descriptors")
                if descriptors is not None:
                    for speaker, descriptor_bank in anchor_descriptor_banks.items():
                        speaker_matches = 0
                        for reference in descriptor_bank:
                            try:
                                pairs = matcher.knnMatch(descriptors, reference, k=2)
                                matches = sum(first.distance < 0.72 * second.distance for first, second in pairs)
                            except cv2.error:
                                matches = 0
                            speaker_matches = max(speaker_matches, matches)
                        speaker_match_scores[speaker] = speaker_matches
                    ranked_matches = sorted(speaker_match_scores.items(), key=lambda item: item[1], reverse=True)
                    in_anchor_turn = any(
                        float(segment["start"]) - 0.25 <= point["time"] <= float(segment["end"]) + 0.25
                        for segment in anchor_window
                    )
                    if in_anchor_turn and best_speaker and len(point["tracks"]) >= 2:
                        best_matches = speaker_match_scores.get(best_speaker, 0)
                    elif ranked_matches and ranked_matches[0][1] >= 5:
                        runner_up = ranked_matches[1][1] if len(ranked_matches) > 1 else 0
                        if ranked_matches[0][1] - runner_up >= 2:
                            best_speaker, best_matches = ranked_matches[0]
                if best_speaker is None and len(point["tracks"]) == 1:
                    active_speaker = diarized_speaker_at(point["time"])
                    if active_speaker and float(track.get("mouth_aperture") or 0.0) >= 0.035:
                        best_speaker = active_speaker
                track.pop("_face_descriptors", None)
                track["speaker_id"] = best_speaker
                track["speaker_identity_matches"] = best_matches
                track["speaker_match_scores"] = speaker_match_scores

        summaries = {
            str(identity["track_id"]): {
                "sample_count": len(identity["observations"]),
                "first_time": round(identity["observations"][0]["time"], 3),
                "last_time": round(identity["observations"][-1]["time"], 3),
                "mean_center_x": round(sum(item["cx"] for item in identity["observations"]) / len(identity["observations"]), 3),
                "mean_mouth_aperture": round(
                    sum(item["mouth_aperture"] for item in identity["observations"] if item["mouth_aperture"] is not None)
                    / max(1, sum(item["mouth_aperture"] is not None for item in identity["observations"])),
                    4,
                ),
            }
            for identity in candidate_tracks
        }
        info = {
            "source_w": source_w,
            "source_h": source_h,
            "fps": fps,
            "speaker_to_track": speaker_to_track,
            "mapping_scores": mapping_scores,
            "anchor_evidence": anchor_evidence,
            "visual_tracks": summaries,
            "sample_fps": fps / step,
        }
        print(f"  [Framing] Speaker mapping from lip activity/face features: {speaker_to_track}")
        return points, info
    except Exception as exc:
        cap.release()
        print(f"  [Framing] Speaker-to-face mapping unavailable: {type(exc).__name__}: {exc}")
        return [], {}


def _speaker_camera_trajectory(points: list[dict], info: dict, speaker_segments: list[dict],
                              target_w: int, target_h: int, zoom: float) -> tuple[list[dict], dict]:
    """Build a stable crop path that switches only to visually matched active speakers."""
    return points, info
    source_w, source_h = info["source_w"], info["source_h"]
    scaled_h = max(target_h, target_h * zoom)
    scaled_w = max(target_w, max(target_w * zoom, scaled_h * source_w / max(1, source_h)))
    max_x, max_y = max(0.0, scaled_w - target_w), max(0.0, scaled_h - target_h)

    def crop_for_track(track: dict) -> tuple[float, float]:
        desired_x = track["cx"] * scaled_w - target_w / 2.0
        desired_y = track["cy"] * scaled_h - target_h * 0.30
        margin_x = max(12.0, scaled_w * 0.015)
        face_left = (track["cx"] - track["w"] * 0.5) * scaled_w
        face_right = (track["cx"] + track["w"] * 0.5) * scaled_w
        safe_min_x = max(0.0, face_right + margin_x - target_w)
        safe_max_x = min(max_x, face_left - margin_x)
        if safe_min_x <= safe_max_x:
            desired_x = max(safe_min_x, min(safe_max_x, desired_x))
        else:
            desired_x = max(0.0, min(max_x, desired_x))

        margin_y = max(8.0, scaled_h * 0.01)
        face_top = (track["cy"] - track["h"] * 0.5) * scaled_h
        face_bottom = (track["cy"] + track["h"] * 0.5) * scaled_h
        safe_min_y = max(0.0, face_bottom + margin_y - target_h)
        safe_max_y = min(max_y, face_top - margin_y)
        if safe_min_y <= safe_max_y:
            desired_y = max(safe_min_y, min(safe_max_y, desired_y))
        else:
            desired_y = max(0.0, min(max_y, desired_y))
        return desired_x, desired_y

    keyframes = [{"time": 0.0, "x": max_x / 2.0, "y": max_y / 2.0}]
    timeline = []
    current_x, current_y = keyframes[0]["x"], keyframes[0]["y"]
    current_speaker = None
    pending_speaker = None
    pending_since = None
    transition_start = None
    transition_from = None
    transition_to = None
    transition_duration = 0.18
    confirmation_duration = 0.10
    last_selected_track = None

    for point in points:
        time_sec = float(point["time"])
        active_segments = [
            segment for segment in speaker_segments
            if float(segment["start"]) <= time_sec < float(segment["end"])
        ]
        active_ids = {str(segment["speaker"]) for segment in active_segments}
        candidates = [track for track in point["tracks"] if track.get("speaker_id") in active_ids]
        chosen_track = None
        chosen_speaker = None
        reason = "no matched active-speaker face"

        if candidates:
            best_by_speaker = {}
            for track in candidates:
                speaker_id = str(track["speaker_id"])
                prior = best_by_speaker.get(speaker_id)
                if prior is None or float(track.get("mouth_aperture") or 0.0) > float(prior.get("mouth_aperture") or 0.0):
                    best_by_speaker[speaker_id] = track
            ranked_candidates = sorted(
                best_by_speaker.items(),
                key=lambda item: float(item[1].get("mouth_aperture") or 0.0),
                reverse=True,
            )
            if len(ranked_candidates) == 1:
                chosen_speaker, chosen_track = ranked_candidates[0]
                reason = "diarized speaker matched to visible face identity"
            else:
                top_aperture = float(ranked_candidates[0][1].get("mouth_aperture") or 0.0)
                next_aperture = float(ranked_candidates[1][1].get("mouth_aperture") or 0.0)
                if top_aperture - next_aperture >= 0.012:
                    chosen_speaker, chosen_track = ranked_candidates[0]
                    reason = "overlap resolved by stronger observed lip activity"
                elif current_speaker in best_by_speaker:
                    chosen_speaker = current_speaker
                    chosen_track = best_by_speaker[current_speaker]
                    reason = "overlap held on last confirmed speaker"

        switch_confirmed = False
        if chosen_speaker is not None and chosen_speaker != current_speaker:
            if pending_speaker != chosen_speaker:
                pending_speaker = chosen_speaker
                pending_since = time_sec
            elif pending_since is not None and time_sec - pending_since >= confirmation_duration - 1e-6:
                current_speaker = chosen_speaker
                pending_speaker = None
                pending_since = None
                switch_confirmed = True
        else:
            pending_speaker = None
            pending_since = None
            if chosen_speaker == current_speaker:
                chosen_track = next(
                    (track for track in candidates if track.get("speaker_id") == current_speaker),
                    chosen_track,
                )

        if current_speaker is None and chosen_speaker is not None and pending_since is not None:
            if time_sec - pending_since >= confirmation_duration - 1e-6:
                current_speaker = chosen_speaker
                pending_speaker = None
                pending_since = None
                switch_confirmed = True

        if chosen_track is None or chosen_speaker != current_speaker:
            selected_track = None
            face_confidence = None
            action = "HOLD"
            reason = "speaker uncertain or target face not visible; hold last confirmed crop"
        else:
            selected_track = int(chosen_track["track_id"])
            face_confidence = float(chosen_track.get("quality", 0.0))
            desired_x, desired_y = crop_for_track(chosen_track)
            if switch_confirmed:
                transition_start = time_sec
                transition_from = (current_x, current_y)
                transition_to = (desired_x, desired_y)
                action = "SWITCH_TO_SPEAKER"
                reason = f"confirmed diarized speaker {current_speaker}; visual identity matched"
            elif transition_start is not None and transition_from is not None:
                transition_to = (desired_x, desired_y)
                progress = min(1.0, max(0.0, (time_sec - transition_start) / transition_duration))
                current_x = transition_from[0] + (transition_to[0] - transition_from[0]) * progress
                current_y = transition_from[1] + (transition_to[1] - transition_from[1]) * progress
                action = "TRANSITION" if progress < 1.0 else "TRACK"
                if progress >= 1.0:
                    transition_start = None
                    transition_from = None
                    transition_to = None
            else:
                deadzone_x = max(28.0, max_x * 0.03)
                deadzone_y = max(28.0, max_y * 0.03)
                if abs(desired_x - current_x) > deadzone_x:
                    current_x += (desired_x - current_x) * 0.20
                if abs(desired_y - current_y) > deadzone_y:
                    current_y += (desired_y - current_y) * 0.18
                action = "TRACK" if selected_track == last_selected_track else "ACQUIRE"

            last_selected_track = selected_track

        current_x = max(0.0, min(max_x, current_x))
        current_y = max(0.0, min(max_y, current_y))
        point.update({
            "active_speaker": current_speaker,
            "speaker_confidence": None,
            "selected_track": selected_track if selected_track is not None else last_selected_track,
            "face_confidence": face_confidence,
            "crop_x": int(round(current_x)),
            "crop_y": int(round(current_y)),
            "x": int(round(current_x)),
            "y": int(round(current_y)),
            "target_id": selected_track if selected_track is not None else last_selected_track,
            "action": action,
            "reason": reason,
        })
        if not keyframes or abs(current_x - keyframes[-1]["x"]) > 1.0 or abs(current_y - keyframes[-1]["y"]) > 1.0:
            keyframes.append({"time": time_sec, "x": current_x, "y": current_y})
        timeline.append({
            "timestamp": round(time_sec, 3),
            "active_speaker": current_speaker,
            "speaker_confidence": None,
            "selected_track": point["selected_track"],
            "face_confidence": face_confidence,
            "crop_x": int(round(current_x)),
            "crop_y": int(round(current_y)),
            "action": action,
            "reason": reason,
        })

    if len(keyframes) > 1:
        sample_interval = 1.0 / max(1.0, float(info.get("sample_fps", 10.0)))
        held_keyframes = [keyframes[0]]
        for next_frame in keyframes[1:]:
            previous_frame = held_keyframes[-1]
            gap = next_frame["time"] - previous_frame["time"]
            if gap > sample_interval * 1.5:
                hold_start = previous_frame["time"] + sample_interval
                hold_end = next_frame["time"] - sample_interval
                if hold_start < next_frame["time"]:
                    held_keyframes.append({
                        "time": hold_start,
                        "x": previous_frame["x"],
                        "y": previous_frame["y"],
                    })
                if hold_end > hold_start:
                    held_keyframes.append({
                        "time": hold_end,
                        "x": previous_frame["x"],
                        "y": previous_frame["y"],
                    })
            held_keyframes.append(next_frame)
        keyframes = []
        for keyframe in held_keyframes:
            if keyframes and keyframe["time"] <= keyframes[-1]["time"]:
                keyframes[-1] = keyframe
            else:
                keyframes.append(keyframe)

    info.update({
        "scaled_w": int(round(scaled_w)),
        "scaled_h": int(round(scaled_h)),
        "max_x": max_x,
        "max_y": max_y,
        "keyframes": keyframes,
        "speaker_timeline": timeline,
    })
    print(f"  [Framing] Speaker-aware camera path; keyframes={len(keyframes)}; switches={sum(row['action'] == 'SWITCH_TO_SPEAKER' for row in timeline)}")
    return points, info


def _read_frame_for_alignment(cap, frame_index: int, fps: float, source_w: int, source_h: int):
    """Read one source frame for facial landmark alignment without retaining the video in memory."""
    current_position = cap.get(cv2.CAP_PROP_POS_FRAMES)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, current_position)
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_index} for face alignment.")
    return frame


def _write_framing_diagnostic(input_path: str, output_dir: str, points: list[dict],
                              info: dict) -> None:
    """Write sampled source frames with the detected target and crop rectangle."""
    _ensure_cv2()
    if cv2 is None or not points or not info:
        return
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(input_path)
    source_w, source_h = info["source_w"], info["source_h"]
    for point in points:
        cap.set(cv2.CAP_PROP_POS_FRAMES, point["frame"])
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        target_id = point.get("target_id")
        for track in point.get("tracks", []):
            x = int((track["cx"] - track["w"] / 2) * source_w)
            y = int((track["cy"] - track["h"] / 2) * source_h)
            w = int(track["w"] * source_w)
            h = int(track["h"] * source_h)
            color = (0, 255, 0) if track["track_id"] == target_id else (255, 180, 0)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 4)
            cv2.putText(frame, f"P{track['track_id']} {track.get('score', 0):.2f}",
                        (max(0, x), max(25, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        left = int(point["x"] / info["scaled_w"] * source_w)
        right = int((point["x"] + 1080) / info["scaled_w"] * source_w)
        top = int(point["y"] / info["scaled_h"] * source_h)
        bottom = int((point["y"] + 1920) / info["scaled_h"] * source_h)
        cv2.rectangle(frame, (left, top), (min(source_w - 1, right), min(source_h - 1, bottom)), (0, 0, 255), 4)
        cv2.putText(frame, f"TARGET P{target_id}", (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
        cv2.imwrite(os.path.join(output_dir, f"frame_{point['frame']:07d}.jpg"), frame)
    cap.release()


def _write_camera_path_diagnostic(output_dir: str, points: list[dict], info: dict) -> str:
    """Persist the camera state and movement reasons beside debug frame images."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "camera_path.json")
    report = {
        "detector": info.get("detector"),
        "sample_fps": info.get("sample_fps"),
        "switch_events": info.get("switch_events", []),
        "keyframes": info.get("keyframes", []),
        "timeline": [
            {
                "time": point.get("time"),
                "state": point.get("state"),
                "active_lock": point.get("active_lock"),
                "camera": [point.get("x"), point.get("y")],
                "camera_delta": point.get("camera_delta"),
                "last_camera_move_time": point.get("last_camera_move_time"),
                "challenger_id": point.get("challenger_id"),
                "challenger_since": point.get("challenger_since"),
                "scene_cut": point.get("scene_cut"),
                "reason": point.get("reason"),
            }
            for point in points
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path



def _detect_gaming_facecam(input_path: str) -> dict | None:
    """Find a stable facecam-style face near a source corner.

    Gaming videos commonly keep the facecam in a corner while the game occupies
    the rest of the frame. We only accept a corner face that persists across
    multiple samples, which prevents random in-game faces from triggering the
    layout.
    """
    _ensure_cv2()
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return None
    try:
        sw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        sh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        indices = [int(total * r) for r in (0.08, 0.24, 0.40, 0.56, 0.72, 0.88)]
        samples = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(total - 1, idx))
            ok, frame = cap.read()
            if ok and frame is not None:
                samples.append(frame)
        cap.release()
        if len(samples) < 3:
            return None
        from PIL import Image
        mtcnn = None
        try:
            from facenet_pytorch import MTCNN
            mtcnn = MTCNN(keep_all=True, device="cuda:0" if torch.cuda.is_available() else "cpu")
        except Exception:
            mtcnn = None
        haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        detections = []
        for frame in samples:
            scale = min(1.0, 960.0 / max(1, sw))
            sample = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
            faces = []
            if mtcnn is not None:
                boxes, probs = mtcnn.detect(Image.fromarray(cv2.cvtColor(sample, cv2.COLOR_BGR2RGB)), landmarks=False)
                if boxes is not None:
                    for box, prob in zip(boxes.tolist(), probs.tolist()):
                        if float(prob or 0) < 0.82:
                            continue
                        x1,y1,x2,y2=box[:4]
                        faces.append((x1/sample.shape[1], y1/sample.shape[0], x2/sample.shape[1], y2/sample.shape[0], float(prob)))
            else:
                gray=cv2.cvtColor(sample,cv2.COLOR_BGR2GRAY)
                for x,y,w,h in haar.detectMultiScale(gray,1.1,4,minSize=(30,30)):
                    faces.append((x/sample.shape[1],y/sample.shape[0],(x+w)/sample.shape[1],(y+h)/sample.shape[0],.65))
            # Facecam candidates are faces close to one of the four corners.
            for f in faces:
                cx=(f[0]+f[2])/2; cy=(f[1]+f[3])/2
                corner=min((cx,cy),(1-cx,cy),(cx,1-cy),(1-cx,1-cy),key=lambda p:p[0]**2+p[1]**2)
                corner_dist=(corner[0]**2+corner[1]**2)**0.5
                if corner_dist <= 0.42:
                    detections.append(f)
        if len(detections) < 3:
            return None
        # Cluster roughly by corner and choose the most persistent region.
        groups={"tl":[],"tr":[],"bl":[],"br":[]}
        for f in detections:
            cx=(f[0]+f[2])/2; cy=(f[1]+f[3])/2
            key=('t' if cy<0.5 else 'b')+('l' if cx<0.5 else 'r')
            groups[key].append(f)
        key, vals=max(groups.items(),key=lambda kv:len(kv[1]))
        if len(vals) < 3:
            return None
        cx=sum((v[0]+v[2])/2 for v in vals)/len(vals)
        cy=sum((v[1]+v[3])/2 for v in vals)/len(vals)
        fw=max(0.10,min(0.38,sum(v[2]-v[0] for v in vals)/len(vals)*4.2))
        fh=max(0.10,min(0.38,sum(v[3]-v[1] for v in vals)/len(vals)*4.2))
        # Expand around the face so the camera frame feels natural rather than a face crop.
        left=max(0.0,min(1.0,cx-fw/2)); top=max(0.0,min(1.0,cy-fh/2))
        if key.endswith('r'): left=max(0.0,1.0-fw)
        if key.startswith('b'): top=max(0.0,1.0-fh)
        return {"x":left,"y":top,"w":fw,"h":fh,"corner":key,"confidence":min(1.0,len(vals)/6.0)}
    except Exception as exc:
        cap.release()
        print(f"  [Gaming] Facecam detection unavailable: {type(exc).__name__}: {exc}")
        return None


def resize_gaming_adaptive(input_path: str, output_path: str, target_w: int = 1080, target_h: int = 1920) -> bool:
    """Create a stable gaming Short: gameplay-first composition + persistent facecam panel.

    The layout intentionally changes only when a persistent corner facecam is found.
    This avoids the jittery frame-by-frame switching common in naive gaming editors.
    """
    if os.getenv("CLIPPEDAI_SPLIT_SCREEN", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return resize_to_vertical_with_zoom(input_path, output_path, target_w=target_w, target_h=target_h)

    facecam = _detect_gaming_facecam(input_path)
    if not facecam:
        print("  [Gaming] No persistent corner facecam found; using stable gameplay framing.")
        return resize_to_vertical_with_zoom(input_path, output_path, zoom_factor=1.00, target_w=target_w, target_h=target_h)
    sw = 1920; sh = 1080
    try:
        probe = _run_hidden([FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", input_path], capture_output=True, text=True, check=True)
        parts=probe.stdout.strip().split('x'); sw=int(parts[0]); sh=int(parts[1])
    except Exception:
        pass
    # Facecam crop is expanded to a comfortable 16:9-ish region around the detected face.
    crop_w=max(320,min(sw,int(sw*facecam["w"])))
    crop_h=max(180,min(sh,int(crop_w*9/16)))
    cx=int((facecam["x"]+facecam["w"]/2)*sw); cy=int((facecam["y"]+facecam["h"]/2)*sh)
    fx=max(0,min(sw-crop_w,cx-crop_w//2)); fy=max(0,min(sh-crop_h,cy-crop_h//2))
    # Gameplay occupies the upper ~57%; facecam gets a large reaction panel below.
    game_h=1080; face_h=760; gap=28; top_y=28; face_y=top_y+game_h+gap
    # A soft blurred background makes the vertical canvas feel intentional rather than boxed.
    filter_complex=(
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},boxblur=18:2[bg];"
        f"[0:v]scale={target_w}:{game_h}:force_original_aspect_ratio=increase,crop={target_w}:{game_h}[game];"
        f"[0:v]crop={crop_w}:{crop_h}:{fx}:{fy},scale={target_w}:{face_h}:force_original_aspect_ratio=decrease,pad={target_w}:{face_h}:(ow-iw)/2:(oh-ih)/2[face];"
        f"[bg][game]overlay=0:{top_y}[g1];"
        f"[g1][face]overlay=0:{face_y}[v]"
    )
    cmd=[FFMPEG_BIN,"-i",input_path,"-filter_complex",filter_complex,"-map","[v]","-map","0:a?","-c:v","libx264","-preset","fast","-crf","22","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart","-y",output_path]
    try:
        _run_hidden(cmd,check=True,capture_output=True,text=True)
        print(f"  [Gaming] Adaptive gameplay + facecam layout · corner={facecam['corner']} confidence={facecam['confidence']:.2f}")
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 1024
    except subprocess.CalledProcessError as exc:
        print(f"  [Gaming] Adaptive layout failed; falling back to stable framing: {exc.stderr[-700:] if exc.stderr else exc}")
        return resize_to_vertical_with_zoom(input_path, output_path, zoom_factor=1.00, target_w=target_w, target_h=target_h)


def _camera_expression(series: list[dict], key: str, max_kf: int = 45,
                       preserve_snap_events: bool = True) -> str:
    """Build an FFmpeg camera expression from a thinned (time -> value) series."""
    if not series:
        return "(in_w-out_w)/2" if key == "x" else "(in_h-out_h)/2"

    # Thin the keyframe list so the resulting FFmpeg expression stays within its
    # length limits: merge consecutive entries within 1px of each other (letting
    # the later one extend the hold), then subsample if still too long.
    thinned = [series[0]]
    for kf in series[1:]:
        if (abs(kf[key] - thinned[-1][key]) >= 1.0
                or (preserve_snap_events and kf.get("state") == "SNAP")
                or kf.get("state") == "LOCKED"
                or kf.get("hold")):
            thinned.append(kf)
    if len(thinned) > max_kf:
        # Scene-cut/reacquisition points are semantic camera events. A simple
        # every-Nth reduction can drop a SNAP and make FFmpeg continue using a
        # stale crop for the rest of the shot. Keep those events (and explicit
        # locks) while sampling only ordinary follow points to fit the budget.
        if preserve_snap_events:
            critical = {
                i for i, kf in enumerate(thinned)
                if i in (0, len(thinned) - 1)
                or kf.get("state") in {"SNAP", "LOCKED"}
                or kf.get("hold")
            }
            if len(critical) > max_kf:
                raise ValueError(
                    f"camera path has {len(critical)} required hold/snap points "
                    f"but the FFmpeg expression budget is {max_kf}"
                )
            optional = [i for i in range(len(thinned)) if i not in critical]
            slots = max_kf - len(critical)
            if slots >= len(optional):
                sampled = optional
            elif slots <= 0:
                sampled = []
            elif slots == 1:
                sampled = [optional[len(optional) // 2]]
            else:
                sampled = [
                    optional[round(i * (len(optional) - 1) / (slots - 1))]
                    for i in range(slots)
                ]
            thinned = [thinned[i] for i in sorted(critical.union(sampled))]
        else:
            # Keep the established normal-camera interpolation unchanged.
            step = max(1, len(thinned) // max_kf)
            reduced = thinned[::step]
            if reduced[-1] is not thinned[-1]:
                reduced.append(thinned[-1])
            thinned = reduced

    expression = f"{thinned[0][key]:.2f}"
    for start, end in zip(thinned, thinned[1:]):
        duration = max(0.200, end["time"] - start["time"])
        delta = end[key] - start[key]
        if abs(delta) <= 0.5:
            continue
        if preserve_snap_events and end.get("state") == "SNAP":
            expression += f"+({delta:.2f})*gte(t\\,{end['time']:.3f})"
        else:
            expression += f"+({delta:.2f})*clip((t-{start['time']:.3f})/{duration:.3f}\\,0\\,1)"
    return expression


def _cluster_by_depth(points: list[dict], clusters: int = 2) -> list[list[dict]]:
    """Group face observations into `clusters` persistent people by horizontal position.

    Track ids churn constantly as MTCNN re-detects the same face, so grouping by
    id is useless here. A 1-D k-means over the x coordinate recovers the stable
    left/right arrangement of a multi-person frame.
    """
    observations = []
    for point in points:
        for track in point.get("tracks", []):
            observations.append({"time": point["time"], "cx": track["cx"],
                                 "cy": track["cy"], "w": track["w"], "h": track["h"],
                                 "score": track.get("score", 0.5),
                                 "scene_id": point.get("scene_id", 0)})
    if not observations:
        return []

    xs = [o["cx"] for o in observations]
    low, high = min(xs), max(xs)
    if high - low < 0.12:
        return [observations]  # effectively one person on screen

    centroids = [low, high] if clusters == 2 else [
        low + (high - low) * i / (clusters - 1) for i in range(clusters)
    ]
    for _ in range(25):
        buckets: list[list[dict]] = [[] for _ in centroids]
        for obs in observations:
            idx = min(range(len(centroids)),
                      key=lambda i: abs(obs["cx"] - centroids[i]))
            buckets[idx].append(obs)
        moved = False
        for i, bucket in enumerate(buckets):
            if not bucket:
                continue
            centre = sum(o["cx"] for o in bucket) / len(bucket)
            if abs(centre - centroids[i]) > 1e-4:
                centroids[i] = centre
                moved = True
        if not moved:
            break

    buckets = [[] for _ in centroids]
    for obs in observations:
        idx = min(range(len(centroids)), key=lambda i: abs(obs["cx"] - centroids[i]))
        buckets[idx].append(obs)
    return [b for b in buckets if b]


def _panel_crop_position(obs: dict, info: dict, panel_w: int, panel_h: int) -> tuple[float, float]:
    """Crop origin that places one person's face in the upper third of a panel."""
    scaled_w = float(info.get("scaled_w") or panel_w)
    scaled_h = float(info.get("scaled_h") or panel_h)
    max_x = max(0.0, scaled_w - panel_w)
    max_y = max(0.0, scaled_h - panel_h)

    face_cx = obs["cx"] * scaled_w
    face_cy = obs["cy"] * scaled_h
    face_w = max(1.0, obs["w"] * scaled_w)
    face_h = max(1.0, obs["h"] * scaled_h)

    x = face_cx - panel_w * 0.5
    y = face_cy - panel_h * 0.32

    # Keep a margin around the face so it never touches a panel edge.
    margin_x = max(28.0, face_w * 0.75)
    margin_y = max(20.0, face_h * 0.90)
    safe_min_x = face_cx + face_w * 0.5 + margin_x - panel_w
    safe_max_x = face_cx - face_w * 0.5 - margin_x
    if safe_min_x <= safe_max_x:
        x = max(safe_min_x, min(safe_max_x, x))
    safe_min_y = face_cy + face_h * 0.5 + margin_y - panel_h
    safe_max_y = face_cy - face_h * 0.5 - margin_y
    if safe_min_y <= safe_max_y:
        y = max(safe_min_y, min(safe_max_y, y))

    return max(0.0, min(max_x, x)), max(0.0, min(max_y, y))


def _locked_scene_series(observations: list[dict], info: dict,
                         panel_w: int, panel_h: int) -> list[dict]:
    """Build a camera series that holds still within each shot.

    A single constant crop cannot frame the right person across an edit, so the
    panel is pinned per scene: static for the length of each shot, re-acquiring
    only when the scene changes. That is what "locked" has to mean on cut-heavy
    source material - it must not drift *inside* a shot.
    """
    by_scene: dict[Any, list[dict]] = {}
    for obs in observations:
        by_scene.setdefault(obs.get("scene_id", 0), []).append(obs)

    series = []
    for scene_id in sorted(by_scene, key=lambda s: min(o["time"] for o in by_scene[s])):
        group = by_scene[scene_id]
        positions = [_panel_crop_position(o, info, panel_w, panel_h) for o in group]
        # Median position of the shot resists a single bad frame and keeps the
        # panel from creeping over the shot.
        xs = sorted(p[0] for p in positions)
        ys = sorted(p[1] for p in positions)
        mid = len(positions) // 2
        series.append({"time": min(o["time"] for o in group),
                       "x": xs[mid], "y": ys[mid]})
    return series


def _tracked_scene_series(observations: list[dict], info: dict,
                          panel_w: int, panel_h: int) -> list[dict]:
    """Build a camera series that follows a person, re-acquiring at scene cuts."""
    series = []
    for obs in sorted(observations, key=lambda o: o["time"]):
        x, y = _panel_crop_position(obs, info, panel_w, panel_h)
        series.append({"time": obs["time"], "x": x, "y": y})

    # Collapse near-duplicate samples so the expression stays short; a scene
    # change always survives because it moves the crop by a visible margin.
    deduped: list[dict] = []
    for entry in series:
        if deduped and abs(entry["x"] - deduped[-1]["x"]) < 0.75 \
                and abs(entry["y"] - deduped[-1]["y"]) < 0.75:
            continue
        deduped.append(entry)
    return deduped


# Last dual-person split plan, retained so the layout can be asserted by the
# regression checks without paying for another detection pass.
LAST_SPLIT_PLAN: dict = {}


def _locked_follow_series(keyframes: list[dict], sample_fps: float = 5.0,
                          window_s: float = 2.0, hold_px: float = 8.0) -> list[dict]:
    """Turn a camera path into a steady, slow-following one.

    A pure step-hold ("only move when it drifts far enough") looks locked but
    abandons the speaker as soon as they move inside a shot - the panel drifts
    off them. Low-pass filtering is what actually reads as a tripod: the camera
    still follows, just without the jitter, and it never snaps.

    The path is first resampled onto a uniform grid, because a keyframe list is
    sparse and uneven; averaging sparse points directly would bias toward
    wherever the tracker happened to emit most often.
    """
    if not keyframes:
        return []

    ordered = sorted(keyframes, key=lambda k: k["time"])
    if any(point.get("state") == "SNAP" for point in ordered):
        # Smooth each shot independently. Carry each reacquisition point through
        # at its exact timestamp so neither the old shot nor its smoothing
        # window drags the camera across a scene cut.
        result: list[dict] = []
        segment: list[dict] = []
        for point in ordered:
            if point.get("state") == "SNAP":
                if segment:
                    result.extend(_locked_follow_series(
                        segment, sample_fps=sample_fps,
                        window_s=window_s, hold_px=hold_px,
                    ))
                result.append(dict(point))
                segment = [{
                    key: value for key, value in point.items()
                    if key not in {"state", "reason", "hold"}
                }]
            else:
                segment.append(point)
        if segment:
            result.extend(_locked_follow_series(
                segment, sample_fps=sample_fps,
                window_s=window_s, hold_px=hold_px,
            ))
        return sorted(result, key=lambda point: point["time"])

    start_time = float(ordered[0]["time"])
    duration = float(ordered[-1]["time"]) - start_time
    if duration <= 0:
        return [{"time": start_time, "x": ordered[0]["x"], "y": ordered[0]["y"]}]

    step = 1.0 / max(0.5, sample_fps)
    samples = int(duration / step) + 1

    grid_x, grid_y = [], []
    index = 0
    current = ordered[0]
    for i in range(samples + 1):
        t = start_time + min(duration, i * step)
        while index < len(ordered) and ordered[index]["time"] <= t + 1e-9:
            current = ordered[index]
            index += 1
        grid_x.append(float(current["x"]))
        grid_y.append(float(current["y"]))

    # Centred moving average, tapered at the edges so the ends are not dragged
    # towards the middle of the clip.
    half = max(1, int(round(window_s / 2.0 / step)))
    smooth_x, smooth_y = [], []
    n = len(grid_x)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        span = hi - lo
        weight_total = 0.0
        sx = sy = 0.0
        for j in range(lo, hi):
            # Triangular taper: centre of the window counts most.
            w = 1.0 - abs((j - i) / max(1, half + 1))
            sx += grid_x[j] * w
            sy += grid_y[j] * w
            weight_total += w
        smooth_x.append(sx / weight_total)
        smooth_y.append(sy / weight_total)

    out: list[dict] = []
    for i in range(n):
        t = start_time + min(duration, i * step)
        if not out or abs(smooth_x[i] - out[-1]["x"]) >= hold_px \
                or abs(smooth_y[i] - out[-1]["y"]) >= hold_px:
            out.append({"time": t, "x": smooth_x[i], "y": smooth_y[i]})
    if not out:
        out = [{"time": 0.0, "x": smooth_x[0], "y": smooth_y[0]}]
    return out


def _hold_missing_split_people(output_path: str, panel_h: int,
                               target_w: int, target_h: int,
                               hold_after_s: float = 0.20,
                               max_hold_s: float = 0.60) -> None:
    """Briefly hold a split panel across a short face-detector gap.

    Verify face presence in the rendered panel itself. Source detection can find
    faces in posters or screenshots, while a held crop can point at background
    after a camera cut. Do not seed missing frames with a future face image or
    freeze a panel across a sustained loss: only bridge a short gap after a
    face-bearing sample, then let the live camera path show its current frame.
    """
    _ensure_cv2()
    if cv2 is None:
        raise RuntimeError("OpenCV is required to hold missing split-screen panels")
    from facenet_pytorch import MTCNN
    import torch
    from PIL import Image

    source = cv2.VideoCapture(output_path)
    if not source.isOpened():
        raise RuntimeError("could not reopen split-screen render for panel holds")
    fps = float(source.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(source.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or frame_count <= 0:
        source.release()
        raise RuntimeError("split-screen render has invalid frame timing")

    sample_step = max(1, int(round(fps / 5.0)))
    sample_frames = list(range(0, frame_count, sample_step))
    if not sample_frames or sample_frames[-1] != frame_count - 1:
        sample_frames.append(frame_count - 1)
    detector = MTCNN(keep_all=True, device="cuda:0" if torch.cuda.is_available() else "cpu")
    panel_states = {"top": [], "bottom": []}
    sample_images: list[tuple[str, int, Image.Image]] = []
    scale = min(1.0, 640.0 / max(1, target_w))
    for index in sample_frames:
        source.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = source.read()
        if not ok or frame is None:
            source.release()
            raise RuntimeError(f"could not sample split-screen frame {index}")
        for name, y1, y2 in (("top", 0, panel_h), ("bottom", panel_h, target_h)):
            panel = frame[y1:y2, 0:target_w]
            if scale < 1.0:
                panel = cv2.resize(panel, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            sample_images.append((name, index, Image.fromarray(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB))))
    source.release()

    visible_by_index = {"top": {}, "bottom": {}}
    for batch_start in range(0, len(sample_images), 8):
        batch = sample_images[batch_start:batch_start + 8]
        boxes_batch, probabilities_batch = detector.detect(
            [row[2] for row in batch], landmarks=False
        )
        for (name, index, _), boxes, probabilities in zip(batch, boxes_batch, probabilities_batch):
            visible = False
            if boxes is not None and probabilities is not None:
                for box, probability in zip(boxes.tolist(), probabilities.tolist()):
                    x1, y1, x2, y2 = box[:4]
                    if float(probability or 0.0) >= 0.84 and min(x2 - x1, y2 - y1) >= 48:
                        visible = True
                        break
            visible_by_index[name][index] = visible

    source = cv2.VideoCapture(output_path)
    if not source.isOpened():
        raise RuntimeError("could not reopen split-screen render for panel holds")
    role_data = []
    for name, y1, y2 in (("top", 0, panel_h), ("bottom", panel_h, target_h)):
        states = [(index, visible_by_index[name][index]) for index in sample_frames]
        first_visible = next((index for index, visible in states if visible), None)
        if first_visible is None:
            source.release()
            raise RuntimeError(f"split-screen {name} panel has no rendered face")
        source.set(cv2.CAP_PROP_POS_FRAMES, first_visible)
        ok, frame = source.read()
        if not ok or frame is None:
            source.release()
            raise RuntimeError(f"could not read first visible {name} split panel")
        role_data.append({
            "name": name, "y1": y1, "y2": y2, "states": states,
            "state_index": 0, "last_visible": None,
            "last_panel": None,
            "held_frames": 0, "visible_samples": sum(visible for _, visible in states),
        })

    source.set(cv2.CAP_PROP_POS_FRAMES, 0)
    temp_video = str(Path(output_path).with_suffix(".split_hold.mp4"))
    muxed_video = str(Path(output_path).with_suffix(".split_mux.mp4"))
    writer = cv2.VideoWriter(
        temp_video, cv2.VideoWriter_fourcc(*"mp4v"), fps, (target_w, target_h)
    )
    if not writer.isOpened():
        source.release()
        raise RuntimeError("could not create split-screen panel-hold video")

    try:
        frame_index = 0
        while True:
            ok, frame = source.read()
            if not ok or frame is None:
                break
            time_sec = frame_index / fps
            for role in role_data:
                states = role["states"]
                while role["state_index"] + 1 < len(states) and \
                        states[role["state_index"] + 1][0] <= frame_index:
                    role["state_index"] += 1
                sampled_frame, sampled_visible = states[role["state_index"]]
                face_sample = bool(sampled_visible and frame_index == sampled_frame)
                y1, y2 = role["y1"], role["y2"]
                if face_sample:
                    role["last_panel"] = frame[y1:y2, 0:target_w].copy()
                    role["last_visible"] = time_sec
                elif _split_panel_hold_for_gap(
                    role["last_visible"], time_sec, hold_after_s, max_hold_s
                ):
                    frame[y1:y2, 0:target_w] = role["last_panel"]
                    role["held_frames"] += 1
            writer.write(frame)
            frame_index += 1
    finally:
        source.release()
        writer.release()

    if frame_index != frame_count:
        for temp in (temp_video, muxed_video):
            try:
                os.remove(temp)
            except OSError:
                pass
        raise RuntimeError(f"split panel hold decoded {frame_index}/{frame_count} frames")

    cmd = [FFMPEG_BIN, "-hide_banner", "-v", "error", "-y",
           "-i", temp_video, "-i", output_path,
           "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264",
           "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", muxed_video]
    try:
        _run_hidden(cmd, check=True, capture_output=True, text=True)
        os.replace(muxed_video, output_path)
    finally:
        for temp in (temp_video, muxed_video):
            try:
                os.remove(temp)
            except OSError:
                pass
    for role in role_data:
        held_s = role["held_frames"] / fps
        print(f"  [Framing] Split panel {role['name']}: visual face present in "
              f"{role['visible_samples']}/{len(role['states'])} samples; "
              f"held/fill {held_s:.2f}s")


def _split_panel_hold_for_gap(last_visible_s: float | None, time_sec: float,
                              hold_after_s: float = 0.20,
                              max_hold_s: float = 0.60) -> bool:
    """Return whether a last-face frame may bridge this brief detector gap."""
    if last_visible_s is None:
        return False
    age = time_sec - last_visible_s
    return max(0.0, hold_after_s - 1e-6) <= age <= max_hold_s


def _compose_dual_person_split(source_path: str, output_path: str,
                               target_w: int = 1080, target_h: int = 1920) -> bool:
    """Build a dual-panel layout with one person locked above a tracked person.

    The previous implementation re-split an already-framed single-person clip
    down the middle, which halved one person and filled the other panel with
    background. This frames each detected person into their own panel instead:
    the dominant speaker is anchored in the top panel for the whole clip and the
    second person is followed with the same smoothed camera path used elsewhere.
    """
    panel_h = max(2, target_h // 2)
    if panel_h % 2:
        panel_h += 1

    # The zoom matters, and it must be identical for every detection pass.
    # With zoom 1 the canvas is only as wide as it is tall (~1707px for a 16:9
    # source), leaving too little horizontal travel to centre two people and
    # pushing each subject to the panel edge. Zoom 2 gives the same ~3413px
    # canvas the single-panel path uses. The filter graph below scales to
    # scaled_w/scaled_h, so a mismatch here would render keyframe coordinates
    # that mean something entirely different.
    panel_zoom = 2.0

    # First pass: find the two speakers and their horizontal slots.
    points, info = _detect_person_trajectory(source_path, target_w, panel_h, panel_zoom)
    scaled_w = int(round(info.get("scaled_w") or target_w))
    scaled_h = int(round(info.get("scaled_h") or panel_h))

    clusters = _cluster_by_depth(points, 2) if points else []
    centroids: tuple[float, ...] | None = None
    if len(clusters) >= 2:
        clusters.sort(key=lambda b: sum(o["cx"] for o in b) / len(b))
        centroids = (sum(o["cx"] for o in clusters[0]) / len(clusters[0]),
                     sum(o["cx"] for o in clusters[1]) / len(clusters[1]))

    if centroids is not None and points:
        # A dual panel can only show two different people when two people are on
        # screen. On single-shooter or mostly-solo footage the empty panel reads
        # as a bug, so measure the overlap and hand the clip back to the normal
        # tracked layout when it is too rare to carry a two-person frame.
        def _role_of(cx: float) -> int:
            return 0 if abs(cx - centroids[0]) <= abs(cx - centroids[1]) else 1

        both = sum(1 for p in points if len({_role_of(t["cx"]) for t in p.get("tracks", [])}) == 2)
        overlap = both / max(1, len(points))
        if overlap < 0.40:
            print(f"  [Framing] Split-screen skipped: both people share the frame in only "
                  f"{overlap:.0%} of shots; using the single tracked layout instead.")
            return False

    if centroids is None:
        raise RuntimeError(
            "split-screen requires two visually separable people; "
            "the detector found fewer than two stable horizontal subject groups"
        )
    else:
        # Each panel now runs the full tracking pipeline against its own person,
        # so framing, loss handling and the face clamp behave exactly as they do
        # for a single-panel clip.
        #
        # The zoom is shared with the clustering pass above; see panel_zoom.
        panel_zoom = 2.0
        # Aim each panel at its own speaker's typical position, so the opening
        # frames are framed on the right person before anything is detected.
        top_hint = (centroids[1], sum(o["cy"] for o in clusters[1]) / len(clusters[1]))
        bottom_hint = (centroids[0], sum(o["cy"] for o in clusters[0]) / len(clusters[0]))

        _, top_info = _detect_person_trajectory(source_path, target_w, panel_h, panel_zoom,
                                                role_centroids=centroids, role_index=1,
                                                hold_on_loss=True, initial_hint=top_hint)
        _, bottom_info = _detect_person_trajectory(source_path, target_w, panel_h, panel_zoom,
                                                   role_centroids=centroids, role_index=0,
                                                   hold_on_loss=True, initial_hint=bottom_hint)

        # Both panels crop from one shared canvas. If the passes above disagree
        # with the filter graph about that canvas, every keyframe coordinate is
        # wrong, so fail loudly instead of rendering a plausible-looking clip.
        for label, role_info in (("top", top_info), ("bottom", bottom_info)):
            rw = int(round(role_info.get("scaled_w") or 0))
            rh = int(round(role_info.get("scaled_h") or 0))
            if (rw, rh) != (scaled_w, scaled_h):
                raise RuntimeError(
                    f"split-screen canvas mismatch in {label} role: "
                    f"detection used {rw}x{rh}, filter graph uses {scaled_w}x{scaled_h}"
                )

        # The top panel reads as a locked-off camera: it follows its speaker, but
        # slowly and without jitter, while the bottom panel keeps the responsive
        # per-frame tracking. That difference is what makes the top look locked.
        top_kf = _locked_follow_series(top_info.get("keyframes", []),
                                       sample_fps=5.0, window_s=2.0, hold_px=8.0)
        bottom_kf = bottom_info.get("keyframes", [])

        if not top_kf:
            top_kf = [{"time": 0.0, "x": (scaled_w - target_w) / 2.0,
                       "y": (scaled_h - panel_h) / 2.0}]
        if not bottom_kf:
            bottom_kf = [{"time": 0.0, "x": (scaled_w - target_w) / 2.0,
                          "y": (scaled_h - panel_h) / 2.0}]

        top_x_expr = _camera_expression(top_kf, "x", max_kf=30)
        top_y_expr = _camera_expression(top_kf, "y", max_kf=30)
        bottom_x = _camera_expression(bottom_kf, "x")
        bottom_y = _camera_expression(bottom_kf, "y")

        divider = panel_h - 2
        vf = (f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,setsar=1,split=2[a][b];"
              f"[a]crop={target_w}:{panel_h}:{top_x_expr}:{top_y_expr},setsar=1[p1];"
              f"[b]crop={target_w}:{panel_h}:{bottom_x}:{bottom_y},setsar=1[p2];"
              f"[p1][p2]vstack=inputs=2,"
              f"drawbox=x=0:y={divider}:w={target_w}:h=4:color=black@0.55:t=fill[v]")
        top_note = (f"top locked ({len(top_kf)} holds), bottom tracked "
                    f"({len(bottom_kf)} keyframes)")

    # Retained for the split-screen regression checks: the exact camera plan that
    # produced this render, so the layout can be asserted without re-detecting.
    global LAST_SPLIT_PLAN
    LAST_SPLIT_PLAN = {
        "panel_w": target_w, "panel_h": panel_h,
        "scaled_w": scaled_w, "scaled_h": scaled_h,
        "centroids": centroids,
        "top_keyframes": top_kf if centroids else [],
        "bottom_keyframes": bottom_kf if centroids else [],
    }

    cmd = [FFMPEG_BIN, "-i", source_path, "-filter_complex", vf,
           "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "fast", "-crf", "22",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", "-y", output_path]
    _run_hidden(cmd, check=True, capture_output=True, text=True)

    ok = os.path.isfile(output_path) and os.path.getsize(output_path) > 1024
    if ok:
        if centroids is not None:
            _hold_missing_split_people(output_path, panel_h, target_w, target_h)
        print(f"  [Framing] Split-screen: {top_note}, panels {target_w}x{panel_h}")
    return ok


def _split_screen_enabled() -> bool:
    return os.getenv("CLIPPEDAI_SPLIT_SCREEN", "0").strip().lower() in {"1", "true", "yes", "on"}


def _validate_camera_render(input_path: str, output_path: str,
                            target_w: int, target_h: int) -> bool:
    """Reject a camera render that is incomplete or has lost its media streams."""
    def probe(path: str) -> dict:
        result = _run_hidden(
            [FFPROBE_BIN, "-v", "error", "-count_frames", "-show_entries",
             "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames",
             "-of", "json", path],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout or "{}")

    try:
        source = probe(input_path)
        rendered = probe(output_path)
        source_streams = source.get("streams", [])
        streams = rendered.get("streams", [])
        source_video = next((s for s in source_streams if s.get("codec_type") == "video"), None)
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        source_audio = next((s for s in source_streams if s.get("codec_type") == "audio"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not video:
            raise ValueError("render has no video stream")
        actual_size = (int(video.get("width", 0)), int(video.get("height", 0)))
        if actual_size != (target_w, target_h):
            raise ValueError(f"render dimensions are {actual_size[0]}x{actual_size[1]}")
        if video.get("codec_name") != "h264":
            raise ValueError(f"render video codec is {video.get('codec_name')!r}, expected h264")
        try:
            frame_count = int(video.get("nb_read_frames", 0))
        except (TypeError, ValueError):
            frame_count = 0
        if frame_count <= 0:
            raise ValueError("render has no decodable video frames")
        source_duration = float(source.get("format", {}).get("duration", 0.0))
        output_duration = float(rendered.get("format", {}).get("duration", 0.0))
        duration_tolerance = max(1.0, source_duration * 0.03)
        if source_duration <= 0 or output_duration <= 0 or abs(source_duration - output_duration) > duration_tolerance:
            raise ValueError(
                f"duration changed from {source_duration:.2f}s to {output_duration:.2f}s"
            )
        if source_audio and (not audio or audio.get("codec_name") != "aac"):
            raise ValueError("source audio is missing from the AAC camera render")
        print(f"  [Framing] Render verified: {actual_size[0]}x{actual_size[1]}, "
              f"{frame_count} frames, {output_duration:.2f}s, "
              f"audio={'AAC' if audio else 'none'}")
        return True
    except Exception as exc:
        print(f"  [ERROR] Camera render validation failed: {type(exc).__name__}: {exc}")
        return False


def _resize_with_blurred_background(input_path: str, output_path: str,
                                    target_w: int, target_h: int) -> bool:
    """Keep the full source frame visible when no reliable subject can be tracked."""
    filter_complex = (
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},boxblur=18:2[bg];"
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2,setsar=1[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[v]"
    )
    command = [
        FFMPEG_BIN, "-i", input_path, "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
        "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-y", output_path,
    ]
    try:
        _run_hidden(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr_tail = exc.stderr[-800:] if exc.stderr else str(exc)
        print(f"  [ERROR] Full-frame vertical resize failed: {stderr_tail}")
        return False
    return (
        os.path.isfile(output_path)
        and os.path.getsize(output_path) > 1024
        and _validate_camera_render(input_path, output_path, target_w, target_h)
    )


def resize_to_vertical_with_zoom(input_path: str, output_path: str, zoom_factor: float = 1.00,
                                 target_w: int = 1080, target_h: int = 1920) -> bool:
    """Create a 1080x1920 output with tracked, smoothed person-aware framing.

    With the split-screen toggle on, each panel gets its own camera path over the
    source rather than one framed clip being cut in half, so the layout changes
    and the framing quality does not.
    """
    split_screen = _split_screen_enabled()

    if split_screen:
        # Try the dual-panel layout first. Doing the single-panel detection up
        # front cost a full extra detection pass per clip for a result that
        # split mode discards.
        try:
            if _compose_dual_person_split(input_path, output_path, target_w, target_h):
                return _validate_camera_render(input_path, output_path, target_w, target_h)
            print("  [ERROR] Split-screen did not produce a valid two-person layout")
            return False
        except subprocess.CalledProcessError as exc:
            stderr_tail = exc.stderr[-500:] if exc.stderr else str(exc)
            print(f"  [ERROR] Split-screen composition failed: {stderr_tail}")
            return False
        except Exception as exc:
            print(f"  [ERROR] Split-screen composition failed: {type(exc).__name__}: {exc}")
            return False

    zoom = max(1.0, min(1.15, float(zoom_factor)))
    points, info = _detect_person_trajectory(input_path, target_w, target_h, zoom)
    try:
        if not points or not info.get("keyframes"):
            print("  [Framing] No reliable subject trajectory; preserving the full frame over a blurred background.")
            return _resize_with_blurred_background(input_path, output_path, target_w, target_h)

        def camera_expression(key: str) -> str:
            keyframes = info.get("keyframes", [])
            return _camera_expression(
                keyframes, key, max_kf=55, preserve_snap_events=False
            )

        scaled_w = int(round(target_w * zoom))
        scaled_h = int(round(target_h * zoom))
        crop_x = "(in_w-out_w)/2"
        crop_y = "(in_h-out_h)/2"
        if points and info:
            scaled_w = int(round(info["scaled_w"]))
            scaled_h = int(round(info["scaled_h"]))
            crop_x = camera_expression("x")
            crop_y = camera_expression("y")

        vf = (f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
              f"crop@vertical_crop={target_w}:{target_h}:{crop_x}:{crop_y}")
        debug_dir = os.getenv("CLIPPEDAI_FRAMING_DEBUG_DIR")
        if debug_dir and points:
            _write_framing_diagnostic(input_path, debug_dir, points, info)
            diagnostic_path = _write_camera_path_diagnostic(debug_dir, points, info)
            print(f"  [Framing] Camera path diagnostics: {diagnostic_path}")
        print(f"  [Framing] Tracked person; samples={len(points)}; "
              f"switches={len(info.get('switch_events', []))}; keyframes={len(info.get('keyframes', []))}")
        cmd = [FFMPEG_BIN, "-i", input_path, "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", output_path]
        _run_hidden(cmd, check=True, capture_output=True, text=True)
        return (os.path.isfile(output_path) and os.path.getsize(output_path) > 1024
                and _validate_camera_render(input_path, output_path, target_w, target_h))
    except subprocess.CalledProcessError as e:
        stderr_tail = e.stderr[-800:] if e.stderr else str(e)
        print(f"  [ERROR] Camera-tracked vertical resize FAILED.")
        print(f"  [ERROR] FFmpeg stderr: {stderr_tail}")
        # Do NOT silently fall back to a centered crop — that would produce visually
        # incorrect output (background between people) without any visible signal.
        # Report the failure clearly so the caller can decide what to do.
        print(f"  [ERROR] Camera render aborted. No centered-crop fallback will be used.")
        print(f"  [ERROR] Check the camera_expression output or reduce clip length.")
        return False
def calculate_engagement_score(
    clip,
    transcription,
):
    """
    Calculate a custom engagement score.
    Higher scores indicate more engaging content.
    """

    clip_words = [
        w
        for w in transcription.get_word_info()
        if w["start_time"] >= clip.start_time
        and w["end_time"] <= clip.end_time
    ]

    if not clip_words:
        return 0.0

    duration = (
        clip.end_time
        - clip.start_time
    )

    word_count = len(clip_words)

    word_density = (
        word_count / duration
        if duration > 0
        else 0
    )

    engagement_words = 0

    for word_info in clip_words:

        word = word_info["word"]

        if (
            any(char.isdigit() for char in word)
            or "$" in word
            or "!" in word
        ):

            engagement_words += 1

    # Normalize to 0-1
    word_density_score = min(
        word_density / 3.0,
        1.0
    )

    engagement_ratio = (
        engagement_words / word_count
        if word_count > 0
        else 0
    )

    duration_score = min(
        duration / 75.0,
        1.0
    )

    engagement_score = (
        word_density_score * 0.45
        + engagement_ratio * 0.30
        + duration_score * 0.25
    )

    return engagement_score


# =========================================================
# LEGACY PIPELINE (disabled — kept for reference only)
# =========================================================

# =========================================================
# NEW AI-POWERED PIPELINE (Ollama / Qwen3 + Shorts style)
# =========================================================


def find_input_videos_auto() -> List[Tuple[str, Optional[str]]]:
    """Scan INPUT_DIR for supported videos and matching cached transcriptions.

    Returns list of (video_abspath, transcription_abspath_or_None).
    Auto mode: match by basename prefix `{stem}_transcription.pkl`.
    Raises FileNotFoundError if no supported videos exist.
    """
    input_dir_abs = os.path.abspath(INPUT_DIR)
    files = os.listdir(input_dir_abs) if os.path.isdir(input_dir_abs) else []
    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    videos = sorted([f for f in files if os.path.splitext(f)[1].lower() in video_extensions])
    if not videos:
        raise FileNotFoundError(
            f"No supported video found in input directory '{input_dir_abs}'. "
            "Place a video in the input/ folder and run again."
        )
    pickles = {f for f in files if f.endswith("_transcription.pkl")}
    result: List[Tuple[str, Optional[str]]] = []
    for vf in videos:
        stem = os.path.splitext(vf)[0]
        expected_pkl = f"{stem}_transcription.pkl"
        vpath = os.path.join(input_dir_abs, vf)
        if expected_pkl in pickles:
            result.append((vpath, os.path.join(input_dir_abs, expected_pkl)))
        else:
            result.append((vpath, None))
    return result


def _dedupe_candidates(clips, min_overlap_gap: float = 12.0):
    """Remove boundary-near duplicates while retaining meaningful trims."""
    seen = []
    for c in clips:
        bad = False
        for s in seen:
            if abs(c.start_time - s.start_time) < min_overlap_gap:
                c_end = getattr(c, "end_time", None)
                s_end = getattr(s, "end_time", None)
                if c_end is None or s_end is None or abs(c_end - s_end) < min_overlap_gap:
                    bad = True
                    break
        if not bad:
            seen.append(c)
    return seen


def create_candidate_clip_finder():
    """Limit generated Qwen candidates to the job's requested Short duration range."""
    from clipsai import ClipFinder

    minimum = max(5, min(60, int(MIN_CLIP_DURATION)))
    maximum = max(minimum, min(60, int(MAX_CLIP_DURATION)))
    return ClipFinder(
        min_clip_duration=minimum,
        max_clip_duration=maximum,
        cutoff_policy="high",
    )


def _add_sentence_aligned_prefix_candidates(clips, transcription):
    """Add one shorter, sentence-aligned opening for overlong topic candidates.

    ClipsAI's semantic topic span can contain a strong opening joke followed by
    unrelated host commentary. A Qwen-judged prefix lets the selector assess the
    earlier complete moment without inventing timestamps or cutting mid-sentence.
    """
    minimum = max(5, min(60, int(MIN_CLIP_DURATION)))
    maximum = max(minimum, min(60, int(MAX_CLIP_DURATION)))
    target_duration = min(maximum, max(minimum, int(PREFERRED_MIN_CLIP_DURATION) + 5))
    tolerance = max(2.0, min(5.0, target_duration * 0.10))

    try:
        sentence_rows = transcription.get_sentence_info()
    except Exception:
        return list(clips)
    if not sentence_rows:
        return list(clips)

    Clip = _clip_class()
    result = list(clips)
    variants = []
    for base in clips:
        try:
            start_time = float(base.start_time)
            base_end_time = float(base.end_time)
            start_char = int(base.start_char)
            base_end_char = int(base.end_char)
        except (AttributeError, TypeError, ValueError):
            continue
        if base_end_time - start_time <= target_duration + tolerance:
            continue

        starts = []
        for row in sentence_rows:
            try:
                row_start = float(row["start_time"])
                row_start_char = int(row["start_char"])
            except (KeyError, TypeError, ValueError):
                continue
            if row_start_char == start_char and abs(row_start - start_time) <= 1.0:
                starts.append((row_start, row_start_char))
        if not starts:
            continue
        sentence_start, sentence_start_char = min(starts, key=lambda pair: abs(pair[0] - start_time))

        ends = []
        for row in sentence_rows:
            try:
                row_end = float(row["end_time"])
                row_end_char = int(row["end_char"])
            except (KeyError, TypeError, ValueError):
                continue
            duration = row_end - sentence_start
            if row_end_char <= base_end_char and sentence_start_char < row_end_char and minimum <= duration <= maximum:
                ends.append((row_end, row_end_char, duration))
        if not ends:
            continue

        end_time, end_char, duration = min(ends, key=lambda item: abs(item[2] - target_duration))
        if abs(duration - target_duration) > tolerance or base_end_time - end_time <= tolerance:
            continue
        variants.append(Clip(sentence_start, end_time, sentence_start_char, end_char))

    result.extend(variants)
    return _dedupe_candidates(result)


def _ffmpeg_color(hex_color: str, opacity: int = 100) -> str:
    c = str(hex_color or "#FFFFFF").strip().lstrip("#")
    if len(c) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in c):
        c = "FFFFFF"
    alpha = max(0, min(255, round(max(0, min(100, int(opacity))) * 2.55)))
    return f"0x{c}@{alpha/255:.3f}"


def _position_xy(position: str, margin: int, item_w: str = "w", item_h: str = "h") -> tuple[str, str]:
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


def _resolve_watermark_file(path_value: str) -> Optional[str]:
    p = Path(path_value.strip().strip('"')) if path_value else Path()
    if p.is_file():
        return str(p)
    if p.is_dir():
        for ext in ("*.png", "*.webp", "*.jpg", "*.jpeg"):
            found = sorted(p.glob(ext))
            if found:
                return str(found[0])
    return None


def _ffmpeg_filter_path(path_value: str) -> str:
    """Escape a Windows path for use inside an FFmpeg filter argument.

    FFmpeg filter options use ':' as separators, so a Windows drive colon must
    be escaped even when the path is surrounded by quotes. Backslashes are
    normalized to forward slashes for portability.
    """
    value = os.path.abspath(str(path_value)).replace("\\", "/")
    value = value.replace("\\", "/")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def apply_optional_branding(input_video: str, output_video: str) -> str:
    """Burn optional logo and/or static text overlay into the final 1080x1920 Short."""
    logo = _resolve_watermark_file(WATERMARK_PATH) if WATERMARK_ENABLED else None
    text = TEXT_OVERLAY if TEXT_ENABLED and TEXT_OVERLAY else ""
    if not logo and not text:
        return input_video
    ffmpeg = get_ffmpeg_path()
    filters = []
    inputs = ["-i", input_video]
    current = "0:v"
    if logo:
        inputs += ["-i", logo]
        # Size is percentage of the 1080px output width.
        logo_w = max(32, round(1080 * WATERMARK_SIZE / 100))
        if WATERMARK_POSITION == "custom":
            x = f"(W-w)*{WATERMARK_X/100:.6f}"
            y = f"(H-h)*{WATERMARK_Y/100:.6f}"
        else:
            x, y = _position_xy(WATERMARK_POSITION, WATERMARK_MARGIN, "w", "h")
        logo_chain = f"[1:v]format=rgba"
        if WATERMARK_BG_REMOVE:
            bg = _ffmpeg_color(WATERMARK_BG_COLOR, 100).split("@")[0].replace("0x", "")
            logo_chain += f",colorkey=0x{bg}:{WATERMARK_BG_SIMILARITY:.3f}:{WATERMARK_BG_BLEND:.3f}"
        logo_chain += f",colorchannelmixer=aa={WATERMARK_OPACITY/100:.3f},scale={logo_w}:-1[wm]"
        filters.append(logo_chain)
        filters.append(f"[{current}][wm]overlay=x={x}:y={y}:format=auto[v1]")
        current = "v1"
    if text:
        text_file = os.path.join(OUTPUT_DIR, "_branding_text.txt")
        Path(text_file).write_text(text, encoding="utf-8")
        font_path = _caption_font_path()
        escaped_font_path = _ffmpeg_filter_path(font_path) if font_path else ""
        font_expr = f":fontfile=\'{escaped_font_path}\'" if escaped_font_path else ""
        fs = max(34, round(1080 * TEXT_SIZE / 100))
        if TEXT_POSITION == "custom":
            x = f"(w-tw)*{TEXT_X/100:.6f}"
            y = f"(h-th)*{TEXT_Y/100:.6f}"
        else:
            x, y = _position_xy(TEXT_POSITION, TEXT_MARGIN, "tw", "th")
        box = 1 if TEXT_BG_ENABLED else 0
        boxcolor = _ffmpeg_color(TEXT_BG_COLOR, TEXT_BG_OPACITY)
        escaped_text_file = _ffmpeg_filter_path(text_file)
        filters.append(f"[{current}]drawtext=textfile='{escaped_text_file}':fontsize={fs}:fontcolor={TEXT_COLOR}:x={x}:y={y}:box={box}:boxcolor={boxcolor}:boxborderw=18:fix_bounds=true[v2]")
        current = "v2"
    fc = ";".join(filters)
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", fc, "-map", f"[{current}]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", output_video]
    proc = _run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        Path(text_file).unlink()
    except Exception:
        pass
    if proc.returncode != 0 or not os.path.exists(output_video) or os.path.getsize(output_video) < 1024:
        raise RuntimeError(f"Branding render failed: {proc.stderr[-1800:]}")
    return output_video


def process_single_video(
    input_path: str,
    transcription_path: Optional[str],
    max_clips: int,
    video_index: int,
    total_videos: int,
) -> List[str]:
    """Process ONE video end-to-end through the new AI pipeline.

    Returns list of final output short file paths created.
    Never crashes the caller; wraps everything in try/except with clear logs.
    """
    created: List[str] = []
    vname = os.path.basename(input_path)
    print(
        f"\n{'='*68}\n"
        f"=== Processing Video {video_index}/{total_videos}: {vname} ===\n"
        f"{'='*68}"
    )

    # -----------------------------------------------------
    # 1. TRANSCRIBE (or load cached pickle)
    # -----------------------------------------------------
    try:
        transcription = None
        if transcription_path and os.path.exists(transcription_path):
            print(f"  [Transcribe] Loading cached transcription: {os.path.basename(transcription_path)}")
            transcription = load_existing_transcription(transcription_path)
            if transcription is None:
                print("  [Transcribe] Cache invalid or corrupt, will re-transcribe.")
        if transcription is None:
            transcriber = create_transcriber(
                model_size=os.getenv("TRANSCRIPTION_MODEL", TRANSCRIPTION_MODEL)
            )
            print(
                f" [Transcribe] Running WhisperX (model={os.getenv('TRANSCRIPTION_MODEL', TRANSCRIPTION_MODEL)})..."
            )
            transcription = transcribe_with_progress(input_path, transcriber)
            save_p = transcription_path or get_transcription_file_path(input_path)
            save_transcription(transcription, save_p)
            print(f"  [Transcribe] Saved transcription cache: {os.path.basename(save_p)}")
    except Exception as e:
        print(f"  [FATAL] Transcription phase failed for {vname}: {type(e).__name__}: {e}")
        return created

    # -----------------------------------------------------
    # 2. FIND CANDIDATE CLIPS via ClipsAI
    # -----------------------------------------------------
    try:
        print(f"  [ClipsAI] Detecting candidate clips...")
        clipfinder = create_candidate_clip_finder()
        raw_clips = clipfinder.find_clips(transcription=transcription)
        raw_clips = _dedupe_candidates(list(raw_clips))
        previous_count = len(raw_clips)
        raw_clips = _add_sentence_aligned_prefix_candidates(raw_clips, transcription)
        added_prefixes = len(raw_clips) - previous_count
        if added_prefixes:
            print(f"  [ClipsAI] Added {added_prefixes} sentence-aligned shorter candidate(s).")
        total_candidates = len(raw_clips)
        print(f"  [ClipsAI] {total_candidates} candidate clip(s) detected.")
        if total_candidates == 0:
            print(f"  [SKIP] No candidates found in this video.")
            return created
        for i, c in enumerate(raw_clips[:10], 1):
            print(f"    [{i}/{total_candidates}] Candidate clip detected "
                  f"({c.start_time:.1f}s–{c.end_time:.1f}s, dur={c.end_time-c.start_time:.1f}s)")
        if total_candidates > 10:
            print(f"    ... and {total_candidates-10} more.")
    except Exception as e:
        print(f"  [FATAL] ClipFinder failed: {type(e).__name__}: {e}")
        return created

    # -----------------------------------------------------
    # 3. AI RANKING with Ollama/qwen3:8b; explicit keep is required to render.
    # -----------------------------------------------------
    ranked = []
    try:
        # Pre-filter all ClipsAI candidates with cheap deterministic scoring, then let Qwen judge the strongest set.
        pre_scored = [(c, calculate_engagement_score(c, transcription)) for c in raw_clips]
        pre_scored.sort(key=lambda x: x[1], reverse=True)
        N = min(len(pre_scored), max(15, max_clips * 4))
        top_candidates = [c for c, _ in pre_scored[:N]]
        print(f"  [AI] Analyzing top {N} candidates for requested {max_clips} Short(s) with {OLLAMA_MODEL}...")
        ai_results = analyze_candidates_with_ai(
            top_candidates, transcription, batch_size=3
        )
        ranked = rank_candidates(top_candidates, transcription, ai_results)
        if ranked:
            best_id, best_clip, best_score, best_meta = ranked[0]
            reason = (best_meta or {}).get("reason", "")[:160]
            print(
                f"  [AI] Top candidate #{best_id+1}: score={best_score:.1f} — {reason}"
            )
        qwen_valid_count = sum(
            1 for row in ranked
            if isinstance(row[3], dict) and row[3].get("ai_valid")
            and row[3].get("decision") in {"keep", "reject"}
        )
        qwen_keep_count = sum(
            1 for row in ranked
            if isinstance(row[3], dict) and row[3].get("ai_valid")
            and row[3].get("decision") == "keep"
        )
        qwen_reject_count = sum(
            1 for row in ranked
            if isinstance(row[3], dict) and row[3].get("ai_valid")
            and row[3].get("decision") == "reject"
        )
        qwen_unscored_count = len(ranked) - qwen_valid_count
        ranked, decision_status = gate_ranked_candidates_by_qwen_decision(ranked)
        print(
            f"  [QwenGate] status={decision_status}; valid={qwen_valid_count}; "
            f"keep={qwen_keep_count}; reject={qwen_reject_count}; "
            f"missing_or_malformed={qwen_unscored_count}; eligible={len(ranked)}."
        )
        if decision_status == "qwen_rejected_all":
            print("  [ERROR] Qwen explicitly rejected every valid candidate; no Short was created.")
            return created
        if decision_status == "qwen_unavailable":
            print("  [ERROR] No valid Qwen keep decision was available; no Short was created and deterministic scores were not used as approval.")
            return created
        print(f"  [Selection] {len(ranked)} explicitly Qwen-approved candidate(s) remain eligible; rejected, malformed, and unscored candidates are excluded.")
    except Exception as e:
        print(f"  [FATAL] Qwen selection failed ({type(e).__name__}: {e}); no Short can be rendered without an explicit valid keep decision.")
        return created

    # -----------------------------------------------------
    # 4. APPLY BOUNDARY + DURATION ENFORCEMENT, SELECT
    # -----------------------------------------------------
    selected_final = []
    for rpos, (orig_idx, clip, final_score, meta) in enumerate(ranked):
        if len(selected_final) >= max_clips:
            break
        try:
            print(f"  [{rpos+1}/{len(ranked)}] Checking candidate "
                  f"({clip.start_time:.1f}-{clip.end_time:.1f}, dur={clip.end_time-clip.start_time:.1f}s, score={final_score:.1f})")
            if isinstance(meta, dict) and meta.get("ai_valid"):
                if float(meta.get("coherence", 0.0)) < 4.5:
                    print("     → Qwen approved this candidate with a low coherence score; applying the score penalty before boundary checks.")
            c1 = adjust_clip_boundaries_to_sentences(clip, transcription, verbose=False)
            c2 = enforce_duration_bounds(c1, transcription, verbose=False)
            if c2 is None:
                print(
                    f"     → rejected by duration bounds (cannot reach "
                    f"{MIN_CLIP_DURATION}–{MAX_CLIP_DURATION}s coherently)."
                )
                continue
            c3 = trim_leading_trailing_silence_conservative(c2, transcription)
            dur = c3.end_time - c3.start_time
            if dur < MIN_CLIP_DURATION - 0.5 or dur > MAX_CLIP_DURATION + 0.5:
                print(f"     → rejected after trimming (dur={dur:.1f}s outside [{MIN_CLIP_DURATION}, {MAX_CLIP_DURATION}]).")
                continue
            print(f"  [OK] Selected candidate "
                  f"(t={c3.start_time:.1f}-{c3.end_time:.1f}s, dur={dur:.1f}s, selection score={final_score:.0f})")
            selected_final.append((c3, final_score, meta))
        except Exception as e:
            print(f"     → skip due to error during boundary enforcement: {type(e).__name__}: {e}")
            continue

    if len(selected_final) < max_clips:
        existing_starts = [float(item[0].start_time) for item in selected_final]
        for _, clip, final_score, meta in ranked:
            if len(selected_final) >= max_clips:
                break
            if any(abs(float(clip.start_time) - start) < 12.0 for start in existing_starts):
                continue
            duration = float(clip.end_time - clip.start_time)
            if MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION:
                selected_final.append((clip, final_score, meta))
                existing_starts.append(float(clip.start_time))
                print(f"  [Recovery] Added candidate at {clip.start_time:.1f}s to reach requested count")

    print(f"  [Selection] Requested {max_clips}; selected {len(selected_final)} valid Short(s).")

    if not selected_final:
        print(f"  [SKIP] No clips survived boundary + duration enforcement.")
        return created

    # -----------------------------------------------------
    # 5. PROCESS EACH SELECTED CLIP
    # -----------------------------------------------------
    for clip_pos, (clip, ai_score, ai_meta) in enumerate(selected_final, 1):
        clip_id_suffix = f"{video_index:02d}_{clip_pos:02d}"
        temp_files: List[str] = []
        trimmed_path = os.path.abspath(
            os.path.join(OUTPUT_DIR, f"_tmp_trimmed_{clip_id_suffix}.mp4")
        )
        temp_files.append(trimmed_path)
        resized_path = os.path.abspath(
            os.path.join(OUTPUT_DIR, f"_tmp_vertical_{clip_id_suffix}.mp4")
        )
        temp_files.append(resized_path)
        ass_path = os.path.abspath(
            os.path.join(OUTPUT_DIR, f"_tmp_captions_{clip_id_suffix}.ass")
        )
        temp_files.append(ass_path)
        # Use the selected clip position rather than len(created). If a later
        # stage fails, the next clip must NOT reuse/overwrite short_01.mp4.
        short_num_str = f"{clip_pos:02d}"
        final_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"short_{short_num_str}.mp4"))
        meta_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"short_{short_num_str}.txt"))

        print(f"\n  [{clip_pos}/{len(selected_final)}] Rendering Short #{short_num_str}...")
        try:
            # Trim
            dur = clip.end_time - clip.start_time
            print(f"     [1/5] Trim {clip.start_time:.1f}s–{clip.end_time:.1f}s ({dur:.1f}s)")
            from clipsai import AudioVideoFile, MediaEditor

            media_editor = MediaEditor()
            media_file = AudioVideoFile(input_path)
            media_editor.trim(
                media_file=media_file,
                start_time=clip.start_time,
                end_time=clip.end_time,
                trimmed_media_file_path=trimmed_path,
            )
            if not os.path.exists(trimmed_path) or os.path.getsize(trimmed_path) < 1024:
                raise RuntimeError(f"Trim output missing or empty: {trimmed_path}")

            # Resize vertical with zoom
            print(f"     [2/5] Resize to 1080x1920 (subtle zoom)")
            if EDIT_MODE == "gaming":
                ok = resize_gaming_adaptive(trimmed_path, resized_path)
            else:
                ok = resize_to_vertical_with_zoom(
                    trimmed_path,
                    resized_path,
                    zoom_factor=1.00,
                )
            if not ok or not os.path.exists(resized_path) or os.path.getsize(resized_path) < 1024:
                raise RuntimeError(f"Vertical resize failed: {resized_path}")

            # Captions
            print(f"     [3/5] Render dynamic Shorts captions...")
            captioned_path = create_animated_subtitles(
                resized_path, transcription, clip, final_path
            )
            if not captioned_path or not os.path.exists(captioned_path):
                raise RuntimeError("Caption renderer did not produce a final captioned video.")
            if os.path.abspath(captioned_path) != os.path.abspath(final_path):
                shutil.copy2(captioned_path, final_path)
                temp_files.append(captioned_path)

            if not os.path.exists(final_path) or os.path.getsize(final_path) < 1024:
                raise RuntimeError(f"Final output missing after caption step: {final_path}")

            # Keep an unbranded captioned base so branding can be changed later in the Editor
            # without rerunning WhisperX, ClipsAI, Qwen, captions, or the AI selection stage.
            clean_base_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"short_{short_num_str}_clean.mp4"))
            shutil.copy2(final_path, clean_base_path)

            # Optional logo + static text branding
            if WATERMARK_ENABLED or (TEXT_ENABLED and TEXT_OVERLAY):
                print("     [Branding] Applying optional logo/text overlays...")
                branded_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"_tmp_branded_{clip_id_suffix}.mp4"))
                temp_files.append(branded_path)
                try:
                    apply_optional_branding(final_path, branded_path)
                    shutil.copy2(branded_path, final_path)
                    print("     [Branding] Done")
                except Exception as branding_error:
                    # Branding is optional. Never throw away a fully rendered Short
                    # just because an overlay cannot be burned. The clean captioned
                    # video remains the valid final output and can be branded later.
                    print(f"     [Branding] WARNING: overlay failed; keeping clean Short. {type(branding_error).__name__}: {branding_error}")
                    if os.path.exists(branded_path):
                        cleanup_temp_files([branded_path])

            # Title generation (local Ollama preferred, Groq fallback)
            print(f"     [4/5] Generating AI title via Qwen3...")
            clip_words = words_for_clip(clip, transcription, padding_words=0)
            clip_text = transcript_text(clip_words)
            title = None
            if clip_text.strip():
                title = get_viral_title_locally(clip_text)
            if not title:
                title = f"Short {short_num_str}"
            cleaned = _clean_title(str(title)) if title else None
            title = cleaned or str(title)
            print(f"     [Title] → {title}")

            # Generate YouTube-facing description, hashtags and search tags locally.
            print(f"     [Metadata] Generating description + hashtags + tags via Qwen3...")
            metadata = generate_short_metadata_locally(clip_text, title)
            metadata_path = os.path.abspath(os.path.join(OUTPUT_DIR, f"short_{short_num_str}.json"))
            provenance = selection_provenance(ai_meta)
            try:
                with open(metadata_path, "w", encoding="utf-8") as jf:
                    json.dump({
                        "title": title,
                        "description": metadata.get("description", ""),
                        "hashtags": metadata.get("hashtags", []),
                        "tags": metadata.get("tags", []),
                        "source_video": vname,
                        "start_time": round(float(clip.start_time), 2),
                        "end_time": round(float(clip.end_time), 2),
                        "duration": round(float(clip.end_time - clip.start_time), 2),
                        "selection": provenance,
                    }, jf, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"     [WARN] JSON metadata write failed: {e}")

            # Save metadata text file
            try:
                dims = ""
                if isinstance(ai_meta, dict):
                    for k in ("hook", "curiosity", "emotion", "surprise", "conflict",
                              "story", "payoff", "pacing", "standalone", "rewatch", "coherence"):
                        v = ai_meta.get(k)
                        if isinstance(v, (int, float)):
                            dims += f"  {k}: {float(v):.1f}\n"
                with open(meta_path, "w", encoding="utf-8") as mf:
                    mf.write(f"Title: {title}\n")
                    mf.write(f"Description: {metadata.get('description','')}\n")
                    mf.write(f"Hashtags: {' '.join(metadata.get('hashtags', []))}\n")
                    mf.write(f"Tags: {', '.join(metadata.get('tags', []))}\n")
                    mf.write(f"Source video: {vname}\n")
                    mf.write(f"Timestamps: {clip.start_time:.2f}s - {clip.end_time:.2f}s\n")
                    mf.write(f"Duration: {clip.end_time - clip.start_time:.2f}s\n")
                    mf.write(f"Selection method: {provenance['method']}\n")
                    if provenance["model"]:
                        mf.write(f"AI model: {provenance['model']}\n")
                    if provenance["decision"]:
                        mf.write(f"AI decision: {provenance['decision']}\n")
                    if provenance["recovery_used"]:
                        mf.write("Recovery used: yes\n")
                    mf.write(f"Selection note: {provenance['note']}\n")
                    if isinstance(ai_meta, dict) and ai_meta.get("ai_valid"):
                        mf.write(f"AI Final Score: {ai_score:.1f}\n")
                    else:
                        mf.write(f"AI Final Score: unavailable\nSelection Score (deterministic): {ai_score:.1f}\n")
                    if isinstance(ai_meta, dict) and ai_meta.get("reason"):
                        mf.write(f"AI Reason: {ai_meta['reason']}\n")
                    if dims:
                        mf.write(f"AI Dimension Scores:\n{dims}")
                    mf.write(f"\nTranscript:\n{clip_text}\n")
                print(f"     [5/5] Saved metadata: {os.path.basename(meta_path)}")
            except Exception as e:
                print(f"     [WARN] Metadata write failed: {e}")

            print(f"  [DONE] → {final_path}  \"{title}\"")
            created.append(final_path)

        except Exception as e:
            print(f"  [ERROR] Clip {clip_pos} failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            continue
        finally:
            # Best-effort cleanup of temp files
            cleanup_temp_files(temp_files)
            # Also remove the ASS that create_animated_subtitles may have written at OUTPUT_DIR root
            for extra in ["temp_subtitles.ass", os.path.basename(ass_path)]:
                p = os.path.join(os.path.abspath(OUTPUT_DIR), extra)
                if p not in temp_files:
                    cleanup_temp_files([p])

    print(f"\n  Finished video {vname}: {len(created)} short(s) created.")
    return created


def _self_test() -> int:
    """Verify every AI runtime dependency and report what is missing.

    Used to validate a fresh installation: it exercises exactly the imports the
    pipeline needs, which a compiled build cannot do from Nuitka's static
    import graph alone.
    """
    print("\n" + "=" * 68)
    print(" Clipify AI runtime self-test")
    print("=" * 68)

    status = runtime_status()
    bootstrap_runtime()
    print(f" Compiled build : {bool(_compiled_build)}")
    print(f" Interpreter    : {sys.executable}")
    print(f" Runtime prefix : {status['prefix'] or '(not found)'}")
    print(f" Site-packages  : {status['site_packages'] or '(not found)'}")
    print(f" FFmpeg         : {FFMPEG_BIN}")
    print("-" * 68)

    checks = (
        ("torch", "torch"),
        ("numpy", "numpy"),
        ("cv2", "opencv"),
        ("PIL", "pillow"),
        ("nltk", "nltk"),
        ("clipsai", "clipsai"),
        ("whisperx", "whisperx"),
        ("mediapipe", "mediapipe"),
        ("facenet_pytorch", "facenet-pytorch"),
        ("kokoro", "kokoro (TTS)"),
    )
    failed: list[str] = []
    for module_name, label in checks:
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "?")
            print(f" [ok]   {label:<20} {version}")
        except Exception as exc:  # noqa: BLE001
            failed.append(label)
            print(f" [FAIL] {label:<20} {type(exc).__name__}: {exc}")

    print("-" * 68)
    if failed:
        print(f" RESULT: {len(failed)} dependency/dependencies missing: {', '.join(failed)}")
        print()
        print(_MISSING_RUNTIME_HINT)
        return 1

    try:
        import torch

        print(f" GPU available  : {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f" GPU            : {torch.cuda.get_device_name(0)}")
    except Exception as exc:  # noqa: BLE001
        print(f" GPU check      : skipped ({type(exc).__name__}: {exc})")

    print(" RESULT: all AI runtime dependencies loaded.")
    return 0


def main():
    """Entry point: parse CLI args and run pipeline."""
    parser = argparse.ArgumentParser(
        description="Clipify AI — AI-powered YouTube Shorts generator using local Ollama/Qwen"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Non-interactive mode: process all videos in input/ automatically",
    )
    parser.add_argument(
        "--clips",
        type=int,
        default=2,
        help="Max number of Shorts to create per video (default: 2 in auto mode)",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=None,
        help="Minimum Short duration in seconds (5-60; UI normally sets this).",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=None,
        help="Maximum Short duration in seconds (5-60; UI normally sets this).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        default=False,
        help="Verify the local AI runtime (Torch, WhisperX, ClipsAI, OpenCV) and exit.",
    )
    args = parser.parse_args()

    if args.self_test:
        sys.exit(_self_test())

    # Allow the CLI/web app to override duration without changing the source file.
    global MIN_CLIP_DURATION, MAX_CLIP_DURATION, PREFERRED_MIN_CLIP_DURATION, PREFERRED_MAX_CLIP_DURATION
    if args.min_duration is not None:
        MIN_CLIP_DURATION = max(5, min(60, int(args.min_duration)))
    if args.max_duration is not None:
        MAX_CLIP_DURATION = max(5, min(60, int(args.max_duration)))
    if MAX_CLIP_DURATION < MIN_CLIP_DURATION:
        MAX_CLIP_DURATION = MIN_CLIP_DURATION
    PREFERRED_MIN_CLIP_DURATION = max(MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, PREFERRED_MIN_CLIP_DURATION))
    PREFERRED_MAX_CLIP_DURATION = max(PREFERRED_MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, PREFERRED_MAX_CLIP_DURATION))

    try:
        _init_ml_runtime()
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(3)

    print()
    print("=" * 68)
    print(" Clipify AI  —  AI-Powered YouTube Shorts Generator")
    print(f" Model        : {OLLAMA_MODEL} (via {OLLAMA_URL})")
    print(f" Clip range   : {MIN_CLIP_DURATION}–{MAX_CLIP_DURATION}s (prefer {PREFERRED_MIN_CLIP_DURATION}–{PREFERRED_MAX_CLIP_DURATION}s)")
    print(f" Resolution   : 1080 x 1920  (9:16 vertical)")
    print(f" Max clips    : {args.clips} per video")
    print(f" FFmpeg       : {FFMPEG_BIN}")
    print(f" ffprobe      : {FFPROBE_BIN}")
    try:
        import torch

        if torch.cuda.is_available():
            print(f" GPU          : {torch.cuda.get_device_name(0)}")
        else:
            print(" GPU          : not visible to this Python process (Ollama may still use GPU)")
    except Exception:
        print(" GPU          : detection skipped")
    print("=" * 68)
    print()

    if not args.auto:
        print("Running in AUTO mode by default (use --auto explicitly or interactive mode TBD).")
        args.auto = True

    # Discover videos + cached transcriptions
    try:
        work_items = find_input_videos_auto()
    except FileNotFoundError as fnf:
        print(f"[ERROR] {fnf}")
        sys.exit(1)

    total_videos = len(work_items)
    print(f"[Start] Found {total_videos} video(s) to process.\n")

    all_created: List[str] = []
    for i, (vpath, tpath) in enumerate(work_items, 1):
        try:
            outs = process_single_video(vpath, tpath, args.clips, video_index=i, total_videos=total_videos)
            all_created.extend(outs)
        except Exception as e:
            print(f"[ERROR] Top-level failure on video {os.path.basename(vpath)}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Final report
    print()
    print("=" * 68)
    if all_created:
        print(f" SUCCESS! Created {len(all_created)} YouTube Short(s):")
        for p in all_created:
            print(f"   • {p}")
    else:
        print(" No Shorts were created. Check the logs above for errors.")
        print(" Common fixes: add a video, ensure Ollama is running, check FFmpeg.")
    print("=" * 68)
if __name__ == "__main__":
    main()
