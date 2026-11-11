"""Build and verify the clean application payload used by the installer.

Usage: python tools/stage_payload.py [--check-only]
       [--app-dist APP_DIST --expected-app-sha256 SHA256]
       [--worker-dist WORKER_DIST --expected-worker-sha256 SHA256]
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
PROJECT = APP.parent.parent
BUILD_OUTPUT_DIR = Path(
    os.environ.get("CLIPIFY_BUILD_OUTPUT_DIR", str(PROJECT / "build"))
).resolve()
DIST = BUILD_OUTPUT_DIR / "dist"
OUT = APP / "resources" / "payload"
PRESERVED = PROJECT / "build" / "installer-preserved"
PRESERVED = Path(os.environ.get("CLIPIFY_PAYLOAD_BACKUP_DIR", str(PRESERVED))).resolve()

APP_EXE_SOURCE = "app.exe"
APP_EXE_NAME = "Clipify AI.exe"

EXCLUDE_DIRS = {
    "input", "output", "jobs", "__pycache__", ".git", ".venv", "venv",
    "narrate clips", "big narrate clips", "sliced clips", "test-output",
}
EXCLUDE_FILES = {
    "clippedai.vbs", "clippedai.bat", "clipifyai.vbs", "clipifyai.bat",
    "ffmpeg.log", ".env", ".env.example",
    "requirements-runtime.txt.orig", "icon.jpg",
}
BANNED_SUFFIXES = {".py", ".pyc", ".pyo", ".pyd.bak", ".env", ".bak", ".tmp"}
BANNED_NAMES = {".git", ".venv", "__pycache__"}


def wants(path: Path) -> bool:
    if path.name.lower() in EXCLUDE_FILES:
        return False
    if path.is_dir() and path.name.lower() in EXCLUDE_DIRS:
        return False
    return True


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def tree_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }


def sync_tree(source: Path, destination: Path) -> None:
    """Make destination match source, supporting locked directory roots.

    Windows security software can deny renaming an existing payload directory
    even when its files are writable. Callers preserve and verify a full backup
    before using this in-place fallback.
    """
    destination.mkdir(parents=True, exist_ok=True)
    source_files = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    }

    for path in destination.rglob("*"):
        if path.is_file() and path.relative_to(destination).as_posix() not in source_files:
            path.chmod(0o666)
            path.unlink()

    source_dirs = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_dir()
    }
    for path in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if path.relative_to(destination).as_posix() not in source_dirs:
            try:
                path.rmdir()
            except OSError:
                pass

    for path in source.rglob("*"):
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    if tree_manifest(source) != tree_manifest(destination):
        raise RuntimeError(f"directory copy verification failed: {destination}")


def verify_payload(root: Path) -> tuple[int, list[str]]:
    problems: list[str] = []
    total = 0
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        total += 1
        if any(part.lower() == "narrate clips" for part in item.relative_to(root).parts[:-1]):
            problems.append(f"user-provided narration footage must not ship: {item.relative_to(root)}")
        name = item.name.lower()
        if item.suffix.lower() in BANNED_SUFFIXES:
            problems.append(f"prohibited file type: {item.relative_to(root)}")
        if name in BANNED_NAMES or name.endswith((".bat", ".vbs")):
            problems.append(f"prohibited launcher/archive: {item.relative_to(root)}")
        if item.suffix.lower() in {".txt", ".json", ".log", ".cfg", ".ini", ".example", ".ps1", ".md"}:
            try:
                text = item.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # Reject paths tied to the current checkout, wherever it lives.
            # Keep the legacy %LOCALAPPDATA%\\ClippedAI user-data root intact.
            for needle in (str(PROJECT), ".venv"):
                if needle.lower() in text.lower():
                    problems.append(
                        f"developer path {needle!r} inside {item.relative_to(root)}"
                    )
                    break
    if not (root / APP_EXE_NAME).is_file():
        problems.append(f"missing {APP_EXE_NAME}")
    source_requirements = PROJECT / "requirements-runtime.txt"
    payload_requirements = root / "requirements-runtime.txt"
    if not source_requirements.is_file():
        problems.append("current project requirements-runtime.txt is missing")
    elif not payload_requirements.is_file():
        problems.append("payload requirements-runtime.txt is missing")
    elif sha256(payload_requirements) != sha256(source_requirements):
        problems.append("payload requirements-runtime.txt differs from the current project manifest")
    return total, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--worker-dist", type=Path,
                        help="validated Nuitka main.dist directory to overlay on the payload")
    parser.add_argument("--expected-worker-sha256",
                        help="required SHA-256 for worker-dist/main.exe")
    parser.add_argument("--app-dist", type=Path,
                        help="validated current app.dist directory to overlay on build/dist")
    parser.add_argument("--expected-app-sha256",
                        help="required SHA-256 for app-dist/app.exe")
    args = parser.parse_args()

    if bool(args.worker_dist) != bool(args.expected_worker_sha256):
        parser.error("--worker-dist and --expected-worker-sha256 must be supplied together")
    if bool(args.app_dist) != bool(args.expected_app_sha256):
        parser.error("--app-dist and --expected-app-sha256 must be supplied together")
    if not DIST.exists():
        print(f"FAIL: build/dist not found at {DIST}")
        return 1

    if args.check_only:
        if not OUT.exists():
            print(f"FAIL: staged payload not found at {OUT}")
            return 1
        total, problems = verify_payload(OUT)
        size_mb = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1024 / 1024
        print(f"payload: {total} files, {size_mb:.1f} MB")
        if problems:
            print("\nPAYLOAD VERIFICATION FAILED:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("payload verification PASSED (no source, no dev paths, no wrappers)")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    staged = OUT.with_name(f".payload-stage-{stamp}-{os.getpid()}")
    if staged.exists():
        raise RuntimeError(f"refusing to reuse existing staging directory: {staged}")
    staged.mkdir(parents=True)

    kept_files = kept_dirs = 0
    for src in DIST.iterdir():
        if not wants(src):
            continue
        dest = staged / src.name
        if src.is_dir():
            shutil.copytree(src, dest)
            kept_dirs += 1
            kept_files += sum(1 for item in dest.rglob("*") if item.is_file())
        else:
            shutil.copy2(src, dest)
            kept_files += 1

    legacy = staged / APP_EXE_SOURCE
    if args.app_dist:
        app_dist = args.app_dist.resolve()
        app_exe = app_dist / "app.exe"
        if not app_exe.is_file():
            print(f"FAIL: compiled app launcher missing at {app_exe}")
            return 1
        actual_app_hash = sha256(app_exe)
        expected_app_hash = args.expected_app_sha256.strip().upper()
        if actual_app_hash != expected_app_hash:
            print(f"FAIL: app launcher hash {actual_app_hash} != expected {expected_app_hash}")
            return 1
        for src in app_dist.rglob("*"):
            if not src.is_file():
                continue
            dest = staged / src.relative_to(app_dist)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        print(f"validated app launcher overlay: {app_exe} sha256={actual_app_hash}")

    if legacy.exists():
        legacy.rename(staged / APP_EXE_NAME)

    if args.worker_dist:
        worker_dist = args.worker_dist.resolve()
        worker_exe = worker_dist / "main.exe"
        if not worker_exe.is_file():
            print(f"FAIL: validated worker missing at {worker_exe}")
            return 1
        actual_worker_hash = sha256(worker_exe)
        expected_worker_hash = args.expected_worker_sha256.strip().upper()
        if actual_worker_hash != expected_worker_hash:
            print(f"FAIL: worker hash {actual_worker_hash} != expected {expected_worker_hash}")
            return 1
        for src in worker_dist.rglob("*"):
            if not src.is_file():
                continue
            dest = staged / src.relative_to(worker_dist)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        print(f"validated worker overlay: {worker_exe} sha256={actual_worker_hash}")

    # build/dist can retain an older runtime manifest. The installer must use
    # the current project dependency list, including pinned repairs for existing
    # installed features, rather than silently shipping that stale copy.
    runtime_requirements = PROJECT / "requirements-runtime.txt"
    if not runtime_requirements.is_file():
        print(f"FAIL: current runtime manifest missing at {runtime_requirements}")
        return 1
    shutil.copy2(runtime_requirements, staged / "requirements-runtime.txt")
    print(f"staged current runtime manifest sha256={sha256(runtime_requirements)}")

    for ico in (HERE.parent / "build").glob("*.ico"):
        shutil.copy2(ico, staged / ico.name)

    print(f"staged {kept_files} files in {kept_dirs} directories -> {staged}")
    total, problems = verify_payload(staged)
    size_mb = sum(p.stat().st_size for p in staged.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"payload: {total} files, {size_mb:.1f} MB")
    if problems:
        print("\nPAYLOAD VERIFICATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        print(f"staged payload retained for inspection at {staged}")
        return 1

    PRESERVED.mkdir(parents=True, exist_ok=True)
    backup = PRESERVED / f"payload-{stamp}"
    if backup.exists():
        raise RuntimeError(f"refusing to reuse existing payload backup: {backup}")
    if OUT.exists():
        try:
            OUT.rename(backup)
        except OSError as move_error:
            if not OUT.exists() or backup.exists():
                raise
            print(
                "payload directory rename was denied; preserving a verified "
                "copy and syncing files in place"
            )
            shutil.copytree(OUT, backup)
            if tree_manifest(OUT) != tree_manifest(backup):
                raise RuntimeError(f"previous payload backup verification failed: {backup}") from move_error
            try:
                sync_tree(staged, OUT)
                _count, final_problems = verify_payload(OUT)
                if final_problems:
                    raise RuntimeError(
                        "in-place payload promotion verification failed: "
                        + "; ".join(final_problems)
                    )
            except Exception:
                sync_tree(backup, OUT)
                raise
            print(f"previous staged payload preserved at {backup}")
            try:
                shutil.rmtree(staged)
            except OSError:
                print(f"staged payload retained for inspection at {staged}")
            print("payload verification PASSED (no source, no dev paths, no wrappers)")
            return 0
    try:
        staged.rename(OUT)
    except Exception:
        if backup.exists() and not OUT.exists():
            backup.rename(OUT)
        raise
    if backup.exists():
        print(f"previous staged payload preserved at {backup}")
    print("payload verification PASSED (no source, no dev paths, no wrappers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
