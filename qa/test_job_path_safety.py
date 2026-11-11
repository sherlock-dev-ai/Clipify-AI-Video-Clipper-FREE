"""Regression tests for caller-supplied job IDs used in filesystem paths."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import app  # noqa: E402


class JobPathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clipify-job-path-test-")
        self.root = Path(self.temp.name) / "jobs"
        self.root.mkdir()
        (self.root / "012345abcdef").mkdir()
        self.patch = patch.object(app, "JOBS", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_safe_job_directory_accepts_only_a_direct_child(self):
        self.assertEqual(app._safe_job_directory("012345abcdef"), (self.root / "012345abcdef").resolve())
        for job_id in ("", ".", "..", "../outside", r"..\outside", r"C:\outside", "C:"):
            with self.subTest(job_id=job_id):
                self.assertIsNone(app._safe_job_directory(job_id))

    def test_project_media_rejects_a_job_path_escape(self):
        outside = Path(self.temp.name) / "secret.mp4"
        outside.write_bytes(b"private")
        with app.app.test_request_context("/"):
            response, status = app.project_media("..", "input", outside.name)
        self.assertEqual(status, 404)
        self.assertEqual(response.get_json()["error"], "Project not found.")
        self.assertEqual(outside.read_bytes(), b"private")

    def test_start_rejects_a_traversal_job_id_before_creating_or_launching(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        with self.client_context() as client:
            response = client.post(
                "/api/start",
                base_url=f"http://127.0.0.1:{app.APP_PORT}",
                json={"job_id": "../outside"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(list(outside.iterdir()), [])

    def client_context(self):
        client = app.app.test_client()
        client.environ_base["HTTP_HOST"] = f"127.0.0.1:{app.APP_PORT}"
        return client


if __name__ == "__main__":
    unittest.main(verbosity=2)
