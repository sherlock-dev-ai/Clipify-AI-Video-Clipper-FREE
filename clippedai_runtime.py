"""Clipify AI runtime bootstrap.

This module is the single place where Clipify AI decides *where* its runtime
lives. It is compiled into app.exe / main.exe by Nuitka and is therefore never
shipped as readable source.

Runtime architecture (see build/README.md "Runtime architecture")
-----------------------------------------------------------------
Tier A - compiled into the executables:
    Pure-Python application/web tier: Flask stack, python-dotenv, requests and
    the narrate package, plus the Python standard library.

Tier B - installed separately as the "Clipify AI ML runtime":
    Torch, WhisperX, ClipsAI, NLTK, NumPy, SciPy, OpenCV, Pillow,
    transformers, MediaPipe, facenet-pytorch, onnxruntime, ctranslate2,
    kokoro, yt-dlp and their dependencies. These are multi-gigabyte,
    GPU/CPU architecture specific and must not be compiled from source or
    embedded in the installer.

Tier B is located at runtime and added to ``sys.path`` before any Tier B
import happens, so the compiled executables never depend on a system Python,
a developer virtualenv or anything on PATH.

Resolution order for the runtime prefix:
    1. ``CLIPPEDAI_RUNTIME`` environment variable
    2. ``%LOCALAPPDATA%\\ClippedAI\\runtime``
    3. ``<app directory>\\runtime``

User data (projects, jobs, outputs, settings, downloaded assets) always lives
under ``%LOCALAPPDATA%\\ClippedAI`` so that uninstalling never destroys it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "APP_DIR",
    "MISSING_MESSAGE",
    "USER_DATA_DIR",
    "bootstrap",
    "data_dir",
    "ensure_data_dirs",
    "frozen",
    "require_runtime",
    "runtime_dir",
    "runtime_python",
    "runtime_site_packages",
    "runtime_status",
]

# Handles returned by os.add_dll_directory must stay alive for the process
# lifetime, otherwise Windows immediately removes the directory again.
_DLL_HANDLES: list = []

_BOOTSTRAPPED = False


def _detect_frozen() -> bool:
    """True when running from a compiled build rather than a source checkout.

    Nuitka does NOT set ``sys.frozen``. It injects ``__compiled__`` into every
    compiled module's globals, which is the documented way to detect it. The
    executable-name check is a fallback that also covers PyInstaller.
    """
    if getattr(sys, "frozen", False):
        return True
    if "__compiled__" in globals():
        return True
    executable = str(getattr(sys, "executable", "")).lower()
    return executable.endswith(".exe") and not executable.endswith(
        ("python.exe", "pythonw.exe")
    )


def _app_dir() -> Path:
    """Directory that contains the running executable."""
    if frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


#: True when running from a compiled (Nuitka/PyInstaller) build.
frozen: bool = _detect_frozen()

#: Installation directory (read-only: application code, DLLs, assets).
APP_DIR: Path = _app_dir()


#: Markers the installer creates beside the application when the user chose a
#: data directory. Their presence means "this install keeps its data here".
_DATA_MARKERS = (".env", "jobs", "input", "output", "settings")


def _looks_like_data_root(candidate: Path) -> bool:
    try:
        return any((candidate / marker).exists() for marker in _DATA_MARKERS)
    except OSError:
        return False


def _user_data_dir() -> Path:
    override = os.environ.get("CLIPPEDAI_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if not frozen:
        # Development checkout: keep the historical project layout so existing
        # jobs/, output/ and input/ folders keep working.
        return APP_DIR
    # A self-contained install. The installer seeds jobs/, input/, output/ and
    # .env in the folder the user picked, so if those are sitting next to the
    # executable that folder is the data root. This keeps everything the user
    # installed in one place instead of silently forking half of it onto C:.
    if _looks_like_data_root(APP_DIR):
        return APP_DIR
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "ClippedAI"


#: Writable user data root. Beside the executable for a self-contained install,
#: otherwise %LOCALAPPDATA%\ClippedAI.
USER_DATA_DIR: Path = _user_data_dir()

# Sub-directories of the user data root that the application relies on.
DATA_SUBDIRS = ("input", "output", "jobs", "settings", "projects", "assets", "narrate clips")


def data_dir(*parts: str) -> Path:
    """Return a path inside the user data root, creating parents as needed."""
    path = USER_DATA_DIR.joinpath(*parts) if parts else USER_DATA_DIR
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def ensure_data_dirs() -> None:
    """Create the user data directory tree."""
    data_dir()
    for name in DATA_SUBDIRS:
        data_dir(name)


def _candidate_runtime_dirs() -> list[Path]:
    candidates: list[Path] = []

    override = os.environ.get("CLIPPEDAI_RUNTIME", "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    candidates.append(USER_DATA_DIR / "runtime")
    candidates.append(APP_DIR / "runtime")

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _site_packages_of(prefix: Path) -> Path | None:
    for parts in (
        ("Lib", "site-packages"),
        ("lib", "site-packages"),
        ("Lib", "site-packages", "packages"),
        ("site-packages",),
    ):
        candidate = prefix.joinpath(*parts)
        if candidate.is_dir():
            return candidate
    return None


def runtime_dir() -> Path | None:
    """Return the first runtime prefix that actually contains site-packages."""
    for prefix in _candidate_runtime_dirs():
        if _site_packages_of(prefix):
            return prefix
    return None


def runtime_site_packages() -> Path | None:
    """Return the site-packages directory of the located ML runtime."""
    prefix = runtime_dir()
    if prefix is None:
        return None
    return _site_packages_of(prefix)


def runtime_python() -> Path | None:
    """Return the interpreter of the ML runtime (used for helper subprocesses)."""
    prefix = runtime_dir()
    if prefix is None:
        return None
    for relative in (("Scripts", "python.exe"), ("python.exe"), ("bin", "python.exe")):
        candidate = prefix.joinpath(*relative)
        if candidate.is_file():
            return candidate
    return None


def _add_dll_directory(path: Path) -> None:
    """Register a directory so dependent DLLs can be resolved by the loader."""
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    try:
        handle = os.add_dll_directory(resolved)
        _DLL_HANDLES.append(handle)
    except (OSError, AttributeError, ValueError):
        pass
    cur_path = os.environ.get("PATH", "")
    if resolved.lower() not in cur_path.lower():
        os.environ["PATH"] = f"{resolved};{cur_path}"


def _contains_dll(path: Path) -> bool:
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith((".dll", ".pyd")):
                    return True
    except OSError:
        return False
    return False


def _register_dll_directories(prefix: Path, site_packages: Path) -> None:
    """Register every directory of the runtime that holds native libraries.

    Torch (torch\\lib), PyAV (av.libs), SciPy/NumPy (scipy.libs, numpy.libs),
    NVIDIA (nvidia\\*\\bin), soundfile (_soundfile_data) and OpenCV's videoio
    plugin all load native DLLs by name at import time. Rather than hard-code a
    list that goes stale, scan the runtime for directories that actually contain
    DLLs.
    """
    seen: set[str] = set()

    def register(path: Path) -> None:
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        _add_dll_directory(path)

    register(prefix)

    # Register bundled tools (FFmpeg, yt-dlp, etc.)
    tools_dir = APP_DIR / "tools"
    if tools_dir.is_dir():
        for root, _, files in os.walk(tools_dir):
            if any(f.lower().endswith((".dll", ".exe")) for f in files):
                register(Path(root))

    # Register torchcodec if present
    torchcodec_dir = site_packages / "torchcodec"
    if torchcodec_dir.is_dir():
        register(torchcodec_dir)

    for base in (site_packages, site_packages / "nvidia"):
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name.endswith(".libs") or entry.name == "nvidia":
                register(entry)
                continue
            candidates = [entry]
            for nested in (entry / "lib", entry / "bin"):
                if nested.is_dir():
                    candidates.append(nested)
            for candidate in candidates:
                if _contains_dll(candidate):
                    register(candidate)


def bootstrap() -> Path | None:
    """Make the ML runtime importable. Safe to call multiple times.

    Returns the located runtime prefix, or ``None`` when the ML runtime is not
    installed yet. Callers that only need the web tier (Flask UI, Ollama
    discovery, uploads) work fine with ``None``; the pipeline refuses to start
    and prints an actionable message instead.
    """
    global _BOOTSTRAPPED
    prefix = runtime_dir()
    if prefix is None:
        return None
    site_packages = _site_packages_of(prefix)
    if site_packages is None:
        return None

    if not _BOOTSTRAPPED:
        path_entry = str(site_packages)
        if path_entry not in sys.path:
            sys.path.insert(0, path_entry)
        _register_dll_directories(prefix, site_packages)
        _BOOTSTRAPPED = True
    return prefix


def runtime_status() -> dict:
    """Human readable status of the ML runtime, for the web UI and diagnostics."""
    prefix = runtime_dir()
    site_packages = runtime_site_packages()
    marker = site_packages / "clipsai" if site_packages else None
    return {
        "installed": bool(prefix),
        "prefix": str(prefix) if prefix else "",
        "site_packages": str(site_packages) if site_packages else "",
        "complete": bool(marker and marker.is_dir()),
        "searched": [str(p) for p in _candidate_runtime_dirs()],
    }


MISSING_MESSAGE = """Clipify AI ML runtime is not installed.

The video pipeline needs the local AI runtime (Torch, WhisperX, ClipsAI,
OpenCV, transformers). The Clipify AI installer sets this up for you.

Searched:
  - CLIPPEDAI_RUNTIME environment variable
  - %LOCALAPPDATA%\\ClippedAI\\runtime
  - <install folder>\\runtime

Re-run Clipify AI Setup.exe and enable the "AI runtime" component, or run:
  <Clipify AI install folder>\\runtime\\Scripts\\python.exe -m pip install -r requirements-runtime.txt
"""


def require_runtime(feature: str = "This feature") -> Path:
    """Return the runtime prefix or raise a descriptive error.

    In a development checkout the interpreter's own site-packages already
    provide the ML tier, so nothing external has to exist yet.
    """
    prefix = bootstrap()
    if not frozen:
        return prefix if prefix is not None else APP_DIR
    status = runtime_status()
    if prefix is None or not status["complete"]:
        raise RuntimeError(MISSING_MESSAGE)
    return prefix
