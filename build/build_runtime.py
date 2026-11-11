"""
build_runtime.py
================
Provisions the Clipify AI ML runtime (tier B).

The compiled app.exe / main.exe do not contain Torch, WhisperX, ClipsAI or any
other ML dependency. They import them from a dedicated virtualenv that this
script creates. The installer calls the same code path, so a runtime built
here and a runtime built by the setup executable are identical.

Default location: %LOCALAPPDATA%\\ClippedAI\\runtime
Override:         --dest <path>   or   CLIPPEDAI_RUNTIME=<path>

Usage:
    .venv\\Scripts\\python.exe build\\build_runtime.py
    .venv\\Scripts\\python.exe build\\build_runtime.py --check
    .venv\\Scripts\\python.exe build\\build_runtime.py --dest D:\\ClipifyAIRuntime

The virtualenv's Python must be CPython 3.11 x64, matching the version the
executables were compiled with. That is verified before anything is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements-runtime.txt"

# The compiled binaries embed CPython 3.11 x64.
REQUIRED_PYTHON = (3, 11)

# Marker packages the pipeline needs before it can run.
MARKERS = (
    Path("Lib", "site-packages", "clipsai"),
    Path("Lib", "site-packages", "torch"),
    Path("Lib", "site-packages", "whisperx"),
    Path("Lib", "site-packages", "cv2"),
    Path("Lib", "site-packages", "en_core_web_sm"),
)


def default_destination() -> Path:
    override = os.environ.get("CLIPPEDAI_RUNTIME", "").strip()
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "ClippedAI" / "runtime"


def runtime_python(dest: Path) -> Path:
    for relative in (("Scripts", "python.exe"), ("python.exe"), ("bin", "python.exe")):
        candidate = dest.joinpath(*relative)
        if candidate.is_file():
            return candidate
    return dest / "Scripts" / "python.exe"


def check(dest: Path) -> dict:
    """Report whether a usable runtime exists at dest."""
    python = runtime_python(dest)
    result = {"dest": str(dest), "python": str(python), "ok": False, "missing": []}
    if not python.is_file():
        result["missing"].append("interpreter")
        return result
    if not all((dest / marker).is_dir() for marker in MARKERS):
        result["missing"] = [m.name for m in MARKERS if not (dest / m).is_dir()]
        return result
    try:
        probe = subprocess.run(
            [
                str(python), "-c",
                "import clipsai, torch, whisperx, cv2, spacy, en_core_web_sm, sys; "
                "from pathlib import Path; "
                "site=(Path(sys.argv[1])/'Lib'/'site-packages').resolve(); "
                "model=Path(en_core_web_sm.__file__).resolve(); "
                "assert model.is_relative_to(site), 'Kokoro English model is outside the selected runtime'; "
                "spacy.load('en_core_web_sm', enable=['tok2vec', 'tagger']); "
                "print(torch.__version__)",
                str(dest),
            ],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if probe.returncode != 0:
        result["error"] = (probe.stderr or probe.stdout)[-800:]
        return result
    result["ok"] = True
    result["torch"] = probe.stdout.strip()
    return result


def base_python() -> Path:
    """Interpreter used to create the runtime virtualenv."""
    override = os.environ.get("CLIPPEDAI_RUNTIME_BASE_PYTHON", "").strip()
    if override:
        return Path(override)
    return Path(sys.base_prefix) / "python.exe"


def verify_base_python(python: Path) -> None:
    probe = subprocess.run(
        [str(python), "-c",
         "import sys,struct;print('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise SystemExit(f"[runtime] Base interpreter is not usable: {python}")
    version, bits = probe.stdout.strip().split("|")
    major, minor = (int(x) for x in version.split("."))
    if (major, minor) != REQUIRED_PYTHON or bits != "64":
        raise SystemExit(
            f"[runtime] The Clipify AI ML runtime must be CPython "
            f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} 64-bit; {python} is {version} ({bits}-bit).\n"
            f"          Install CPython {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} x64, or point\n"
            f"          CLIPPEDAI_RUNTIME_BASE_PYTHON at a matching interpreter."
        )


def ensure_venv(dest: Path, python: Path) -> Path:
    target = runtime_python(dest)
    if target.is_file():
        print(f"[runtime] Reusing existing virtualenv: {dest}")
        return target
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[runtime] Creating virtualenv: {dest}")
    result = subprocess.run([str(python), "-m", "venv", str(dest)])
    if result.returncode != 0:
        raise SystemExit("[runtime] Failed to create the runtime virtualenv")
    if not target.is_file():
        raise SystemExit(f"[runtime] Virtualenv created but {target} is missing")
    return target


def pip_install(python: Path, *args: str) -> None:
    cmd = [str(python), "-m", "pip", "install", "--disable-pip-version-check", *args]
    print(f"[runtime] {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"[runtime] pip install failed ({result.returncode})")


# Installed with --no-deps because the published metadata is stale.
#   facenet-pytorch 2.6.0 declares numpy<2.0.0, which cannot be satisfied
#   alongside whisperx's numpy>=2.1.0. It works with NumPy 2.x (the development
#   environment runs facenet-pytorch 2.6.0 with numpy 2.4.6), and its real
#   dependencies - torch, torchvision, Pillow - come from requirements-runtime.txt.
NO_DEPS = ("facenet-pytorch==2.6.0",)


def install_no_deps(python: Path) -> None:
    pip_install(python, "--no-deps", *NO_DEPS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the Clipify AI ML runtime")
    parser.add_argument("--dest", default="", help="Runtime location (default: %LOCALAPPDATA%\\ClippedAI\\runtime)")
    parser.add_argument("--check", action="store_true", help="Only report status")
    parser.add_argument("--force", action="store_true", help="Recreate the virtualenv from scratch")
    parser.add_argument("--json", action="store_true", help="Machine readable status only")
    args = parser.parse_args()

    dest = Path(args.dest).expanduser() if args.dest else default_destination()

    if args.check:
        status = check(dest)
        print(json.dumps(status) if args.json else json.dumps(status, indent=2))
        return 0 if status.get("ok") else 1

    if args.force and dest.exists():
        import shutil
        print(f"[runtime] Removing {dest}")
        shutil.rmtree(dest, ignore_errors=True)

    base = base_python()
    if not base.is_file():
        raise SystemExit(f"[runtime] Base Python not found: {base}")
    verify_base_python(base)

    python = ensure_venv(dest, base)
    pip_install(python, "--upgrade", "pip", "setuptools", "wheel")
    pip_install(python, "-r", str(REQUIREMENTS))
    install_no_deps(python)

    status = check(dest)
    print(json.dumps(status, indent=2))
    if not status.get("ok"):
        raise SystemExit("[runtime] The runtime was installed but verification failed")
    print(f"[runtime] Clipify AI ML runtime ready at {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
