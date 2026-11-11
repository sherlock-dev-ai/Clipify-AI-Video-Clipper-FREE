"""Focused tests for YouTube URL validation and downloader job transitions."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import app  # noqa: E402


VIDEO_ID = "jNQXAC9IVRw"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


class InlineThread:
    def __init__(self, *, target, daemon=False, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class FakeDownloader:
    def __init__(self, command, *, output=True, line_output="download:100%|12|12|1MiB/s|00:00\n", return_code=0, **_kwargs):
        self.command = command
        self.stdout = io.StringIO(line_output)
        self.return_code = return_code
        self.ended = False
        if output:
            template = command[command.index("-o") + 1]
            target = Path(template.replace("%(ext)s", "mp4"))
            target.write_bytes(b"mock-download-for-route-test")

    def wait(self, timeout=None):
        self.ended = True
        return self.return_code

    def poll(self):
        return self.return_code if self.ended else None

    def terminate(self):
        self.ended = True

    def kill(self):
        self.ended = True


class YouTubeUrlTests(unittest.TestCase):
    def test_supported_video_urls_normalize_to_one_watch_url(self):
        urls = (
            CANONICAL,
            f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}&t=20",
            f"https://youtu.be/{VIDEO_ID}?si=share-token",
            f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share",
            f"https://m.youtube.com/watch?v={VIDEO_ID}",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(app._normalize_youtube_url(url), CANONICAL)
                self.assertTrue(app._is_youtube_url(url))

    def test_malformed_or_ambiguous_urls_are_rejected(self):
        urls = (
            "",
            "https://youtube.com.evil.example/watch?v=" + VIDEO_ID,
            "ftp://youtube.com/watch?v=" + VIDEO_ID,
            "https://www.youtube.com/playlist?list=PL1234567890",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch?v=" + VIDEO_ID + "&v=abcdefghijk",
            "https://user@example.com@youtube.com/watch?v=" + VIDEO_ID,
            "https://youtube.com:8443/watch?v=" + VIDEO_ID,
            "https://youtu.be/" + VIDEO_ID + "/extra",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertIsNone(app._normalize_youtube_url(url))
                self.assertFalse(app._is_youtube_url(url))


class YouTubeImportRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clipify-youtube-test-")
        self.jobs_dir = Path(self.temp.name) / "jobs"
        self.jobs_dir.mkdir()
        with app.jobs_lock:
            app.jobs.clear()
        self.client = app.app.test_client()
        self.base_url = f"http://127.0.0.1:{app.APP_PORT}"
        self.patches = [
            patch.object(app, "JOBS", self.jobs_dir),
            patch.object(app, "_yt_dlp_command", return_value=["yt-dlp"]),
            patch.object(app, "_ffmpeg_path", return_value=str(Path(sys.executable).with_name("ffmpeg.exe"))),
            patch.object(app.threading, "Thread", InlineThread),
        ]
        for item in self.patches:
            item.start()

    def open_local(self, path, *, method="GET", **kwargs):
        return self.client.open(path, method=method, base_url=self.base_url, **kwargs)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()
        with app.jobs_lock:
            app.jobs.clear()

    def test_valid_url_is_canonicalized_and_ffprobe_valid_download_becomes_ready(self):
        observed = {}

        def run(command, **kwargs):
            observed["ffprobe"] = command
            return SimpleNamespace(stdout="video\naudio\n", returncode=0)

        with patch.object(app.subprocess, "Popen", side_effect=lambda command, **kwargs: observed.setdefault("process", FakeDownloader(command, **kwargs))), patch.object(app.subprocess, "run", side_effect=run):
            response = self.open_local("/api/import-youtube", method="POST", json={"url": f"https://youtu.be/{VIDEO_ID}?si=tracking"})

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        if "process" not in observed:
            self.fail(f"Downloader never started; job status: {self.open_local(f'/api/status/{job_id}').get_json()}")
        self.assertEqual(observed["process"].command[-1], CANONICAL)
        status = self.open_local(f"/api/status/{job_id}").get_json()
        self.assertEqual(status["status"], "uploaded")
        self.assertEqual(status["progress"], 100)
        self.assertTrue((self.jobs_dir / job_id / "input" / "youtube.mp4").is_file())

    def test_ffmpeg_lookup_failure_ends_the_job_instead_of_leaving_download_spinner(self):
        with patch.object(app, "_ffmpeg_path", side_effect=RuntimeError("FFmpeg was not found.")):
            response = self.open_local("/api/import-youtube", method="POST", json={"url": CANONICAL})

        self.assertEqual(response.status_code, 202)
        job_id = response.get_json()["job_id"]
        status = self.open_local(f"/api/status/{job_id}").get_json()
        self.assertEqual(status["status"], "error")
        self.assertIn("FFmpeg was not found", status["detail"])

    def test_failed_download_can_be_retried_as_a_new_job(self):
        calls = 0

        def popen(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeDownloader(command, output=False, line_output="ERROR: video unavailable\n", return_code=1, **kwargs)
            return FakeDownloader(command, output=True, **kwargs)

        with patch.object(app.subprocess, "Popen", side_effect=popen), patch.object(
            app.subprocess, "run", return_value=SimpleNamespace(stdout="video\naudio\n", returncode=0)
        ):
            failed = self.open_local("/api/import-youtube", method="POST", json={"url": CANONICAL}).get_json()
            retried = self.open_local("/api/import-youtube", method="POST", json={"url": CANONICAL}).get_json()

        self.assertNotEqual(failed["job_id"], retried["job_id"])
        self.assertEqual(self.open_local(f"/api/status/{failed['job_id']}").get_json()["status"], "error")
        retry_status = self.open_local(f"/api/status/{retried['job_id']}").get_json()
        self.assertEqual(retry_status["status"], "uploaded", retry_status)

    def test_invalid_url_is_rejected_before_downloader_start(self):
        with patch.object(app.subprocess, "Popen") as popen:
            response = self.open_local("/api/import-youtube", method="POST", json={"url": "ftp://youtube.com/watch?v=" + VIDEO_ID})
        self.assertEqual(response.status_code, 400)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
