from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parent.parent
STAGE_SCRIPT = PROJECT / "build" / "installer_app" / "tools" / "stage_payload.py"
BUILDER_SCRIPT = PROJECT / "build" / "build_installer.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class StagePayloadLauncherOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(
            prefix="clipify-stage-payload-", dir=PROJECT / "build"
        )
        self.root = Path(self._temp.name)
        self.project = self.root / "fixture-project"
        self.app = self.project / "build" / "installer_app"
        self.script = self.app / "tools" / "stage_payload.py"
        self.out = self.app / "resources" / "payload"
        self.base_dist = self.project / "build" / "dist"
        self.app_dist = self.root / "current-app.dist"
        self.worker_dist = self.root / "current-worker.dist"

        self.script.parent.mkdir(parents=True)
        shutil.copy2(STAGE_SCRIPT, self.script)
        (self.app / "build").mkdir()
        (self.app / "build" / "icon.ico").write_bytes(b"icon")
        self.base_dist.mkdir(parents=True)
        (self.base_dist / "app.exe").write_bytes(b"old launcher")
        (self.base_dist / "requirements-runtime.txt").write_text(
            "clipsai==0.2.2\n", encoding="utf-8"
        )
        (self.project / "requirements-runtime.txt").write_text(
            "clipsai==0.2.3\n"
            "en-core-web-sm @ https://example.invalid/en_core_web_sm.whl#sha256=fixture\n",
            encoding="utf-8",
        )
        (self.base_dist / "python311.dll").write_bytes(b"baseline python runtime")
        self.out.mkdir(parents=True)
        (self.out / "user-preserved-sentinel.txt").write_text(
            "prior staged payload", encoding="utf-8"
        )

        self.app_dist.mkdir()
        (self.app_dist / "app.exe").write_bytes(b"current launcher")
        (self.app_dist / "launcher-support.dll").write_bytes(b"current launcher support")
        (self.app_dist / "static").mkdir()
        (self.app_dist / "static" / "app.css").write_text("current css", encoding="utf-8")

        self.worker_dist.mkdir()
        (self.worker_dist / "main.exe").write_bytes(b"validated worker")
        (self.worker_dist / "python311.dll").write_bytes(b"validated worker runtime")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def run_stager(self, expected_app_hash: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--app-dist", str(self.app_dist),
                "--expected-app-sha256", expected_app_hash,
                "--worker-dist", str(self.worker_dist),
                "--expected-worker-sha256", sha256(self.worker_dist / "main.exe"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_current_launcher_overlays_base_and_worker_is_final_overlay(self) -> None:
        result = self.run_stager(sha256(self.app_dist / "app.exe"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertEqual((self.out / "Clipify AI.exe").read_bytes(), b"current launcher")
        self.assertEqual((self.out / "launcher-support.dll").read_bytes(), b"current launcher support")
        self.assertEqual((self.out / "static" / "app.css").read_text(encoding="utf-8"), "current css")
        self.assertEqual(
            (self.out / "requirements-runtime.txt").read_text(encoding="utf-8"),
            (self.project / "requirements-runtime.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual((self.out / "main.exe").read_bytes(), b"validated worker")
        self.assertEqual((self.out / "python311.dll").read_bytes(), b"validated worker runtime")
        self.assertFalse((self.out / "app.exe").exists())

        backups = list((self.project / "build" / "installer-preserved").glob("payload-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            (backups[0] / "user-preserved-sentinel.txt").read_text(encoding="utf-8"),
            "prior staged payload",
        )

    def test_check_only_rejects_a_stale_runtime_manifest(self) -> None:
        result = self.run_stager(sha256(self.app_dist / "app.exe"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.out / "requirements-runtime.txt").write_text("clipsai==0.2.2\n", encoding="utf-8")
        check = subprocess.run(
            [sys.executable, str(self.script), "--check-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("requirements-runtime.txt differs from the current project manifest", check.stdout)

    def test_launcher_hash_mismatch_does_not_replace_staged_payload(self) -> None:
        result = self.run_stager("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app launcher hash", result.stdout)
        self.assertEqual(
            (self.out / "user-preserved-sentinel.txt").read_text(encoding="utf-8"),
            "prior staged payload",
        )

    def test_installer_builder_requires_a_validated_app_record_for_current_launcher(self) -> None:
        source = BUILDER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"--app-record"', source)
        self.assertIn("validated_app_launcher", source)
        self.assertIn('"--app-dist"', source)
        self.assertIn('"--expected-app-sha256"', source)
        self.assertIn('source_sha256_after', source)


if __name__ == "__main__":
    unittest.main()
