"""Route-level guards for YouTube channel confirmation and explicit scheduling."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import app  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name != "flask":
        raise
    app = None


class PublisherStub:
    def __init__(self):
        self.confirmed = False
        self.confirmed_ids = []
        self.uploads = []

    def status(self):
        return {
            "configured": True,
            "connected": True,
            "confirmed": self.confirmed,
            "channel_title": "Creator Channel",
            "channel_id": "UC-exact-channel",
        }

    def confirm_channel(self, channel_id):
        self.confirmed_ids.append(channel_id)
        if channel_id != "UC-exact-channel":
            raise ValueError("wrong channel")
        self.confirmed = True

    def upload_now(self, *_args, **_kwargs):
        self.uploads.append(True)
        return {"video_id": "should-not-be-created", "url": "https://youtube.com/shorts/should-not-be-created"}


@unittest.skipIf(app is None, "Flask is not installed in the current test runtime.")
class YouTubePublishRouteTests(unittest.TestCase):
    def setUp(self):
        self.old_testing = app.app.config.get("TESTING", False)
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        self.publisher = PublisherStub()
        self.patch_publisher = patch.object(app, "_youtube_publisher", return_value=self.publisher)
        self.patch_publisher.start()
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.patch_publisher.stop()
        app.app.config["TESTING"] = self.old_testing
        self.temp.cleanup()

    def open_local(self, path, *, method="GET", **kwargs):
        return self.client.open(path, method=method, base_url="http://127.0.0.1:5000", **kwargs)

    def test_status_shows_channel_and_confirmation_binds_to_exact_id(self):
        status = self.open_local("/api/publish/youtube/status").get_json()
        self.assertEqual(status["channel_title"], "Creator Channel")
        self.assertEqual(status["channel_id"], "UC-exact-channel")
        self.assertFalse(status["confirmed"])

        confirmed = self.open_local(
            "/api/publish/youtube/confirm-channel",
            method="POST",
            json={"channel_id": "UC-exact-channel"},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.publisher.confirmed_ids, ["UC-exact-channel"])

    def test_schedule_requires_separate_explicit_confirmation_and_channel_confirmation(self):
        no_explicit_confirm = self.open_local(
            "/api/publish/youtube/schedule",
            method="POST",
            json={"confirm": False, "schedule": []},
        )
        self.assertEqual(no_explicit_confirm.status_code, 400)
        self.assertEqual(self.publisher.uploads, [])

        not_channel_confirmed = self.open_local(
            "/api/publish/youtube/schedule",
            method="POST",
            json={"confirm": True, "schedule": [{"clip_id": "x"}]},
        )
        self.assertEqual(not_channel_confirmed.status_code, 403)
        self.assertEqual(self.publisher.uploads, [])

    def test_preview_rejects_landscape_as_shorts_but_allows_standard_video(self):
        landscape = {
            "clip_id": "landscape-id",
            "job_id": "job",
            "filename": "source.mp4",
            "title": "Source clip",
            "description": "",
            "duration": 40,
            "width": 854,
            "height": 480,
            "short_compatible": False,
        }
        with patch.object(app, "_youtube_clips", return_value=[landscape]):
            shorts = self.open_local(
                "/api/publish/youtube/preview",
                method="POST",
                json={"clip_ids": ["landscape-id"], "video_type": "shorts"},
            )
            standard = self.open_local(
                "/api/publish/youtube/preview",
                method="POST",
                json={"clip_ids": ["landscape-id"], "video_type": "standard"},
            )

        self.assertEqual(shorts.status_code, 400)
        self.assertIn("9:16", shorts.get_json()["error"])
        self.assertEqual(standard.status_code, 200)

    def test_public_trial_requires_exact_first_three_and_does_not_change_schedule_queue(self):
        clips = [
            {
                "clip_id": f"vertical-{index}",
                "job_id": "job",
                "filename": f"vertical_{index}.mp4",
                "title": f"Clip {index}",
                "description": "",
                "width": 1080,
                "height": 1920,
                "short_compatible": True,
            }
            for index in range(4)
        ]
        payload = {
            "confirm": True,
            "confirm_public_visibility": True,
            "visibility": "public",
            "channel_id": "UC-exact-channel",
            "clips": [
                {"clip_id": clip["clip_id"], "title": clip["title"], "description": ""}
                for clip in clips[:3]
            ],
        }
        with patch.object(app, "_youtube_clips", return_value=clips), patch.object(
            app, "_youtube_clip_path", return_value=Path(self.temp.name) / "clip.mp4"
        ):
            unconfirmed = self.open_local(
                "/api/publish/youtube/trial",
                method="POST",
                json=payload,
            )
            self.assertEqual(unconfirmed.status_code, 403)
            self.publisher.confirmed = True
            wrong_channel = self.open_local(
                "/api/publish/youtube/trial",
                method="POST",
                json={**payload, "channel_id": "UC-other"},
            )
            self.assertEqual(wrong_channel.status_code, 409)
            wrong_visibility = self.open_local(
                "/api/publish/youtube/trial",
                method="POST",
                json={**payload, "visibility": "unlisted"},
            )
            self.assertEqual(wrong_visibility.status_code, 400)
            with patch.object(app.threading, "Thread") as thread:
                started = self.open_local(
                    "/api/publish/youtube/trial",
                    method="POST",
                    json=payload,
                )
                self.assertEqual(started.status_code, 202)
                thread.return_value.start.assert_called_once()
            trial_id = started.get_json()["trial_id"]
            app._youtube_trial_jobs.pop(trial_id, None)
            self.assertEqual(self.publisher.uploads, [])
            self.assertEqual(app._youtube_schedule_jobs, {})

            rejected_payload = {**payload, "clips": payload["clips"] + [{"clip_id": "vertical-3"}]}
            rejected = self.open_local(
                "/api/publish/youtube/trial",
                method="POST",
                json=rejected_payload,
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(self.publisher.uploads, [])

    def test_direct_upload_is_blocked_until_the_exact_channel_is_confirmed(self):
        video = Path(self.temp.name) / "short.mp4"
        video.write_bytes(b"video")
        with patch.object(app, "_resolve_publish_video", return_value=(video, None)):
            response = self.open_local(
                "/api/publish/upload",
                method="POST",
                json={
                    "platform": "youtube",
                    "job_id": "job",
                    "filename": "short.mp4",
                    "title": "Short",
                    "description": "",
                },
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.publisher.uploads, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
