"""Focused tests for YouTube OAuth, schedule generation, and clip discovery."""

from __future__ import annotations

import json
import http.client
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.youtube_publisher import (  # noqa: E402
    YouTubePublisher,
    YouTubePublisherError,
    build_schedule,
    discover_generated_clips,
    is_short_compatible_clip,
    select_trial_clips,
)


class MemoryTokenStore:
    def __init__(self):
        self.value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self):
        self.value = None


class FakeResponse:
    def __init__(self, value=None, headers=None):
        self._value = value or {}
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self._value).encode("utf-8")


class YouTubeOAuthTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryTokenStore()
        self.responses = [
            FakeResponse({"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}),
            FakeResponse({"items": [{"id": "UC-channel-123", "snippet": {"title": "My Channel"}}]}),
        ]
        self.requests = []

        def fake_urlopen(request, **_kwargs):
            self.requests.append(request)
            return self.responses.pop(0)

        self.publisher = YouTubePublisher(
            5000,
            environ={"YOUTUBE_CLIENT_ID": "desktop-client-id"},
            token_store=self.store,
            urlopen=fake_urlopen,
            clock=lambda: 1_800_000_000,
        )

    def tearDown(self):
        self.publisher.disconnect()

    def test_oauth_uses_pkce_loopback_and_does_not_require_a_client_secret(self):
        authorization_url = self.publisher.start_authorization()
        query = parse_qs(urlsplit(authorization_url).query)
        self.assertEqual(query["client_id"], ["desktop-client-id"])
        redirect_uri = urlsplit(query["redirect_uri"][0])
        self.assertEqual(redirect_uri.scheme, "http")
        self.assertEqual(redirect_uri.hostname, "127.0.0.1")
        self.assertTrue(1024 <= redirect_uri.port <= 65535)
        self.assertEqual(redirect_uri.path, "")
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["prompt"], ["select_account consent"])
        self.assertTrue(query["code_challenge"][0])
        self.assertNotIn("client_secret", query)

    def test_oauth_retrieves_exact_channel_and_requires_confirmation(self):
        query = parse_qs(urlsplit(self.publisher.start_authorization()).query)
        result = self.publisher.complete_authorization("auth-code", query["state"][0])
        self.assertEqual(result, {"channel_id": "UC-channel-123", "channel_title": "My Channel"})
        self.assertTrue(self.publisher.status()["connected"])
        self.assertFalse(self.publisher.status()["confirmed"])
        self.assertEqual(self.requests[1].get_header("Authorization"), "Bearer access")

        with self.assertRaisesRegex(YouTubePublisherError, "does not match"):
            self.publisher.confirm_channel("different-channel")
        self.publisher.confirm_channel("UC-channel-123")
        self.assertTrue(self.publisher.status()["confirmed"])
        self.assertEqual(self.publisher.status()["channel_title"], "My Channel")

    def test_loopback_listener_handles_oauth_callback_without_logging_or_using_google_network(self):
        authorization_url = self.publisher.start_authorization()
        query = parse_qs(urlsplit(authorization_url).query)
        redirect_uri = urlsplit(query["redirect_uri"][0])
        connection = http.client.HTTPConnection(redirect_uri.hostname, redirect_uri.port, timeout=3)
        connection.request("GET", f"/?{urlencode({'code': 'fake-code', 'state': query['state'][0]})}")
        response = connection.getresponse()
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "http://127.0.0.1:5000/?youtube_connected=1")
        connection.close()
        self.assertTrue(self.publisher.status()["connected"])
        self.assertFalse(self.publisher.status()["confirmed"])

    def test_callback_state_is_one_time_and_must_match(self):
        with self.assertRaisesRegex(YouTubePublisherError, "could not be verified"):
            self.publisher.complete_authorization("auth-code", "forged-state")
        self.assertEqual(self.requests, [])

    def test_multiple_authorized_channels_are_not_resolved_by_picking_the_first(self):
        publisher = YouTubePublisher(
            5000,
            environ={"YOUTUBE_CLIENT_ID": "desktop-client-id"},
            token_store=MemoryTokenStore(),
            urlopen=lambda *_args, **_kwargs: FakeResponse({
                "items": [
                    {"id": "UC-first", "snippet": {"title": "First"}},
                    {"id": "UC-second", "snippet": {"title": "Second"}},
                ],
            }),
        )
        with self.assertRaisesRegex(YouTubePublisherError, "will not choose one automatically"):
            publisher._get_channel("access")


class YouTubeScheduleTests(unittest.TestCase):
    def test_default_schedule_is_evenly_spaced_and_starts_tomorrow_in_ist(self):
        now = datetime(2026, 11, 24, 17, 14, tzinfo=timezone.utc)
        clips = [{"clip_id": str(index)} for index in range(8)]
        schedule = build_schedule(clips, now=now)
        self.assertEqual(
            [item["publish_at"] for item in schedule[:7]],
            [
                "2026-11-25T09:00:00+05:30",
                "2026-11-25T11:00:00+05:30",
                "2026-11-25T13:00:00+05:30",
                "2026-11-25T15:00:00+05:30",
                "2026-11-25T17:00:00+05:30",
                "2026-11-25T19:00:00+05:30",
                "2026-11-25T21:00:00+05:30",
            ],
        )
        self.assertEqual(schedule[7]["publish_at"], "2026-11-26T09:00:00+05:30")

    def test_invalid_schedule_window_or_cadence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "window"):
            build_schedule([], now=datetime.now(timezone.utc), start_hour=8)
        with self.assertRaisesRegex(ValueError, "between 1 and 13"):
            build_schedule([], now=datetime.now(timezone.utc), clips_per_day=14)

    def test_upload_requires_confirmed_channel_and_sets_private_publish_at(self):
        payloads = []
        store = MemoryTokenStore()
        store.set(json.dumps({
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": 2_000_000_000,
            "channel_id": "UC-confirmed",
        }))

        def fake_urlopen(request, **_kwargs):
            payloads.append(request)
            method = request.get_method()
            if method == "GET":
                return FakeResponse({"items": [{"id": "UC-confirmed", "snippet": {"title": "Confirmed"}}]})
            if method == "POST":
                return FakeResponse(headers={"Location": "https://www.googleapis.com/upload/session"})
            return FakeResponse({"id": "video-123"})

        publisher = YouTubePublisher(
            5000,
            environ={"YOUTUBE_CLIENT_ID": "desktop-client-id"},
            token_store=store,
            urlopen=fake_urlopen,
            clock=lambda: 1_800_000_000,
        )
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "short.mp4"
            video.write_bytes(b"video")
            publish_at = "2027-02-02T09:00:00+05:30"
            with self.assertRaisesRegex(YouTubePublisherError, "Confirm the exact"):
                publisher.upload_scheduled(
                    video,
                    title="Short",
                    description="",
                    publish_at=publish_at,
                    expected_channel_id="UC-confirmed",
                )
            self.assertEqual(payloads, [])

            publisher.confirm_channel("UC-confirmed")
            result = publisher.upload_scheduled(
                video,
                title="Short",
                description="",
                publish_at=publish_at,
                expected_channel_id="UC-confirmed",
            )

        self.assertEqual(result["video_id"], "video-123")
        self.assertEqual(len(payloads), 3)
        metadata = json.loads(payloads[1].data.decode("utf-8"))
        self.assertEqual(metadata["status"]["privacyStatus"], "private")
        self.assertEqual(metadata["status"]["publishAt"], publish_at)

    def test_upload_refuses_channel_switch_since_schedule_confirmation(self):
        store = MemoryTokenStore()
        store.set(json.dumps({
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": 2_000_000_000,
            "channel_id": "UC-new",
            "confirmed_channel_id": "UC-new",
        }))
        publisher = YouTubePublisher(
            5000,
            environ={"YOUTUBE_CLIENT_ID": "desktop-client-id"},
            token_store=store,
            urlopen=lambda *_args, **_kwargs: self.fail("Upload must not be initiated for a different channel."),
            clock=lambda: 1_800_000_000,
        )
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "short.mp4"
            video.write_bytes(b"video")
            with self.assertRaisesRegex(YouTubePublisherError, "channel changed"):
                publisher.upload_scheduled(
                    video,
                    title="Short",
                    description="",
                    publish_at="2027-02-02T09:00:00+05:30",
                    expected_channel_id="UC-original",
                )


class GeneratedClipDiscoveryTests(unittest.TestCase):
    def test_discovers_9_16_outputs_and_labels_landscape_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            first = root / "job-a" / "output"
            second = root / "job-b" / "output"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "clip_01.mp4").write_bytes(b"a" * 2048)
            (first / "vertical").mkdir()
            (first / "vertical" / "clip_01.mp4").write_bytes(b"e" * 2048)
            (second / "duplicate.mp4").write_bytes(b"a" * 2048)
            (first / "too_short.mp4").write_bytes(b"b" * 2048)
            (first / "too_long.mp4").write_bytes(b"c" * 2048)
            (first / "landscape.mp4").write_bytes(b"d" * 2048)
            media = {
                "job-a/output/clip_01.mp4": (40, 1080, 1920),
                "job-a/output/vertical/clip_01.mp4": (40, 1080, 1920),
                "job-b/output/duplicate.mp4": (40, 1080, 1920),
                "job-a/output/too_short.mp4": (29.99, 1080, 1920),
                "job-a/output/too_long.mp4": (50.01, 1080, 1920),
                "job-a/output/landscape.mp4": (40, 854, 480),
            }

            clips = discover_generated_clips(
                root,
                media_probe=lambda path: media[path.relative_to(root).as_posix()],
            )

        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[0]["duration"], 40)
        self.assertEqual(clips[0]["clip_id"], __import__("hashlib").sha256(b"a" * 2048).hexdigest())
        self.assertEqual(clips[0]["format_label"], "9:16 vertical output")
        self.assertTrue(clips[0]["short_compatible"])
        self.assertEqual(clips[1]["format_label"], "landscape source (not a Short)")
        self.assertFalse(clips[1]["short_compatible"])
        self.assertEqual(clips[2]["filename"], "vertical/clip_01.mp4")
        self.assertTrue(clips[2]["short_compatible"])

    def test_shorts_require_verified_9_16_dimensions(self):
        self.assertTrue(is_short_compatible_clip({"width": 1080, "height": 1920}))
        self.assertTrue(is_short_compatible_clip({"width": 540, "height": 960}))
        self.assertFalse(is_short_compatible_clip({"width": 854, "height": 480}))
        self.assertFalse(is_short_compatible_clip({"width": None, "height": None}))

    def test_trial_scope_is_only_first_three_verified_vertical_clips(self):
        clips = [
            {"clip_id": "source", "width": 854, "height": 480},
            *[
                {"clip_id": str(index), "width": 1080, "height": 1920}
                for index in range(5)
            ],
        ]
        self.assertEqual(
            [clip["clip_id"] for clip in select_trial_clips(clips)],
            ["0", "1", "2"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
