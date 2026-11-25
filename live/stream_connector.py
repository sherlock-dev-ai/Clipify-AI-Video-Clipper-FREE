"""Live stream ingestion connector for Clipify AI Live Studio.

Supports YouTube Live, TikTok Live, and OBS Studio local RTMP ingestion.
Continuous capture writes bounded video/audio segments into the rolling buffer.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("clipify.live.connector")

# Common regex patterns for live sources
YOUTUBE_LIVE_REGEX = re.compile(
    r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|live/|@[\w.-]+/live|c/[\w.-]+/live)|youtu\.be/)([\w-]{6,12})",
    re.IGNORECASE,
)
TIKTOK_LIVE_REGEX = re.compile(
    r"^(https?://)?(www\.)?tiktok\.com/@([\w.-]+)(/live)?",
    re.IGNORECASE,
)
TWITCH_LIVE_REGEX = re.compile(
    r"^(https?://)?(www\.)?twitch\.tv/([\w.-]+)",
    re.IGNORECASE,
)
KICK_LIVE_REGEX = re.compile(
    r"^(https?://)?(www\.)?kick\.com/([\w.-]+)",
    re.IGNORECASE,
)


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def extract_preview_frame(chunk_path: Path, output_image: Path, ffmpeg_bin: str) -> bool:
    """Extract a fast JPEG poster frame from a video segment."""
    try:
        cmd = [
            ffmpeg_bin,
            "-ss", "00:00:01",
            "-i", str(chunk_path),
            "-vframes", "1",
            "-q:v", "3",
            "-y",
            str(output_image),
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=5, creationflags=_hidden_flags())
        return res.returncode == 0 and output_image.exists() and output_image.stat().st_size > 0
    except Exception as e:
        logger.debug("Failed extracting preview frame from %s: %s", chunk_path.name, e)
        return False


class StreamConnector:
    """Manages the ingestion subprocess and stream health."""

    def __init__(
        self,
        source_type: str,
        source_url: str,
        buffer_dir: Path,
        ffmpeg_bin: str,
        python_bin: Optional[str] = None,
        segment_duration: int = 5,
        on_segment_ready: Optional[Callable[[Path, int, float], None]] = None,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.source_type = source_type.lower().strip()
        self.source_url = source_url.strip()
        self.buffer_dir = Path(buffer_dir)
        self.ffmpeg_bin = ffmpeg_bin
        self.python_bin = python_bin or "python"
        self.segment_duration = max(3, min(15, segment_duration))
        self.on_segment_ready = on_segment_ready
        self.on_status_change = on_status_change
        self.on_error = on_error

        self.is_running = False
        self.process: Optional[subprocess.Popen] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None
        self.stream_metadata: dict[str, Any] = {
            "title": "Live Stream",
            "author": "",
            "resolution": "1080p",
            "fps": 30,
            "is_live": True,
            "source_type": self.source_type,
        }
        self.connected_at: Optional[float] = None
        self.segments_recorded = 0
        self.last_error: Optional[str] = None
        self.status: str = "idle"
        self.status_detail: str = "Ready"
        self._stop_event = threading.Event()

    def validate(self) -> tuple[bool, str]:
        """Validate input parameters for the chosen source."""
        if self.source_type == "youtube":
            if not self.source_url:
                return False, "Please enter a valid YouTube Live URL."
            if not YOUTUBE_LIVE_REGEX.search(self.source_url):
                if "youtube.com" not in self.source_url:
                    return False, "Not a recognized YouTube live stream link."
            return True, ""
        elif self.source_type == "twitch":
            if not self.source_url:
                return False, "Please enter a Twitch live URL or channel name."
            return True, ""
        elif self.source_type == "kick":
            if not self.source_url:
                return False, "Please enter a Kick live URL or channel name."
            return True, ""
        elif self.source_type == "tiktok":
            if not self.source_url:
                return False, "Please enter a TikTok live URL or username."
            return True, ""
        elif self.source_type == "obs":
            return True, ""
        return False, f"Unsupported source type: {self.source_type}"

    def _notify_status(self, status: str, detail: str) -> None:
        self.status = status
        self.status_detail = detail
        if self.on_status_change:
            try:
                self.on_status_change(status, detail)
            except Exception as e:
                logger.debug("on_status_change callback failed: %s", e)

    def probe_metadata(self) -> dict[str, Any]:
        """Probe stream details prior to capture."""
        if self.source_type == "youtube":
            try:
                cmd = [
                    self.python_bin, "-m", "yt_dlp",
                    "--dump-json", "--no-warnings", "--no-playlist",
                    "--extractor-args", "youtube:player_client=android,web",
                    "--socket-timeout", "10",
                    self.source_url,
                ]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=15, creationflags=_hidden_flags(),
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout.strip().splitlines()[0])
                    self.stream_metadata["title"] = data.get("title", "YouTube Live Stream")
                    self.stream_metadata["author"] = data.get("uploader", "")
                    self.stream_metadata["is_live"] = bool(data.get("is_live", True))
                    if data.get("width") and data.get("height"):
                        self.stream_metadata["resolution"] = f"{data['width']}x{data['height']}"
                    if data.get("fps"):
                        self.stream_metadata["fps"] = data["fps"]
            except Exception as e:
                logger.warning("yt-dlp probe failed or timed out: %s", e)
                self.stream_metadata["title"] = "YouTube Live Stream"

        elif self.source_type == "twitch":
            clean_url = self.source_url.strip()
            if not clean_url.startswith("http"):
                clean_url = f"https://www.twitch.tv/{clean_url.lstrip('@')}"
            try:
                cmd = [
                    self.python_bin, "-m", "yt_dlp",
                    "--dump-json", "--no-warnings", "--no-playlist",
                    "--socket-timeout", "10",
                    clean_url,
                ]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=15, creationflags=_hidden_flags(),
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout.strip().splitlines()[0])
                    self.stream_metadata["title"] = data.get("title", f"Twitch Live: {data.get('uploader', clean_url)}")
                    self.stream_metadata["author"] = data.get("uploader", "")
                    self.stream_metadata["is_live"] = bool(data.get("is_live", True))
                    if data.get("width") and data.get("height"):
                        self.stream_metadata["resolution"] = f"{data['width']}x{data['height']}"
                    if data.get("fps"):
                        self.stream_metadata["fps"] = data["fps"]
                else:
                    channel_name = clean_url.rstrip("/").split("/")[-1]
                    self.stream_metadata["title"] = f"Twitch Live: {channel_name}"
                    self.stream_metadata["author"] = channel_name
            except Exception as e:
                logger.warning("Twitch metadata probe failed: %s", e)
                channel_name = clean_url.rstrip("/").split("/")[-1]
                self.stream_metadata["title"] = f"Twitch Live: {channel_name}"
                self.stream_metadata["author"] = channel_name

        elif self.source_type == "kick":
            clean_url = self.source_url.strip()
            if not clean_url.startswith("http"):
                clean_url = f"https://kick.com/{clean_url.lstrip('@')}"
            try:
                cmd = [
                    self.python_bin, "-m", "yt_dlp",
                    "--dump-json", "--no-warnings", "--no-playlist",
                    "--socket-timeout", "10",
                    clean_url,
                ]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=15, creationflags=_hidden_flags(),
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout.strip().splitlines()[0])
                    self.stream_metadata["title"] = data.get("title", f"Kick Live: {data.get('uploader', clean_url)}")
                    self.stream_metadata["author"] = data.get("uploader", "")
                    self.stream_metadata["is_live"] = bool(data.get("is_live", True))
                    if data.get("width") and data.get("height"):
                        self.stream_metadata["resolution"] = f"{data['width']}x{data['height']}"
                    if data.get("fps"):
                        self.stream_metadata["fps"] = data["fps"]
                else:
                    channel_name = clean_url.rstrip("/").split("/")[-1]
                    self.stream_metadata["title"] = f"Kick Live: {channel_name}"
                    self.stream_metadata["author"] = channel_name
            except Exception as e:
                logger.warning("Kick metadata probe failed: %s", e)
                channel_name = clean_url.rstrip("/").split("/")[-1]
                self.stream_metadata["title"] = f"Kick Live: {channel_name}"
                self.stream_metadata["author"] = channel_name

        elif self.source_type == "obs":
            self.stream_metadata["title"] = "OBS Studio Ingestion"
            self.stream_metadata["author"] = "Local Broadcast"
            self.stream_metadata["resolution"] = "1920x1080"
            self.stream_metadata["fps"] = 60

        elif self.source_type == "tiktok":
            self.stream_metadata["title"] = f"TikTok Live: {self.source_url}"
            self.stream_metadata["author"] = self.source_url

        return self.stream_metadata

    def _resolve_youtube_stream(self) -> tuple[bool, list[str], str]:
        """Resolve YouTube Live stream manifests using yt-dlp with anti-bot arguments."""
        self._notify_status("resolving", "Resolving YouTube Live stream feed...")
        try:
            cmd = [
                self.python_bin, "-m", "yt_dlp",
                "-g", "--no-warnings", "--no-playlist",
                "--extractor-args", "youtube:player_client=android,web",
                "-f", "bv*+ba/best/b",
                "--format-sort", "res:2160,res:1440,res:1080,fps:60,vbr",
                "--socket-timeout", "15",
                self.source_url,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=45,
                creationflags=_hidden_flags(),
            )
            if proc.returncode != 0:
                # Fallback to general best format
                logger.info("Retrying YouTube stream resolution with fallback format...")
                cmd_fallback = [
                    self.python_bin, "-m", "yt_dlp",
                    "-g", "--no-warnings", "--no-playlist",
                    "--extractor-args", "youtube:player_client=android,web",
                    "-f", "best/b/bv*+ba",
                    "--socket-timeout", "15",
                    self.source_url,
                ]
                proc = subprocess.run(
                    cmd_fallback, capture_output=True, text=True, timeout=30,
                    creationflags=_hidden_flags(),
                )

            if proc.returncode != 0:
                err = proc.stderr.strip()
                logger.warning("yt-dlp stream resolution failed: %s", err)
                clean_err = "Live stream is offline or link is invalid."
                if "This live event will begin in" in err:
                    clean_err = "This live stream has not started yet (scheduled event)."
                elif "Private video" in err:
                    clean_err = "This live stream is private."
                elif "recording is not available" in err or "not available" in err:
                    clean_err = "This live stream has ended or is unavailable."
                elif "Sign in to confirm you’re not a bot" in err:
                    clean_err = "YouTube bot check triggered. Please try again or use another stream."
                elif err:
                    first_err_line = [l for l in err.splitlines() if "ERROR:" in l]
                    if first_err_line:
                        clean_err = first_err_line[0].replace("ERROR: [youtube]", "").strip()
                return False, [], clean_err

            lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip().startswith("http")]
            if not lines:
                return False, [], "No playable stream URL returned by yt-dlp."

            logger.info("yt-dlp resolved %d stream manifest URL(s)", len(lines))
            return True, lines, ""
        except subprocess.TimeoutExpired:
            return False, [], "Stream resolution timed out (45s). Please verify link or try again."
        except Exception as e:
            logger.exception("Error resolving YouTube stream: %s", e)
            return False, [], str(e)

    def _resolve_twitch_stream(self) -> tuple[bool, list[str], str]:
        """Resolve Twitch Live stream manifests using yt-dlp."""
        self._notify_status("resolving", "Resolving Twitch Live stream feed...")
        clean_url = self.source_url.strip()
        if not clean_url.startswith("http"):
            clean_url = f"https://www.twitch.tv/{clean_url.lstrip('@')}"
        try:
            cmd = [
                self.python_bin, "-m", "yt_dlp",
                "-g", "--no-warnings", "--no-playlist",
                "-f", "best",
                "--format-sort", "res:2160,res:1440,res:1080,fps:60,vbr",
                "--socket-timeout", "15",
                clean_url,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=25,
                creationflags=_hidden_flags(),
            )
            if proc.returncode != 0:
                err = proc.stderr.strip()
                logger.warning("yt-dlp Twitch stream resolution failed: %s", err)
                clean_err = "Twitch channel is offline or link is invalid."
                if "does not exist" in err or "404" in err:
                    clean_err = "Twitch channel does not exist."
                elif "is offline" in err or "offline" in err:
                    clean_err = "This Twitch stream is currently offline."
                elif err:
                    first_err_line = [l for l in err.splitlines() if "ERROR:" in l]
                    if first_err_line:
                        clean_err = first_err_line[0].replace("ERROR: [twitch:stream]", "").strip()
                return False, [], clean_err

            lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip().startswith("http")]
            if not lines:
                return False, [], "No playable stream URL returned for Twitch stream."

            logger.info("yt-dlp resolved Twitch stream manifest URL: %s", lines[0][:80])
            return True, lines, ""
        except subprocess.TimeoutExpired:
            return False, [], "Twitch stream resolution timed out (25s)."
        except Exception as e:
            logger.exception("Error resolving Twitch stream: %s", e)
            return False, [], str(e)

    def _resolve_kick_stream(self) -> tuple[bool, list[str], str]:
        """Resolve Kick Live stream manifests using yt-dlp."""
        self._notify_status("resolving", "Resolving Kick Live stream feed...")
        clean_url = self.source_url.strip()
        if not clean_url.startswith("http"):
            clean_url = f"https://kick.com/{clean_url.lstrip('@')}"
        try:
            cmd = [
                self.python_bin, "-m", "yt_dlp",
                "-g", "--no-warnings", "--no-playlist",
                "-f", "best",
                "--format-sort", "res:2160,res:1440,res:1080,fps:60,vbr",
                "--socket-timeout", "15",
                clean_url,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=25,
                creationflags=_hidden_flags(),
            )
            if proc.returncode != 0:
                err = proc.stderr.strip()
                logger.warning("yt-dlp Kick stream resolution failed: %s", err)
                clean_err = "Kick channel is offline or link is invalid."
                if "does not exist" in err or "404" in err:
                    clean_err = "Kick channel does not exist."
                elif "is offline" in err or "offline" in err:
                    clean_err = "This Kick stream is currently offline."
                elif err:
                    first_err_line = [l for l in err.splitlines() if "ERROR:" in l]
                    if first_err_line:
                        clean_err = first_err_line[0].replace("ERROR: [kick]", "").strip()
                return False, [], clean_err

            lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip().startswith("http")]
            if not lines:
                return False, [], "No playable stream URL returned for Kick stream."

            logger.info("yt-dlp resolved Kick stream manifest URL: %s", lines[0][:80])
            return True, lines, ""
        except subprocess.TimeoutExpired:
            return False, [], "Kick stream resolution timed out (25s)."
        except Exception as e:
            logger.exception("Error resolving Kick stream: %s", e)
            return False, [], str(e)

    def _resolve_tiktok_stream(self) -> tuple[bool, list[str], str]:
        """Resolve TikTok Live stream manifests or suggest OBS fallback."""
        self._notify_status("resolving", "Resolving TikTok Live stream feed...")
        try:
            cmd = [
                self.python_bin, "-m", "yt_dlp",
                "-g", "--no-warnings", "--no-playlist",
                "--socket-timeout", "10",
                self.source_url,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                creationflags=_hidden_flags(),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip().startswith("http")]
                if lines:
                    return True, lines, ""

            return False, [], (
                "TikTok Live direct extraction is restricted by platform security. "
                "Please use OBS Studio: capture TikTok in OBS and stream directly to Clipify AI via RTMP."
            )
        except Exception as e:
            return False, [], f"TikTok resolution failed: {e}. Please use the OBS Studio option."

    def _build_ffmpeg_cmd(self, stream_urls: list[str]) -> list[str]:
        """Construct the FFmpeg command for the configured source."""
        out_pattern = str(self.buffer_dir / "chunk_%05d.mp4")

        # High-performance encoding for rolling buffer segments (max quality, high bitrate)
        common_output = [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
            "-b:v", "16M", "-maxrate", "24M", "-bufsize", "32M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "16000",
            "-f", "segment",
            "-segment_time", str(self.segment_duration),
            "-segment_format", "mp4",
            "-reset_timestamps", "1",
            "-movflags", "+faststart+frag_keyframe+empty_moov",
            "-y", out_pattern,
        ]

        if self.source_type == "obs":
            rtmp_url = self.source_url if self.source_url.startswith("rtmp://") else "rtmp://0.0.0.0:1935/live/stream"
            return [
                self.ffmpeg_bin,
                "-listen", "1",
                "-i", rtmp_url,
                *common_output,
            ]

        # Note: We intentionally avoid -reconnect_at_eof 1 as it breaks HLS playlist parsing
        if len(stream_urls) >= 2:
            # Dual manifests: stream_urls[0] = video, stream_urls[1] = audio
            video_url, audio_url = stream_urls[0], stream_urls[1]
            return [
                self.ffmpeg_bin,
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                "-i", video_url,
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                "-i", audio_url,
                "-map", "0:v:0",
                "-map", "1:a:0",
                *common_output,
            ]
        elif len(stream_urls) == 1:
            # Single muxed stream
            return [
                self.ffmpeg_bin,
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                "-i", stream_urls[0],
                *common_output,
            ]
        else:
            return [
                self.ffmpeg_bin,
                "-i", self.source_url,
                *common_output,
            ]

    def start(self) -> None:
        """Start capturing the stream into rolling buffer segments."""
        if self.is_running:
            return

        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self.is_running = True
        self.connected_at = None
        self.segments_recorded = 0
        self.last_error = None

        self._notify_status("connecting", "Initializing live stream capture...")
        self.monitor_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.monitor_thread.start()

    def stop(self) -> None:
        """Gracefully stop stream ingestion."""
        self.is_running = False
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        self._notify_status("disconnected", "Live stream capture stopped.")

    def _capture_loop(self) -> None:
        """Background thread executing capture with precise status transitions."""
        retry_delay = 2
        consecutive_failures = 0

        while not self._stop_event.is_set():
            stream_urls: list[str] = []

            # 1. Resolve source URL
            if self.source_type == "youtube":
                ok, stream_urls, err_msg = self._resolve_youtube_stream()
                if not ok:
                    self.last_error = err_msg
                    self._notify_status("failed", err_msg)
                    if self.on_error:
                        self.on_error(err_msg)
                    break
            elif self.source_type == "twitch":
                ok, stream_urls, err_msg = self._resolve_twitch_stream()
                if not ok:
                    self.last_error = err_msg
                    self._notify_status("failed", err_msg)
                    if self.on_error:
                        self.on_error(err_msg)
                    break
            elif self.source_type == "kick":
                ok, stream_urls, err_msg = self._resolve_kick_stream()
                if not ok:
                    self.last_error = err_msg
                    self._notify_status("failed", err_msg)
                    if self.on_error:
                        self.on_error(err_msg)
                    break
            elif self.source_type == "tiktok":
                ok, stream_urls, err_msg = self._resolve_tiktok_stream()
                if not ok:
                    self.last_error = err_msg
                    self._notify_status("failed", err_msg)
                    if self.on_error:
                        self.on_error(err_msg)
                    break
            elif self.source_type == "obs":
                self._notify_status("listening", "Listening for OBS Studio RTMP on rtmp://127.0.0.1:1935/live...")

            if self._stop_event.is_set():
                break

            # 2. Build FFmpeg command and start capture
            cmd = self._build_ffmpeg_cmd(stream_urls)
            if self.source_type != "obs":
                self._notify_status("connecting", "Starting FFmpeg ingestion pipeline...")

            logger.info("Starting live capture subprocess: %s", " ".join(cmd[:6]))

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    creationflags=_hidden_flags(),
                )
            except Exception as exc:
                err_msg = f"Failed to start FFmpeg: {exc}"
                logger.exception(err_msg)
                self.last_error = err_msg
                self._notify_status("failed", err_msg)
                break

            # Stderr reader thread to prevent pipe deadlocks and capture error logs
            stderr_lines: list[str] = []

            def _drain_stderr() -> None:
                try:
                    if self.process and self.process.stderr:
                        for line in iter(self.process.stderr.readline, ""):
                            if not line:
                                break
                            clean_line = line.strip()
                            if clean_line:
                                stderr_lines.append(clean_line)
                                if len(stderr_lines) > 40:
                                    stderr_lines.pop(0)
                except Exception:
                    pass

            self.stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            self.stderr_thread.start()

            if self.source_type != "obs":
                self._notify_status("buffering", "Receiving media packets, initializing rolling buffer...")

            # 3. Monitor output directory for newly created segments
            known_chunks: set[str] = set()
            is_live_reported = False
            preview_img = self.buffer_dir / "preview_current.jpg"

            while not self._stop_event.is_set():
                poll_res = self.process.poll()
                if poll_res is not None:
                    recent_err = " ".join(stderr_lines[-5:]) if stderr_lines else f"Exited with code {poll_res}"
                    logger.warning("Capture process exited with code %d: %s", poll_res, recent_err)
                    if not is_live_reported:
                        self.last_error = f"Ingestion ended prematurely: {recent_err}"
                        self._notify_status("failed", self.last_error)
                        return
                    break

                # Check for completed chunks
                files = sorted(self.buffer_dir.glob("chunk_*.mp4"))
                if files:
                    # Transition to "live" when first chunk exists and has written data
                    if not is_live_reported:
                        first_chunk = files[0]
                        if first_chunk.stat().st_size > 10240:
                            is_live_reported = True
                            self.connected_at = time.time()
                            self._notify_status("live", f"Connected to {self.source_type.upper()} Live Stream")
                            extract_preview_frame(first_chunk, preview_img, self.ffmpeg_bin)

                    if len(files) >= 2:
                        for chunk in files[:-1]: # All except currently writing last chunk
                            if chunk.name not in known_chunks and chunk.stat().st_size > 1024:
                                known_chunks.add(chunk.name)
                                self.segments_recorded += 1
                                elapsed = (time.time() - self.connected_at) if self.connected_at else 0
                                extract_preview_frame(chunk, preview_img, self.ffmpeg_bin)
                                if self.on_segment_ready:
                                    try:
                                        self.on_segment_ready(chunk, self.segments_recorded, elapsed)
                                    except Exception as exc:
                                        logger.exception("Error in on_segment_ready: %s", exc)

                time.sleep(1.0)

            if self._stop_event.is_set():
                break

            consecutive_failures += 1
            if consecutive_failures >= 3:
                self._notify_status("failed", f"Stream disconnected: {self.last_error or 'Connection lost'}")
                break

            self._notify_status("reconnecting", f"Stream disconnected. Reconnecting in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(15, retry_delay * 1.5)

        self.is_running = False
