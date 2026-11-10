"""Build an immutable, versioned Windows installer artifact.

    python build/build_installer.py

Output (one new artifact per run; previous artifacts are retained):

    installer\\Clipify AI Setup-<build-id>.exe

The build refuses to report success unless that file exists, is a real PE
executable, and is non-trivial in size. It also verifies the staged application
payload contains no readable proprietary source and no developer paths, so a
dirty working directory can never be shipped by accident.
"""

from __future__ import annotations

import json
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BUILD_OUTPUT_DIR = Path(
    os.environ.get("CLIPIFY_BUILD_OUTPUT_DIR", str(PROJECT / "build"))
).resolve()
BUILD_DIST = BUILD_OUTPUT_DIR / "dist"
APP = PROJECT / "build" / "installer_app"
BUILD_ID = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
ARG_PARSER = argparse.ArgumentParser(description="Build Clipify AI's Windows installer")
ARG_PARSER.add_argument(
    "--isolated-qa",
    action="store_true",
    help="give this QA package a unique NSIS identity so it cannot upgrade another setup install",
)
ARG_PARSER.add_argument(
    "--qa-launcher-sha256",
    help="expected app.exe SHA-256 for an isolated QA payload; never applies to production builds",
)
ARG_PARSER.add_argument(
    "--worker-record",
    type=Path,
    help="validated worker build record to package; defaults to the historical recovery record",
)
ARG_PARSER.add_argument(
    "--app-record",
    type=Path,
    help="validated current app-launcher build record; allowed only for isolated QA packages",
)
ARGS = ARG_PARSER.parse_args()
QA_APP_ID = f"dev.sherlock.clipifyai.setup.qa.{BUILD_ID.replace('-', '.') }"
QA_PRODUCT_NAME = f"Clipify AI Setup QA {BUILD_ID}"
QA_INSTALL_SLUG = f"ClipifyAI-QA-{BUILD_ID}"
DIST = APP / f"release-{BUILD_ID}"
FINAL_DIR = PROJECT / "installer"
FINAL_NAME = "Clipify AI Setup.exe"
FINAL_EXE = FINAL_DIR / FINAL_NAME
VALIDATION_DIR = PROJECT / "build" / f"installer-validation-{BUILD_ID}"
WORKER_RECORD = (
    ARGS.worker_record.resolve()
    if ARGS.worker_record
    else PROJECT / "build" / "worker_recovery_20261011" / "worker_retry6_pkgresources_result.json"
)
# Refreshed from the current-source Nuitka build recorded in the QA report.
EXPECTED_LAUNCHER_SHA256 = "0FF56C16A84233FBC5226428DC91A57353D90280C9496F5D13ECCD2AB4971A1F"

NPM = r"C:\Program Files\nodejs\npm.cmd"


def select_python() -> Path:
    """Use the project venv when it starts; fall back to the active Python.

    A venv can survive after its base interpreter has been removed or moved.
    Checking only for the shim file makes installer builds fail late with
    "No Python at ..." even when the caller has a working Python available.
    """
    candidate = PROJECT / ".venv" / "Scripts" / "python.exe"
    try:
        probe = subprocess.run(
            [str(candidate), "--version"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
        )
        if probe.returncode == 0:
            return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    fallback = Path(sys.executable)
    print(f"[python] project venv is unavailable; using {fallback}")
    return fallback


PYTHON = select_python()


def banner(text: str) -> None:
    bar = "=" * 62
    print(f"\n{bar}\n{text}\n{bar}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validated_worker() -> tuple[Path, str, str]:
    if not WORKER_RECORD.is_file():
        raise SystemExit(f"FAIL: validated worker build record missing: {WORKER_RECORD}")
    record = json.loads(WORKER_RECORD.read_text(encoding="utf-8"))
    source = PROJECT / "main.py"
    current_source_hash = sha256(source)
    if record.get("status") != "built" or record.get("exit_code") != 0:
        raise SystemExit("FAIL: recovery record does not show a successful worker build")
    if record.get("source_sha256", "").upper() != current_source_hash:
        raise SystemExit(
            "FAIL: validated worker was built from a different main.py; "
            f"record={record.get('source_sha256')} current={current_source_hash}"
        )
    if record.get("expected_source_sha256", "").upper() != current_source_hash:
        raise SystemExit("FAIL: worker build's expected source hash does not match current source")
    worker_dist = Path(record["executable"]).resolve().parent
    worker_exe = worker_dist / "main.exe"
    if not worker_exe.is_file():
        raise SystemExit(f"FAIL: validated worker executable missing: {worker_exe}")
    actual_worker_hash = sha256(worker_exe)
    expected_worker_hash = record.get("executable_sha256", "").upper()
    if actual_worker_hash != expected_worker_hash:
        raise SystemExit(
            f"FAIL: worker hash mismatch: record={expected_worker_hash} actual={actual_worker_hash}"
        )
    if not (worker_dist / "python311.dll").is_file():
        raise SystemExit(f"FAIL: worker distribution support runtime missing: {worker_dist / 'python311.dll'}")
    return worker_dist, current_source_hash, actual_worker_hash


def validated_app_launcher() -> tuple[Path | None, str | None, str | None]:
    if not ARGS.app_record:
        return None, None, None
    if not ARGS.isolated_qa:
        raise SystemExit("FAIL: --app-record is allowed only with --isolated-qa")
    if ARGS.qa_launcher_sha256:
        raise SystemExit("FAIL: --app-record cannot be combined with --qa-launcher-sha256")

    record_path = ARGS.app_record.resolve()
    if not record_path.is_file():
        raise SystemExit(f"FAIL: app build record missing: {record_path}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    source = PROJECT / "app.py"
    current_source_hash = sha256(source)
    if record.get("status") != "built" or record.get("exit_code") != 0:
        raise SystemExit("FAIL: app build record does not show a successful launcher build")
    if record.get("source_sha256", "").upper() != current_source_hash:
        raise SystemExit("FAIL: app launcher was built from a different app.py")
    if record.get("source_sha256_after", "").upper() != current_source_hash:
        raise SystemExit("FAIL: app.py changed during its recorded launcher build")

    executable = Path(record["executable"]).resolve()
    if executable.name.lower() != "app.exe" or not executable.is_file():
        raise SystemExit(f"FAIL: expected compiled app.exe is missing: {executable}")
    actual_hash = sha256(executable)
    expected_hash = record.get("executable_sha256", "").upper()
    if actual_hash != expected_hash:
        raise SystemExit(
            f"FAIL: app launcher hash mismatch: record={expected_hash} actual={actual_hash}"
        )
    if not (executable.parent / "static").is_dir() or not (executable.parent / "templates").is_dir():
        raise SystemExit("FAIL: compiled app launcher distribution is missing static/templates")
    return executable.parent, current_source_hash, actual_hash


def preserve_generated_assets() -> None:
    # The asset preparation step overwrites generated PNGs. Retain their prior
    # versions alongside this run's logs before touching them.
    candidates = [
        APP / "build" / "logo-round.png",
        APP / "build" / "logo.png",
        APP / "renderer" / "logo-round.png",
        APP / "renderer" / "logo.png",
    ]
    backup_root = VALIDATION_DIR / "pre-build-assets"
    for source in candidates:
        if source.is_file():
            target = backup_root / source.relative_to(APP)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def run(command: list[str], cwd: Path, label: str, env: dict[str, str] | None = None) -> None:
    print(f"\n--- {label} ---")
    started = time.time()
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", shell=False, env=env
    )
    elapsed = time.time() - started
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_")
    (VALIDATION_DIR / f"{safe_label}.stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (VALIDATION_DIR / f"{safe_label}.stderr.log").write_text(result.stderr or "", encoding="utf-8")
    if result.stdout:
        tail = result.stdout.strip().splitlines()[-25:]
        print("\n".join(tail))
    if result.returncode != 0:
        print(f"\n!!! {label} FAILED (exit {result.returncode})")
        if result.stderr:
            print(result.stderr.strip()[-3000:])
        raise SystemExit(result.returncode)
    print(f"[{label}] ok in {elapsed:.1f}s")


def main() -> int:
    global EXPECTED_LAUNCHER_SHA256
    banner("CLIPIFY AI INSTALLER BUILD")

    VALIDATION_DIR.mkdir(parents=True, exist_ok=False)
    worker_dist, source_hash, worker_hash = validated_worker()
    app_dist, app_source_hash, app_launcher_hash = validated_app_launcher()
    print(f"[worker] current source SHA-256: {source_hash}")
    print(f"[worker] validated executable SHA-256: {worker_hash}")
    print(f"[worker] standalone distribution: {worker_dist}")
    if app_dist:
        EXPECTED_LAUNCHER_SHA256 = app_launcher_hash or ""
        print(f"[app] current source SHA-256: {app_source_hash}")
        print(f"[app] validated launcher SHA-256: {EXPECTED_LAUNCHER_SHA256}")
        print(f"[app] standalone distribution: {app_dist}")

    if ARGS.qa_launcher_sha256:
        if not ARGS.isolated_qa:
            raise SystemExit("FAIL: --qa-launcher-sha256 is allowed only with --isolated-qa")
        EXPECTED_LAUNCHER_SHA256 = ARGS.qa_launcher_sha256.strip().upper()
        if not re.fullmatch(r"[0-9A-F]{64}", EXPECTED_LAUNCHER_SHA256):
            raise SystemExit("FAIL: --qa-launcher-sha256 must be a 64-character SHA-256")

    # Production packaging still requires the root launcher to match the
    # current build. The staged payload is regenerated from BUILD_DIST below,
    # so validate that copy after staging instead of rejecting its old contents
    # before the refresh can run.
    launcher_sources = {
        (app_dist / "app.exe") if app_dist else (BUILD_DIST / "app.exe")
    }
    if not ARGS.isolated_qa:
        launcher_sources.add(Path(r"L:\ClipifyAI\Clipify AI.exe"))
    for launcher in sorted(launcher_sources, key=str):
        if not launcher.is_file():
            raise SystemExit(f"FAIL: validated launcher copy missing: {launcher}")
        launcher_hash = sha256(launcher)
        if launcher_hash != EXPECTED_LAUNCHER_SHA256:
            raise SystemExit(
                f"FAIL: launcher is not the validated build: {launcher} sha256={launcher_hash}"
            )
        print(f"[launcher] {launcher} sha256={launcher_hash}")

    # Refuse to mix this worker with stale standalone support files.
    for source in worker_dist.rglob("*"):
        if not source.is_file() or source.name.lower() == "main.exe":
            continue
        relative = source.relative_to(worker_dist)
        staged_support = BUILD_DIST / relative
        if not staged_support.is_file() or sha256(staged_support) != sha256(source):
            raise SystemExit(f"FAIL: worker support file differs from {BUILD_DIST}: {relative}")

    if not APP.exists():
        print(f"FAIL: installer app not found at {APP}")
        return 1

    preserve_generated_assets()

    # 1. Reuse the already-generated brand PNGs when present. Regeneration is
    # optional for a packaging-only build and would otherwise require Pillow in
    # the build interpreter even though the verified assets are already staged.
    brand_assets = [APP / "build" / "logo-round.png", APP / "build" / "logo.png"]
    if all(asset.is_file() and asset.stat().st_size > 0 for asset in brand_assets):
        for asset in brand_assets:
            print(f"[assets] reusing {asset} sha256={sha256(asset)}")
    else:
        run([str(PYTHON), "tools/prepare_assets.py"], APP, "Clipify AI monogram assets")
        if not all(asset.is_file() and asset.stat().st_size > 0 for asset in brand_assets):
            raise SystemExit("FAIL: brand asset generation did not produce both required PNGs")

    # 1b. The renderer is packed into app.asar from renderer/**, so the brand
    #     PNGs must live *inside* renderer/. Referencing ../build/logo-round.png
    #     shipped nothing and every logo rendered as a broken-image glyph.
    renderer = APP / "renderer"
    for name in ("logo-round.png", "logo.png"):
        source_asset = APP / "build" / name
        if source_asset.exists():
            shutil.copy2(source_asset, renderer / name)
            print(f"[assets] copied {name} -> renderer/")

    # 2. Rebuild the verified application payload (no source, no dev paths).
    stage_command = [
        str(PYTHON), "tools/stage_payload.py", "--worker-dist", str(worker_dist),
        "--expected-worker-sha256", worker_hash,
    ]
    if app_dist:
        stage_command.extend([
            "--app-dist", str(app_dist),
            "--expected-app-sha256", EXPECTED_LAUNCHER_SHA256,
        ])
    run(
        stage_command,
        APP,
        "Stage + verify application payload",
    )
    staged_payload = APP / "resources" / "payload"
    staged_launcher_hash = sha256(staged_payload / "Clipify AI.exe")
    staged_worker_hash = sha256(staged_payload / "main.exe")
    if staged_launcher_hash != EXPECTED_LAUNCHER_SHA256:
        raise SystemExit(f"FAIL: staged launcher hash mismatch: {staged_launcher_hash}")
    if staged_worker_hash != worker_hash:
        raise SystemExit(f"FAIL: staged worker hash mismatch: {staged_worker_hash}")
    print(f"[payload] launcher SHA-256: {staged_launcher_hash}")
    print(f"[payload] worker SHA-256: {staged_worker_hash}")

    # 4. Package into a fresh, uniquely named output directory.
    #    Reusing one directory is fragile here: Windows Defender routinely holds
    #    a freshly written app.asar open for a few seconds, which made
    #    electron-builder fail with EBUSY on the second consecutive build.
    global DIST
    DIST = APP / f"release-{int(time.time())}"
    build_command = [NPM, "run", "dist", "--", f"--config.directories.output={DIST.name}"]
    build_env = os.environ.copy()
    electron_dist = APP / "node_modules" / "electron" / "dist"
    if (electron_dist / "electron.exe").exists():
        # The installed electron package already contains the exact binary the
        # builder otherwise tries to download again. Use it so offline builds
        # work and the installer cannot silently acquire a different release.
        build_command.append(f"--config.electronDist={electron_dist}")
        print(f"[electron] packaging from local distribution {electron_dist}")
    package_identity = {"app_id": "dev.sherlock.clipifyai.setup", "product_name": "Clipify AI Setup"}
    if ARGS.isolated_qa:
        # Electron Builder uses the AppId to discover and uninstall an existing
        # per-user setup package before installing. QA needs a clean, separate
        # registration and directory so it can never route through a previous
        # release or test copy.
        build_command.extend([
            f"--config.appId={QA_APP_ID}",
            f"--config.productName={QA_PRODUCT_NAME}",
            # Use an assisted QA setup so the harness can direct NSIS to a
            # fresh shell directory. Electron's per-user NSIS target is based
            # on the package name and ignores an overridden LOCALAPPDATA, so
            # unique AppIds alone do not isolate repeated QA shell installs.
            "--config.nsis.oneClick=false",
            "--config.nsis.allowToChangeInstallationDirectory=true",
            # NSIS is only the bootstrap shell. The actual custom installer UI
            # is the Electron app launched after the shell finishes.
            "--config.nsis.runAfterFinish=true",
            f"--config.extraMetadata.clipifyQaInstallSlug={QA_INSTALL_SLUG}",
        ])
        package_identity = {
            "app_id": QA_APP_ID,
            "product_name": QA_PRODUCT_NAME,
            "install_slug": QA_INSTALL_SLUG,
            "custom_ui_after_finish": True,
        }
        print(f"[isolated-qa] unique NSIS identity: {package_identity}")

    # Some electron-builder releases fetch rcedit even though this project
    # already has the compatible Windows utility bundled with electron-winstaller.
    # Reuse that tool for x64 resource editing when it is available.
    vendor_rcedit = APP / "node_modules" / "electron-winstaller" / "vendor" / "rcedit.exe"
    if vendor_rcedit.exists():
        rcedit_dir = APP / "build" / f"offline-rcedit-{BUILD_ID}"
        rcedit_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vendor_rcedit, rcedit_dir / "rcedit-x64.exe")
        build_env["ELECTRON_BUILDER_RCEDIT_PATH"] = str(rcedit_dir)
        print(f"[rcedit] using bundled tool {vendor_rcedit}")

    run(
        build_command,
        APP,
        "Package Electron + NSIS installer",
        env=build_env,
    )

    # Inspect the actual Electron archive and extraResources before publishing
    # the outer setup executable. Source files existing outside app.asar are
    # not sufficient proof that the custom UI reached the package.
    run(
        [
            "node",
            "tools/verify_packaged_ui.js",
            str(DIST / "win-unpacked"),
            str(APP),
            QA_INSTALL_SLUG if ARGS.isolated_qa else "",
        ],
        APP,
        "Verify packaged custom installer UI",
        env=build_env,
    )

    # 5. Locate and publish the artifact.
    candidates = sorted(DIST.rglob("*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        print("\nBUILD FAILED: no .exe produced by electron-builder.")
        return 1

    source = next((c for c in candidates if c.name.endswith("Setup.exe")), candidates[0])
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, FINAL_EXE)

    # 6. Verify the deliverable for real.
    if not FINAL_EXE.exists():
        print("BUILD FAILED: expected installer was not produced.")
        return 1
    size = FINAL_EXE.stat().st_size
    head = FINAL_EXE.read_bytes()[:2]
    if head != b"MZ":
        print(f"BUILD FAILED: {FINAL_EXE} is not a Windows PE executable.")
        return 1
    if size < 5 * 1024 * 1024:
        print(f"BUILD FAILED: installer is implausibly small ({size} bytes).")
        return 1

    stat = FINAL_EXE.stat()
    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))

    banner("CLIPIFY AI INSTALLER BUILD\n\nSUCCESS")
    print(f"Installer:\n{FINAL_EXE}")
    print(f"\nSize:\n{size / 1024 / 1024:.1f} MB")
    print(f"\nCreated:\n{created}")
    print(f"Modified:\n{modified}")
    installer_hash = sha256(FINAL_EXE)
    build_result = {
        "build_id": BUILD_ID,
        "source": str(PROJECT / "main.py"),
        "source_sha256": source_hash,
        "app_source_sha256": app_source_hash,
        "launcher_sha256": EXPECTED_LAUNCHER_SHA256,
        "launcher_dist": str(app_dist) if app_dist else str(BUILD_DIST),
        "app_build_record": str(ARGS.app_record.resolve()) if ARGS.app_record else None,
        "worker_sha256": worker_hash,
        "worker_dist": str(worker_dist),
        "installer": str(FINAL_EXE),
        "installer_sha256": installer_hash,
        "installer_size_bytes": size,
        "package_identity": package_identity,
        "custom_ui_archive_verified": True,
        "qa_nsis_run_after_finish": True if ARGS.isolated_qa else None,
        "copied_from": str(source),
        "result": "built; installation validation pending",
    }
    result_path = VALIDATION_DIR / "build-result.json"
    result_path.write_text(json.dumps(build_result, indent=2), encoding="utf-8")
    print(f"\nCopied from:\n{source}")
    print(f"\nSHA-256:\n{installer_hash}")
    print(f"\nBuild record:\n{result_path}")
    print("\nNOT YET TESTED - run the installer to verify the screens.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
