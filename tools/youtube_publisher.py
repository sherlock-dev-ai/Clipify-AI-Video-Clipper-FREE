"""Official YouTube OAuth, secure token storage, and scheduled uploads."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit


YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://youtube.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
TOKEN_SERVICE = "Clipify AI YouTube"
TOKEN_USERNAME = "youtube-oauth"
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")


class YouTubePublisherError(RuntimeError):
    """A user-actionable YouTube publishing error."""


class KeyringTokenStore:
    """Store OAuth tokens only in a native OS credential vault."""

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise YouTubePublisherError(
                "Secure credential storage is unavailable. Install the Clipify AI runtime dependencies and restart."
            ) from exc

        backend = keyring.get_keyring()
        module = type(backend).__module__
        secure_backends = (
            "keyring.backends.Windows",
            "keyring.backends.macOS",
            "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        )
        if not any(module.startswith(prefix) for prefix in secure_backends):
            raise YouTubePublisherError(
                "No supported OS credential vault is available. Configure Windows Credential Manager, "
                "macOS Keychain, or a Linux Secret Service/KWallet backend."
            )
        self._keyring = keyring

    def get(self) -> str | None:
        try:
            return self._keyring.get_password(TOKEN_SERVICE, TOKEN_USERNAME)
        except Exception as exc:
            raise YouTubePublisherError("Could not access the OS credential vault.") from exc

    def set(self, value: str) -> None:
        try:
            self._keyring.set_password(TOKEN_SERVICE, TOKEN_USERNAME, value)
        except Exception as exc:
            raise YouTubePublisherError("Could not save YouTube authorization in the OS credential vault.") from exc

    def delete(self) -> None:
        try:
            self._keyring.delete_password(TOKEN_SERVICE, TOKEN_USERNAME)
        except self._keyring.errors.PasswordDeleteError:
            pass
        except Exception as exc:
            raise YouTubePublisherError("Could not remove YouTube authorization from the OS credential vault.") from exc


class YouTubePublisher:
    def __init__(
        self,
        port: int,
        *,
        environ: dict[str, str] | None = None,
        token_store: Any | None = None,
        urlopen: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.port = int(port)
        self.environ = environ if environ is not None else os.environ
        self._token_store = token_store
        self._urlopen = urlopen or urllib.request.urlopen
        self._clock = clock
        self._pending: dict[str, dict[str, Any]] = {}
        self._callback_servers: dict[str, http.server.ThreadingHTTPServer] = {}
        self._lock = threading.Lock()

    def _client_id(self) -> str:
        client_id = self.environ.get("YOUTUBE_CLIENT_ID", "").strip()
        if not client_id:
            raise YouTubePublisherError(
                "YouTube is not configured. Add your Google OAuth Desktop app client ID to the local .env file, then restart Clipify AI."
            )
        return client_id

    def _store(self) -> Any:
        if self._token_store is None:
            self._token_store = KeyringTokenStore()
        return self._token_store

    def _read_tokens(self) -> dict[str, Any] | None:
        value = self._store().get()
        if not value:
            return None
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise YouTubePublisherError("Saved YouTube authorization data is invalid. Disconnect and connect again.") from exc
        if not isinstance(data, dict):
            raise YouTubePublisherError("Saved YouTube authorization data is invalid. Disconnect and connect again.")
        return data

    def _write_tokens(self, tokens: dict[str, Any]) -> None:
        self._store().set(json.dumps(tokens, separators=(",", ":")))

    @staticmethod
    def _json_request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
                      method: str | None = None, urlopen: Callable[..., Any], timeout: int = 30) -> dict[str, Any]:
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                payload = json.loads(body.decode("utf-8"))
                message = payload.get("error", {}).get("message") or payload.get("error_description") or str(exc)
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                message = str(exc)
            raise YouTubePublisherError(f"YouTube request failed: {message}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise YouTubePublisherError(f"Could not reach YouTube: {exc}") from exc
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise YouTubePublisherError("YouTube returned an invalid response.") from exc
        if not isinstance(result, dict):
            raise YouTubePublisherError("YouTube returned an invalid response.")
        return result

    def start_authorization(self) -> str:
        client_id = self._client_id()
        self._store()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        now = self._clock()
        publisher = self

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed_path = urlsplit(self.path)
                if parsed_path.path != "/":
                    self.send_error(404)
                    return
                query = parse_qs(parsed_path.query)
                state_value = query.get("state", [""])[0]
                error = query.get("error", [""])[0]
                if error:
                    publisher.cancel_authorization(state_value)
                    result_query = "youtube_error=authorization_denied"
                else:
                    try:
                        publisher.complete_authorization(query.get("code", [""])[0], state_value)
                        result_query = "youtube_connected=1"
                    except YouTubePublisherError as exc:
                        error_code = "multiple_channels" if "multiple YouTube channels" in str(exc) else "authorization_failed"
                        result_query = f"youtube_error={error_code}"
                    except Exception:
                        result_query = "youtube_error=authorization_failed"
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{publisher.port}/?{result_query}")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        server.daemon_threads = True
        redirect_uri = f"http://127.0.0.1:{server.server_port}"
        expired_servers = []
        with self._lock:
            for key, value in list(self._pending.items()):
                if now - value["created_at"] >= 600:
                    self._pending.pop(key, None)
                    expired = self._callback_servers.pop(key, None)
                    if expired is not None:
                        expired_servers.append(expired)
            self._pending[state] = {
                "verifier": verifier,
                "created_at": now,
                "redirect_uri": redirect_uri,
            }
            self._callback_servers[state] = server
        for expired in expired_servers:
            threading.Thread(target=expired.shutdown, daemon=True).start()

        def serve_callback():
            try:
                server.serve_forever(poll_interval=0.25)
            finally:
                server.server_close()

        threading.Thread(target=serve_callback, daemon=True).start()
        expiry = threading.Timer(600, server.shutdown)
        expiry.daemon = True
        expiry.start()
        query = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": YOUTUBE_SCOPE,
            "access_type": "offline",
            "prompt": "select_account consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{AUTHORIZE_URL}?{query}"

    def complete_authorization(self, code: str, state: str) -> dict[str, str]:
        if not code or not state:
            raise YouTubePublisherError("YouTube authorization was incomplete. Please connect again.")
        now = self._clock()
        with self._lock:
            pending = self._pending.pop(state, None)
            server = self._callback_servers.pop(state, None)
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()
        if pending is None or now - pending["created_at"] >= 600:
            raise YouTubePublisherError("YouTube authorization expired or could not be verified. Please connect again.")

        token_result = self._json_request(
            TOKEN_URL,
            data=urllib.parse.urlencode({
                "code": code,
                "client_id": self._client_id(),
                "redirect_uri": pending["redirect_uri"],
                "grant_type": "authorization_code",
                "code_verifier": pending["verifier"],
            }).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
            urlopen=self._urlopen,
        )
        access_token = token_result.get("access_token")
        if not access_token:
            raise YouTubePublisherError("Google did not return an access token. Please connect again.")

        channel = self._get_channel(access_token)
        previous = self._read_tokens()
        refresh_token = token_result.get("refresh_token") or (previous or {}).get("refresh_token")
        if not refresh_token:
            raise YouTubePublisherError("Google did not issue a refresh token. Disconnect the app in Google Account permissions, then connect again.")
        self._write_tokens({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": now + int(token_result.get("expires_in", 3600)),
            "channel_id": channel["id"],
            "channel_title": channel["title"],
        })
        return {"channel_id": channel["id"], "channel_title": channel["title"]}

    def confirm_channel(self, channel_id: str) -> None:
        tokens = self._read_tokens()
        if not tokens or not tokens.get("refresh_token"):
            raise YouTubePublisherError("Connect a YouTube channel before confirming it.")
        if not channel_id or channel_id != tokens.get("channel_id"):
            raise YouTubePublisherError("The channel identifier does not match the account authorized with Google.")
        tokens["confirmed_channel_id"] = channel_id
        tokens["channel_confirmed_at"] = int(self._clock())
        self._write_tokens(tokens)

    def _get_channel(self, access_token: str) -> dict[str, str]:
        payload = self._json_request(
            CHANNELS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            urlopen=self._urlopen,
        )
        items = payload.get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise YouTubePublisherError("No YouTube channel was found for this Google account.")
        if len(items) != 1:
            raise YouTubePublisherError(
                "Google returned multiple YouTube channels for this account, so Clipify AI will not choose one automatically. Authorize the specific channel's Google account and try again."
            )
        item = items[0]
        if not item.get("id"):
            raise YouTubePublisherError("Google did not identify the authorized YouTube channel.")
        title = item.get("snippet", {}).get("title", "YouTube channel")
        return {"id": str(item.get("id", "")), "title": str(title)}

    def status(self) -> dict[str, Any]:
        try:
            client_id = self._client_id()
            tokens = self._read_tokens()
            return {
                "configured": True,
                "connected": bool(tokens and tokens.get("refresh_token")),
                "confirmed": bool(tokens and tokens.get("channel_id") and tokens.get("confirmed_channel_id") == tokens.get("channel_id")),
                "channel_title": (tokens or {}).get("channel_title", ""),
                "channel_id": (tokens or {}).get("channel_id", ""),
                "client_id_configured": bool(client_id),
            }
        except YouTubePublisherError as exc:
            return {
                "configured": False,
                "connected": False,
                "confirmed": False,
                "channel_title": "",
                "channel_id": "",
                "error": str(exc),
            }

    def disconnect(self) -> None:
        with self._lock:
            servers = list(self._callback_servers.values())
            self._callback_servers.clear()
            self._pending.clear()
        for server in servers:
            threading.Thread(target=server.shutdown, daemon=True).start()
        self._store().delete()

    def cancel_authorization(self, state: str) -> None:
        with self._lock:
            self._pending.pop(state, None)
            server = self._callback_servers.pop(state, None)
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    def _access_token(self, expected_channel_id: str) -> str:
        tokens = self._read_tokens()
        if not tokens or not tokens.get("refresh_token"):
            raise YouTubePublisherError("Connect your YouTube channel before scheduling clips.")
        if not expected_channel_id or tokens.get("channel_id") != expected_channel_id:
            raise YouTubePublisherError("The connected YouTube channel changed. Reconfirm the intended channel before uploading.")
        if not tokens.get("channel_id") or tokens.get("confirmed_channel_id") != tokens.get("channel_id"):
            raise YouTubePublisherError("Confirm the exact YouTube channel in Clipify AI before uploading or scheduling.")
        if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > self._clock() + 60:
            access_token = str(tokens["access_token"])
        else:
            refreshed = self._json_request(
                TOKEN_URL,
                data=urllib.parse.urlencode({
                    "client_id": self._client_id(),
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                }).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
                urlopen=self._urlopen,
            )
            if not refreshed.get("access_token"):
                raise YouTubePublisherError("YouTube authorization expired. Disconnect and connect your channel again.")
            access_token = str(refreshed["access_token"])
            tokens["access_token"] = access_token
            tokens["expires_at"] = self._clock() + int(refreshed.get("expires_in", 3600))
            self._write_tokens(tokens)
        channel = self._get_channel(access_token)
        if channel["id"] != expected_channel_id:
            raise YouTubePublisherError("Google now identifies a different YouTube channel. Disconnect and reconnect the intended channel.")
        return access_token

    def upload_scheduled(
        self,
        video_path: Path,
        *,
        title: str,
        description: str,
        publish_at: str,
        expected_channel_id: str,
    ) -> dict[str, str]:
        return self._upload_video(
            video_path,
            title=title,
            description=description,
            publish_at=publish_at,
            privacy="private",
            expected_channel_id=expected_channel_id,
        )

    def upload_now(
        self,
        video_path: Path,
        *,
        title: str,
        description: str,
        privacy: str = "unlisted",
        tags: list[str] | None = None,
        expected_channel_id: str,
    ) -> dict[str, str]:
        if privacy not in {"public", "unlisted", "private"}:
            raise YouTubePublisherError("Choose a valid YouTube privacy setting.")
        return self._upload_video(
            video_path,
            title=title,
            description=description,
            publish_at=None,
            privacy=privacy,
            tags=tags,
            expected_channel_id=expected_channel_id,
        )

    def _upload_video(
        self,
        video_path: Path,
        *,
        title: str,
        description: str,
        publish_at: str | None,
        privacy: str,
        tags: list[str] | None = None,
        expected_channel_id: str,
    ) -> dict[str, str]:
        video_path = Path(video_path)
        if not video_path.is_file():
            raise YouTubePublisherError(f"Generated clip is missing: {video_path.name}")
        if not title.strip() or len(title) > 100:
            raise YouTubePublisherError("YouTube titles must contain 1–100 characters.")
        if publish_at is not None:
            try:
                from datetime import datetime
                publish_timestamp = datetime.fromisoformat(publish_at)
                if publish_timestamp.tzinfo is None or publish_timestamp.timestamp() < self._clock() + 900:
                    raise YouTubePublisherError("Scheduled publication must be at least 15 minutes in the future.")
            except ValueError as exc:
                raise YouTubePublisherError("The scheduled publication time is invalid.") from exc

        token = self._access_token(expected_channel_id)
        status: dict[str, Any] = {
            "privacyStatus": "private" if publish_at is not None else privacy,
            "selfDeclaredMadeForKids": False,
        }
        if publish_at is not None:
            status["publishAt"] = publish_at
        metadata = {
            "snippet": {
                "title": title.strip(),
                "description": description.strip(),
                "tags": tags or ["Shorts", "ClipifyAI"],
                "categoryId": "22",
            },
            "status": status,
        }
        init_request = urllib.request.Request(
            UPLOAD_URL,
            data=json.dumps(metadata).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(video_path.stat().st_size),
            },
            method="POST",
        )
        try:
            with self._urlopen(init_request, timeout=30) as response:
                upload_url = response.headers.get("Location")
            upload_uri = urllib.parse.urlsplit(upload_url or "")
            if (upload_uri.scheme != "https"
                    or upload_uri.hostname not in {"www.googleapis.com", "youtube.googleapis.com"}
                    or upload_uri.username or upload_uri.password):
                raise YouTubePublisherError("YouTube did not provide a secure resumable upload URL.")
            with video_path.open("rb") as stream:
                upload_request = urllib.request.Request(
                    upload_url,
                    data=stream,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(video_path.stat().st_size),
                    },
                    method="PUT",
                )
                with self._urlopen(upload_request, timeout=1800) as response:
                    result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                message = json.loads(body.decode("utf-8")).get("error", {}).get("message", str(exc))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                message = str(exc)
            raise YouTubePublisherError(f"YouTube upload failed: {message}") from exc
        except YouTubePublisherError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise YouTubePublisherError(f"YouTube upload failed: {exc}") from exc

        video_id = result.get("id") if isinstance(result, dict) else None
        if not video_id:
            raise YouTubePublisherError("YouTube completed the upload but returned no video ID.")
        return {"video_id": str(video_id), "url": f"https://www.youtube.com/shorts/{video_id}"}


def build_schedule(
    clips: list[dict[str, Any]],
    *,
    now: Any,
    clips_per_day: int = 7,
    start_hour: int = 9,
    end_hour: int = 21,
) -> list[dict[str, Any]]:
    """Create evenly spaced publication times in Asia/Kolkata, starting tomorrow."""
    from datetime import date, datetime, time as datetime_time

    if not 1 <= clips_per_day <= 13:
        raise ValueError("Clips per day must be between 1 and 13.")
    if not 9 <= start_hour < end_hour <= 21:
        raise ValueError("The schedule window must be between 9:00 AM and 9:00 PM.")
    current = now.astimezone(INDIA_TIMEZONE) if now.tzinfo else now.replace(tzinfo=INDIA_TIMEZONE)
    first_date: date = current.date() + timedelta(days=1)
    output: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        day_index, slot_index = divmod(index, clips_per_day)
        if clips_per_day == 1:
            hour = start_hour
        else:
            hour = round(start_hour + slot_index * (end_hour - start_hour) / (clips_per_day - 1))
        scheduled = datetime.combine(
            first_date + timedelta(days=day_index),
            datetime_time(hour=hour),
            tzinfo=INDIA_TIMEZONE,
        )
        output.append({
            **clip,
            "publish_at": scheduled.isoformat(timespec="seconds"),
        })
    return output


def discover_generated_clips(
    jobs_dir: Path,
    *,
    media_probe: Callable[[Path], tuple[float, int | None, int | None] | None],
) -> list[dict[str, Any]]:
    """Find unique generated 30–50 second MP4s and report their video geometry."""
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.is_dir():
        return []
    clips: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for job_dir in sorted(jobs_dir.iterdir(), key=lambda path: (path.stat().st_mtime, path.name) if path.exists() else (0, path.name)):
        output_dir = job_dir / "output"
        if not job_dir.is_dir() or not output_dir.is_dir():
            continue
        try:
            if output_dir.resolve().parent != job_dir.resolve():
                continue
        except OSError:
            continue
        for video_path in sorted(output_dir.rglob("*.mp4"), key=lambda path: path.as_posix().casefold()):
            try:
                if not video_path.is_file() or video_path.stat().st_size < 1024:
                    continue
                relative_path = video_path.resolve().relative_to(output_dir.resolve())
                media_info = media_probe(video_path)
                if media_info is None:
                    continue
                duration, width, height = media_info
                if duration is None or not 30 <= duration <= 50:
                    continue
                if width is not None and width <= 0:
                    width = None
                if height is not None and height <= 0:
                    height = None
                orientation = (
                    "portrait" if width is not None and height is not None and height > width
                    else "landscape" if width is not None and height is not None and width > height
                    else "square" if width is not None and height is not None
                    else "unknown"
                )
                aspect_ratio = round(width / height, 3) if width is not None and height is not None else None
                geometry = {"width": width, "height": height}
                short_compatible = is_short_compatible_clip(geometry)
                format_label = (
                    "9:16 vertical output"
                    if short_compatible
                    else "landscape source (not a Short)"
                    if orientation == "landscape"
                    else "not 9:16 / dimensions unknown"
                )
                digest = hashlib.sha256()
                with video_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                clip_id = digest.hexdigest()
                if clip_id in seen_hashes:
                    continue
                seen_hashes.add(clip_id)
                metadata: dict[str, Any] = {}
                metadata_path = video_path.with_suffix(".json")
                if metadata_path.is_file():
                    try:
                        value = json.loads(metadata_path.read_text(encoding="utf-8"))
                        if isinstance(value, dict):
                            metadata = value
                    except (OSError, json.JSONDecodeError):
                        pass
                clips.append({
                    "clip_id": clip_id,
                    "job_id": job_dir.name,
                    "filename": relative_path.as_posix(),
                    "title": str(metadata.get("title") or video_path.stem.replace("_", " ")),
                    "description": str(metadata.get("description") or "#ClipifyAI"),
                    "duration": round(float(duration), 2),
                    "width": width,
                    "height": height,
                    "orientation": orientation,
                    "aspect_ratio": aspect_ratio,
                    "format_label": format_label,
                    "short_compatible": short_compatible,
                    "size": video_path.stat().st_size,
                })
            except (OSError, ValueError):
                continue
    return clips


def is_short_compatible_clip(clip: dict[str, Any]) -> bool:
    """Return whether a clip is approximately 9:16, the selected Shorts output format."""
    try:
        width = int(clip["width"])
        height = int(clip["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return width > 0 and height > 0 and abs(width / height - 9 / 16) <= 0.02


def select_trial_clips(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only the first three verified 9:16 clips for a trial batch."""
    return [clip for clip in clips if is_short_compatible_clip(clip)][:3]
