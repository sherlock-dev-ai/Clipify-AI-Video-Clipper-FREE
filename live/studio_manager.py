"""Coordinator singleton for Clipify AI Live Studio.

Orchestrates live ingestion, rolling buffers, transcription,
highlight analysis, clip generation, and status telemetry.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

from live.clip_generator import LiveClipGenerator
from live.highlight_detector import HighlightDetector, HighlightCandidate
from live.rolling_buffer import RollingBuffer
from live.stream_connector import StreamConnector
from live.transcriber import LiveTranscriber, LiveTranscriptSegment

logger = logging.getLogger("clipify.live.manager")


class LiveStudioManager:
    """Coordinates active Live Studio session."""

    def __init__(self, data_dir: Path, ffmpeg_bin: str, python_bin: str):
        self.data_dir = Path(data_dir)
        self.ffmpeg_bin = ffmpeg_bin
        self.python_bin = python_bin

        self.live_root = self.data_dir / "live_studio"
        self.buffer_dir = self.live_root / "buffer"
        self.clips_dir = self.live_root / "clips"
        self.live_root.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        self.session_active = False
        self.status = "idle"  # "idle", "connecting", "live", "reconnecting", "disconnected"
        self.status_detail = "Ready to connect to live stream"

        self.source_type = "youtube"
        self.source_url = ""
        self.auto_clip_enabled = False
        self.sensitivity = 5
        self.buffer_minutes = 10
        self.stream_metadata: dict[str, Any] = {}
        self.session_start_time: Optional[float] = None

        self.connector: Optional[StreamConnector] = None
        self.buffer: Optional[RollingBuffer] = None
        self.transcriber: Optional[LiveTranscriber] = None
        self.detector: Optional[HighlightDetector] = None
        self.generator: Optional[LiveClipGenerator] = None

        self.live_events: list[dict[str, Any]] = []
        self.recent_transcripts: list[dict[str, Any]] = []
        self.clips: list[dict[str, Any]] = []
        self.ranked_clips: list[dict[str, Any]] = []
        self.console_logs: list[dict[str, Any]] = []
        self.ranking_logs: list[dict[str, Any]] = []
        self.is_ranking: bool = False
        self.auto_clip_interval: int = 5
        self.auto_clip_target: int = 10
        self.last_auto_clip_time: float = time.time()
        self._auto_clip_thread: Optional[threading.Thread] = None
        self._auto_clip_stop_event = threading.Event()
        self.editing_prefs: dict[str, Any] = {
            "auto_edit": True,
            "auto_captions": True,
            "face_tracking": True,
            "gaming_layout": True,
            "auto_clip_interval": 5,
            "auto_clip_target": 10,
            "caption_style": "highlight",
            "caption_font": "Montserrat Extra Bold",
            "caption_language": "en",
            "background_style": "soft_blur",
            "background_color": "#000000",
            "custom_text": "",
            "custom_text_pos": "top-center",
            "custom_text_color": "#FFFFFF",
        }

        self._lock = threading.RLock()
        self._load_saved_clips()
        self.log_activity("Live Studio manager initialized. System ready.", "system")

    def log_activity(self, message: str, level: str = "info") -> None:
        """Record real-time activity for the Live Studio console."""
        with self._lock:
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "message": message,
                "level": level,
            }
            self.console_logs.append(entry)
            if len(self.console_logs) > 200:
                self.console_logs.pop(0)
            self._emit_event("console_log", entry)

    def get_console_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.console_logs)

    def _load_saved_clips(self) -> None:
        """Load any existing clips from previous sessions on disk."""
        with self._lock:
            self.clips.clear()
            if not self.clips_dir.exists():
                return
            for clip_folder in self.clips_dir.iterdir():
                if clip_folder.is_dir():
                    meta_json = clip_folder / "meta.json"
                    if meta_json.exists():
                        try:
                            data = json.loads(meta_json.read_text(encoding="utf-8"))
                            if not data.get("badges"):
                                data["badges"] = ["✨ Smart Fit", "💬 Auto Captions"]
                            self.clips.append(data)
                        except Exception:
                            pass
            self.clips.sort(key=lambda c: c.get("created_at", 0), reverse=True)

            ranked_file = self.clips_dir / "ranked_clips.json"
            if ranked_file.exists():
                try:
                    self.ranked_clips = json.loads(ranked_file.read_text(encoding="utf-8"))
                except Exception:
                    self.ranked_clips = []

    def get_obs_config(self) -> dict[str, str]:
        """Return OBS Studio connection parameters."""
        return {
            "server": "rtmp://127.0.0.1:1935/live",
            "stream_key": "stream",
            "instructions": "In OBS Studio, open Settings -> Stream -> Service: Custom -> Server: rtmp://127.0.0.1:1935/live -> Stream Key: stream -> Click Start Streaming.",
        }

    def update_editing_prefs(self, prefs: dict[str, Any]) -> dict[str, Any]:
        """Update live Short editing preferences (auto_edit, face_tracking, captions, layout, font, custom text, background, auto_clip_target, auto_clip_interval)."""
        with self._lock:
            for k in ("auto_edit", "auto_captions", "face_tracking", "gaming_layout"):
                if k in prefs:
                    self.editing_prefs[k] = bool(prefs[k])
            for k in (
                "caption_style", "caption_font", "caption_language", "background_style", "background_color",
                "custom_text", "custom_text_pos", "custom_text_color", "ai_provider", "hf_model",
            ):
                if k in prefs:
                    self.editing_prefs[k] = str(prefs[k])
            if self.detector:
                if "ai_provider" in prefs:
                    self.detector.ai_provider = str(prefs["ai_provider"]).strip().lower()
                if "hf_model" in prefs:
                    self.detector.hf_model = str(prefs["hf_model"]).strip()
            if "caption_language" in prefs and self.transcriber:
                self.transcriber.set_language(str(prefs["caption_language"]))
            if "auto_clip_interval" in prefs:
                try:
                    self.auto_clip_interval = max(1, min(60, int(prefs["auto_clip_interval"])))
                    self.editing_prefs["auto_clip_interval"] = self.auto_clip_interval
                except Exception:
                    pass
            if "auto_clip_target" in prefs:
                try:
                    self.auto_clip_target = max(1, min(100, int(prefs["auto_clip_target"])))
                    self.editing_prefs["auto_clip_target"] = self.auto_clip_target
                except Exception:
                    pass
            return dict(self.editing_prefs)

    def start_session(
        self,
        source_type: str,
        source_url: str,
        auto_clip: bool = False,
        sensitivity: int = 5,
        buffer_minutes: int = 10,
        model_name: str = "qwen2.5:3b",
        stream_quality: str = "1080p",
        editing_prefs: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Initialize and start a live studio monitoring session."""
        with self._lock:
            if self.session_active:
                return False, "A live session is already running. Stop it before starting a new one."

            self.source_type = source_type.lower().strip()
            self.source_url = source_url.strip()
            self.auto_clip_enabled = auto_clip
            self.sensitivity = max(1, min(10, sensitivity))
            self.buffer_minutes = max(3, min(30, buffer_minutes))
            if editing_prefs:
                for k in ("auto_edit", "auto_captions", "face_tracking", "gaming_layout"):
                    if k in editing_prefs:
                        self.editing_prefs[k] = bool(editing_prefs[k])
                for k in (
                    "caption_style", "caption_font", "caption_language", "background_style", "background_color",
                    "custom_text", "custom_text_pos", "custom_text_color",
                ):
                    if k in editing_prefs:
                        self.editing_prefs[k] = str(editing_prefs[k])

            # Initialize components
            self.buffer = RollingBuffer(
                buffer_dir=self.buffer_dir,
                ffmpeg_bin=self.ffmpeg_bin,
                max_duration_sec=self.buffer_minutes * 60,
            )
            self.buffer.clear()

            self.generator = LiveClipGenerator(
                ffmpeg_bin=self.ffmpeg_bin,
                rolling_buffer=self.buffer,
                clips_output_dir=self.clips_dir,
            )

            self.detector = HighlightDetector(
                model_name=model_name,
                sensitivity=self.sensitivity,
                ai_provider=str(self.editing_prefs.get("ai_provider", "ollama")),
                hf_model=str(self.editing_prefs.get("hf_model", "Qwen/Qwen2.5-7B-Instruct")),
            )

            self.transcriber = LiveTranscriber(
                python_bin=self.python_bin,
                ffmpeg_bin=self.ffmpeg_bin,
                language=self.editing_prefs.get("caption_language", "en"),
                on_segment=self._on_transcript_segment,
            )
            self.transcriber.start()

            self.connector = StreamConnector(
                source_type=self.source_type,
                source_url=self.source_url,
                buffer_dir=self.buffer_dir,
                ffmpeg_bin=self.ffmpeg_bin,
                python_bin=self.python_bin,
                stream_quality=stream_quality,
                on_segment_ready=self._on_segment_ready,
                on_status_change=self._on_status_change,
                on_error=self._on_connector_error,
            )

            valid, err = self.connector.validate()
            if not valid:
                self.transcriber.stop()
                return False, err

            # Probe initial stream metadata
            threading.Thread(target=self._probe_and_start, daemon=True).start()

            self.session_active = True
            self.session_start_time = time.time()
            self.last_auto_clip_time = 0.0
            self.status = "connecting"
            self.status_detail = f"Connecting to {self.source_type.upper()} live stream..."
            self.recent_transcripts.clear()
            self._auto_clip_stop_event.clear()
            if self._auto_clip_thread is None or not self._auto_clip_thread.is_alive():
                self._auto_clip_thread = threading.Thread(
                    target=self._auto_clip_timer_loop,
                    daemon=True,
                )
                self._auto_clip_thread.start()
            self._emit_event("session_started", {"source_type": self.source_type})

            return True, "Connecting to live stream"

    def _probe_and_start(self) -> None:
        """Background probe and stream launch."""
        if self.connector:
            self.connector.start()
            def _async_probe():
                try:
                    meta = self.connector.probe_metadata()
                    if meta:
                        self.stream_metadata = meta
                except Exception:
                    pass
            threading.Thread(target=_async_probe, daemon=True).start()

    def stop_session(self) -> None:
        """Stop capture and transcription cleanly."""
        with self._lock:
            if not self.session_active:
                return

            self.session_active = False
            self._auto_clip_stop_event.set()
            self.status = "idle"
            self.status_detail = "Live Studio session ended."

            if self.connector:
                self.connector.stop()
                self.connector = None

            if self.transcriber:
                self.transcriber.stop()
                self.transcriber = None

            if self.buffer:
                self.buffer.clear()

            self._emit_event("session_stopped", {})

    def _on_status_change(self, status: str, detail: str) -> None:
        self.status = status
        self.status_detail = detail
        if status in ("failed", "disconnected") and status == "failed":
            self.session_active = False
        self.log_activity(f"Stream status: {status.upper()} — {detail}", "info" if status == "live" else "debug")
        self._emit_event("status_change", {"status": status, "detail": detail})

    def _on_connector_error(self, err_msg: str) -> None:
        self.status = "failed"
        self.status_detail = f"Stream error: {err_msg}"
        self.session_active = False
        self.log_activity(f"Stream connector error: {err_msg}", "error")
        self._emit_event("stream_error", {"error": err_msg})

    def _on_segment_ready(self, chunk_path: Path, index: int, stream_elapsed: float) -> None:
        """Callback when a new 5-second chunk is saved by FFmpeg."""
        if not self.buffer or not self.transcriber:
            return

        chunk = self.buffer.add_chunk(chunk_path, index, stream_elapsed)
        self.log_activity(f"Buffer chunk #{index} captured ({chunk.duration:.1f}s, total buffer: {self.buffer.get_window_duration():.0f}s)", "debug")

        # Update live preview JPEG frame asynchronously for snapshot / fallback mode
        try:
            from live.stream_connector import extract_preview_frame
            preview_out = self.buffer_dir / "preview_current.jpg"
            threading.Thread(
                target=extract_preview_frame,
                args=(chunk_path, preview_out, self.ffmpeg_bin),
                daemon=True,
            ).start()
        except Exception:
            pass

        # Extract WAV audio for transcription
        wav_path = chunk_path.with_suffix(".wav")
        if self.buffer.extract_audio_wav(chunk_path, wav_path):
            self.transcriber.enqueue_chunk(wav_path, chunk.start_sec, chunk.duration)

    def _on_transcript_segment(self, segment: LiveTranscriptSegment) -> None:
        """Callback when speech is transcribed."""
        seg_dict = {
            "start": round(segment.start_sec, 2),
            "end": round(segment.end_sec, 2),
            "text": segment.text,
            "speaker": segment.speaker,
            "words": getattr(segment, "words", []),
        }
        self.recent_transcripts.append(seg_dict)
        if len(self.recent_transcripts) > 100:
            self.recent_transcripts.pop(0)

        self.log_activity(f"Transcribed [{segment.start_sec:.1f}s]: \"{segment.text[:55]}\"", "debug")
        self._emit_event("transcript", seg_dict)

        # Check for highlights if auto-clip is enabled and interval elapsed
        if self.auto_clip_enabled and self.detector and self.generator:
            now = time.time()
            interval_sec = self.auto_clip_interval * 60
            if (now - self.last_auto_clip_time) >= interval_sec:
                recent_segments = self.transcriber.get_recent_transcripts(last_n_seconds=45.0) if self.transcriber else []
                candidate = self.detector.evaluate(recent_segments)
                if candidate:
                    self.last_auto_clip_time = now
                    self.log_activity(f"Auto-clip trigger: highlight \"{candidate.title}\" detected (score: {candidate.score:.1f})", "info")
                    threading.Thread(
                        target=self._trigger_clip_generation,
                        args=(candidate,),
                        daemon=True,
                    ).start()

    def _auto_clip_timer_loop(self) -> None:
        """Autonomous background loop generating clips at strict intervals up to target count."""
        while not self._auto_clip_stop_event.is_set():
            time.sleep(2.0)
            if not self.session_active or not self.auto_clip_enabled or self.status != "live":
                continue
            if not self.buffer or not self.generator:
                continue

            with self._lock:
                current_clips_count = len(self.clips)
                target = self.auto_clip_target
                interval_sec = self.auto_clip_interval * 60
                last_time = self.last_auto_clip_time
                target_dur = float(self.editing_prefs.get("clip_duration", 30))

            if current_clips_count >= target:
                continue

            buf_dur = self.buffer.get_window_duration() if self.buffer else 0.0
            if buf_dur < min(28.0, target_dur):
                continue

            now = time.time()
            is_initial = (current_clips_count == 0 and last_time == 0.0 and buf_dur >= min(28.0, target_dur))
            if not is_initial and (now - last_time) < interval_sec:
                continue

            with self._lock:
                self.last_auto_clip_time = now

            self.log_activity(
                f"[Auto-Clip] Interval trigger ({self.auto_clip_interval}m elapsed). Evaluating highlight for clip #{current_clips_count + 1} of {target}...",
                "info"
            )

            # Evaluate recent transcript if available
            candidate = None
            if self.detector and self.transcriber:
                recent_segments = self.transcriber.get_recent_transcripts(last_n_seconds=45.0)
                if recent_segments:
                    candidate = self.detector.evaluate(recent_segments)

            # If no transcript candidate found (sparse speech or silence), synthesize rolling buffer highlight
            if not candidate:
                current_time = (time.time() - self.session_start_time) if self.session_start_time else 0.0
                clip_dur = target_dur
                start_sec = max(0.0, current_time - clip_dur)
                end_sec = current_time
                candidate = HighlightCandidate(
                    start_sec=start_sec,
                    end_sec=end_sec,
                    category="High-energy moments",
                    title=f"Live Highlight #{current_clips_count + 1}",
                    score=8.5,
                    reason=f"Scheduled periodic highlight from live stream buffer ({self.auto_clip_interval}m interval)",
                    transcript_snippet="Live broadcast moment",
                )

            threading.Thread(
                target=self._trigger_clip_generation,
                args=(candidate,),
                daemon=True,
            ).start()

    def _trigger_clip_generation(self, candidate: HighlightCandidate) -> None:
        """Renders an auto-detected highlight into MP4 clips with user configured duration."""
        if not self.generator:
            return

        with self._lock:
            target_dur = float(self.editing_prefs.get("clip_duration", 30))
            current_time = (time.time() - self.session_start_time) if self.session_start_time else candidate.end_sec
            buf_dur = self.buffer.get_window_duration() if self.buffer else target_dur
            available_start = max(0.0, current_time - buf_dur)

            # Symmetrically center the slice on the highlight candidate
            center = (candidate.start_sec + candidate.end_sec) / 2.0
            half = target_dur / 2.0
            clip_start = center - half
            clip_end = center + half

            if clip_end > current_time:
                clip_end = current_time
                clip_start = clip_end - target_dur
            if clip_start < available_start:
                clip_start = available_start
                clip_end = min(current_time, clip_start + target_dur)

            clip_start = max(0.0, clip_start)
            if clip_end - clip_start < 10.0 and (current_time - available_start) >= 10.0:
                clip_end = min(current_time, clip_start + 10.0)

            transcripts = [
                t for t in self.recent_transcripts
                if t.get("start", 0) <= clip_end and t.get("end", 0) >= clip_start
            ]
            if not transcripts:
                transcripts = list(self.recent_transcripts[-10:])
            prefs = dict(self.editing_prefs)

        self.log_activity(f"Rendering highlight Short: \"{candidate.title}\" ({clip_start:.1f}s - {clip_end:.1f}s, target {target_dur:.0f}s)...", "info")
        self._emit_event("highlight_detected", {
            "title": candidate.title,
            "category": candidate.category,
            "score": candidate.score,
        })

        clip_data = self.generator.render_clip(
            start_sec=clip_start,
            end_sec=clip_end,
            title=candidate.title,
            category=candidate.category,
            subtitle_text=candidate.transcript_snippet,
            transcripts=transcripts,
            editing_prefs=prefs,
            energy_score=candidate.score,
        )

        if clip_data:
            with self._lock:
                self.clips.insert(0, clip_data)
            self.log_activity(f"Clip ready: \"{clip_data['title']}\" ({clip_data['duration']}s, {clip_data.get('layout')})", "success")
            self._emit_event("new_clip", clip_data)

    def instant_clip(self, duration_sec: int = 30) -> Optional[dict[str, Any]]:
        """User manual trigger: capture the last N seconds into a Short."""
        with self._lock:
            self.last_instant_clip_error = ""
            if not self.session_active or not self.buffer or not self.generator:
                self.last_instant_clip_error = "No active live recording session. Connect to a live stream first."
                self.log_activity("Clip Highlight failed: no active live recording session.", "error")
                return None

            # Automatically activate background auto-clipping if not already active
            if not self.auto_clip_enabled:
                self.auto_clip_enabled = True
                self.last_auto_clip_time = time.time()
                if not self._auto_clip_thread or not self._auto_clip_thread.is_alive():
                    self._auto_clip_stop_event.clear()
                    self._auto_clip_thread = threading.Thread(target=self._auto_clip_timer_loop, daemon=True)
                    self._auto_clip_thread.start()
                self.log_activity("Clip Highlight triggered: auto-clipping enabled automatically.", "success")

            duration_sec = max(5, min(90, duration_sec))
            buf_duration = self.buffer.get_window_duration()
            if buf_duration < 4.0:
                self.last_instant_clip_error = f"Buffering stream ({buf_duration:.0f}s recorded)... Wait a few seconds and try again."
                self.log_activity(self.last_instant_clip_error, "warn")
                return None

            # Base times on recorded buffer chunks to guarantee exact length and audio sync
            if self.buffer.chunks:
                end_sec = self.buffer.chunks[-1].end_sec
                start_sec = max(self.buffer.chunks[0].start_sec, end_sec - float(duration_sec))
            else:
                current_time = (time.time() - self.session_start_time) if self.session_start_time else 0.0
                start_sec = max(0.0, current_time - duration_sec)
                end_sec = current_time

            title = f"Live Highlight #{len(self.clips) + 1}"
            category = "High-energy moments"

            # Check recent transcript for title inspiration
            if self.recent_transcripts:
                last_txt = self.recent_transcripts[-1].get("text", "")
                if last_txt:
                    words = last_txt.split()[:5]
                    title = " ".join(words).title() + "!"

            transcripts = [
                t for t in self.recent_transcripts
                if t.get("start", 0) <= end_sec and t.get("end", 0) >= start_sec
            ]
            if not transcripts:
                transcripts = list(self.recent_transcripts[-10:])
            prefs = dict(self.editing_prefs)

        self.log_activity(f"Instant Clip requested: extracting {duration_sec}s slice ({start_sec:.1f}s - {end_sec:.1f}s)...", "info")
        self.log_activity("Processing video: face tracking, smart reframing, audio synchronization...", "info")

        clip_data = self.generator.render_clip(
            start_sec=start_sec,
            end_sec=end_sec,
            title=title,
            category=category,
            transcripts=transcripts,
            editing_prefs=prefs,
            energy_score=8.0,
        )

        if clip_data:
            with self._lock:
                self.clips.insert(0, clip_data)
            self.log_activity(f"Instant Short ready: \"{clip_data['title']}\" ({clip_data['duration']}s, layout: {clip_data.get('layout')})", "success")
            self._emit_event("new_clip", clip_data)
            return clip_data

        self.log_activity("Instant Clip render failed during FFmpeg encoding.", "error")
        return None

    def batch_clip(self, count: int = 4, duration_sec: int = 30) -> list[dict[str, Any]]:
        """Generate N professionally edited Shorts from the rolling buffer."""
        count = max(1, min(10, count))
        duration_sec = max(10, min(90, duration_sec))

        with self._lock:
            if not self.session_active or not self.buffer or not self.generator:
                self.log_activity("Batch Clip failed: no active live recording session.", "error")
                return []
            buf_duration = self.buffer.get_window_duration()
            if buf_duration < min(float(duration_sec), 20.0):
                self.log_activity(
                    f"Buffer is still accumulating ({buf_duration:.0f}s / {duration_sec}s). Please wait for sufficient buffer before generating batch Shorts.",
                    "warn",
                )
                return []

            if self.buffer.chunks:
                available_start = self.buffer.chunks[0].start_sec
                current_time = self.buffer.chunks[-1].end_sec
            else:
                current_time = (time.time() - self.session_start_time) if self.session_start_time else 0.0
                available_start = max(0.0, current_time - buf_duration)

            transcripts_copy = list(self.recent_transcripts)
            prefs = dict(self.editing_prefs)

        self.log_activity(f"Batch Clip requested: targeting {count} Shorts ({duration_sec}s each) from buffer...", "info")
        target_dur = float(duration_sec)
        intervals: list[tuple[float, float, str]] = []

        # 1. Look for distinct speech burst groups and center full duration slice on them
        if len(transcripts_copy) >= count:
            step = max(1, len(transcripts_copy) // count)
            for i in range(count):
                sub = transcripts_copy[i * step : (i + 1) * step]
                if sub:
                    speech_center = (float(sub[0].get("start", current_time)) + float(sub[-1].get("end", current_time))) / 2.0
                    s = speech_center - (target_dur / 2.0)
                    e = speech_center + (target_dur / 2.0)
                    if e > current_time:
                        e = current_time
                        s = e - target_dur
                    if s < available_start:
                        s = available_start
                        e = min(current_time, s + target_dur)
                    s = max(0.0, s)
                    if e - s >= min(target_dur, 20.0):
                        words = sub[0].get("text", "").split()[:4]
                        t_title = (" ".join(words).title() + "!") if words else f"Live Highlight #{len(self.clips) + len(intervals) + 1}"
                        intervals.append((s, e, t_title))

        # 2. Fill remaining intervals by staggering full target_dur slices across the available buffer
        if len(intervals) < count:
            needed = count - len(intervals)
            for i in range(needed):
                shift = i * (target_dur * 0.5)
                end_i = current_time - shift
                start_i = end_i - target_dur
                if start_i < available_start:
                    start_i = available_start
                    end_i = min(current_time, start_i + target_dur)
                start_i = max(0.0, start_i)
                if end_i - start_i >= min(target_dur, 20.0):
                    intervals.append((start_i, end_i, f"Live Highlight #{len(self.clips) + len(intervals) + 1}"))

        generated: list[dict[str, Any]] = []
        for idx, (s_time, e_time, title) in enumerate(intervals[:count]):
            self.log_activity(f"Rendering batch Short {idx + 1}/{len(intervals[:count])}: \"{title}\" ({s_time:.1f}s - {e_time:.1f}s)...", "info")
            sub_transcripts = [
                t for t in transcripts_copy
                if t.get("start", 0) <= e_time and t.get("end", 0) >= s_time
            ]
            clip_data = self.generator.render_clip(
                start_sec=s_time,
                end_sec=e_time,
                title=title,
                category="High-energy moments",
                transcripts=sub_transcripts,
                editing_prefs=prefs,
                energy_score=8.5,
            )
            if clip_data:
                with self._lock:
                    self.clips.insert(0, clip_data)
                self.log_activity(f"Batch Short {idx + 1}/{len(intervals[:count])} completed: \"{title}\"", "success")
                self._emit_event("new_clip", clip_data)
                generated.append(clip_data)

        self.log_activity(f"Batch render completed: {len(generated)} Shorts ready in export gallery.", "success")
        return generated

    def delete_clip(self, clip_id: str) -> bool:
        """Delete a generated clip from memory and disk."""
        return self.delete_clips([clip_id]) > 0

    def delete_clips(self, clip_ids: list[str]) -> int:
        """Batch delete multiple clips by ID from memory and disk."""
        deleted_count = 0
        with self._lock:
            id_set = set(clip_ids)
            initial_count = len(self.clips)
            self.clips = [c for c in self.clips if c.get("id") not in id_set]
            self.ranked_clips = [c for c in self.ranked_clips if c.get("id") not in id_set]
            deleted_count = initial_count - len(self.clips)
            try:
                (self.clips_dir / "ranked_clips.json").write_text(
                    json.dumps(self.ranked_clips, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

            for clip_id in id_set:
                clip_folder = self.clips_dir / clip_id
                if clip_folder.exists():
                    try:
                        shutil.rmtree(clip_folder)
                    except Exception as e:
                        logger.warning("Failed deleting clip folder %s: %s", clip_id, e)

            if deleted_count == 0 and len(id_set) > 0:
                deleted_count = len(id_set)
        self.log_activity(f"Batch deleted {deleted_count} clips.", "info")
        return deleted_count

    def update_clip(self, clip_id: str, updates: dict[str, Any]) -> bool:
        """Update metadata (title, category, description, tags, subtitle/text) of a clip in memory and disk."""
        with self._lock:
            found = False
            for clip in self.clips:
                if clip.get("id") == clip_id:
                    for k in ("title", "category", "description", "tags", "tags_str", "subtitle_text", "custom_text", "overlay_text"):
                        if k in updates and updates[k] is not None:
                            clip[k] = updates[k]
                    found = True
                    meta_path = self.clips_dir / clip_id / "meta.json"
                    if meta_path.exists():
                        try:
                            meta_path.write_text(json.dumps(clip, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning("Failed writing updated meta.json for clip %s: %s", clip_id, e)
                    break

            for r_clip in self.ranked_clips:
                if r_clip.get("id") == clip_id:
                    for k in ("title", "category", "description", "tags", "tags_str", "subtitle_text", "custom_text", "overlay_text"):
                        if k in updates and updates[k] is not None:
                            r_clip[k] = updates[k]
                    try:
                        (self.clips_dir / "ranked_clips.json").write_text(
                            json.dumps(self.ranked_clips, indent=2), encoding="utf-8"
                        )
                    except Exception:
                        pass
                    break

            if found:
                self.log_activity(f"Updated metadata for clip {clip_id}.", "info")
            return found

    def generate_clip_description(self, clip_id: str) -> dict[str, Any]:
        """Generate high-engagement viral description, hashtags, and SEO tags for a clip."""
        with self._lock:
            target_clip = None
            for c in self.clips:
                if c.get("id") == clip_id:
                    target_clip = c
                    break
            if not target_clip:
                meta_file = self.clips_dir / clip_id / "meta.json"
                if meta_file.exists():
                    try:
                        target_clip = json.loads(meta_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

            if not target_clip:
                return {"ok": False, "error": f"Clip {clip_id} not found."}

            title = str(target_clip.get("title", "")).strip()
            duration = float(target_clip.get("duration", 30.0))
            category = str(target_clip.get("category", "Gaming Highlight"))

            # Build rich engaging description
            desc_lines = [
                f"🔥 {title}",
                "",
                f"Watch this insane stream moment! Automated highlight captured in 9:16 vertical format with Clipify AI Live Studio.",
                "",
                f"⏱️ Clip Length: {duration:.1f}s | Category: {category}",
                "🚀 Created with 100% Free & Open-Source Clipify AI",
                "",
                "👉 Drop a LIKE, leave a COMMENT, and SUBSCRIBE for more daily viral stream clips!"
            ]
            description = "\n".join(desc_lines)

            # Build relevant hashtags based on keywords
            base_tags = ["#Shorts", "#Gaming", "#LiveStream", "#ViralShorts", "#ClipifyAI", "#Highlights", "#Trending"]
            kw_pool = (title + " " + category).lower()
            if any(w in kw_pool for w in ["gta", "car", "drift", "speed", "drive", "racing"]):
                base_tags.extend(["#GTA5", "#GTAV", "#GamingClips", "#Clutch"])
            elif any(w in kw_pool for w in ["minecraft", "craft", "parkour"]):
                base_tags.extend(["#Minecraft", "#MinecraftShorts"])
            elif any(w in kw_pool for w in ["rage", "mad", "funny", "fail", "omg", "lol"]):
                base_tags.extend(["#StreamerRage", "#FunnyMoments", "#InstantRegret"])
            elif any(w in kw_pool for w in ["valorant", "apex", "fortnite", "cod", "warzone"]):
                base_tags.extend(["#FPS", "#ProPlay", "#Headshot"])

            tags_str = " ".join(base_tags)

            # Update clip
            target_clip["description"] = description
            target_clip["tags"] = base_tags
            target_clip["tags_str"] = tags_str

            meta_file = self.clips_dir / clip_id / "meta.json"
            if meta_file.parent.exists():
                try:
                    meta_file.write_text(json.dumps(target_clip, indent=2), encoding="utf-8")
                except Exception as e:
                    logger.warning("Failed writing meta.json: %s", e)

            for r_clip in self.ranked_clips:
                if r_clip.get("id") == clip_id:
                    r_clip["description"] = description
                    r_clip["tags"] = base_tags
                    r_clip["tags_str"] = tags_str
                    try:
                        (self.clips_dir / "ranked_clips.json").write_text(
                            json.dumps(self.ranked_clips, indent=2), encoding="utf-8"
                        )
                    except Exception:
                        pass
                    break

            return {
                "ok": True,
                "clip_id": clip_id,
                "title": title,
                "description": description,
                "tags": base_tags,
                "tags_str": tags_str,
            }

    def log_ranking(self, message: str, level: str = "info") -> None:
        """Record real-time activity for the AI Ranking console."""
        with self._lock:
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "message": message,
                "level": level,
            }
            self.ranking_logs.append(entry)
            if len(self.ranking_logs) > 100:
                self.ranking_logs.pop(0)

    def rank_clips_ai(
        self,
        top_n: int = 10,
        clip_ids: Optional[list[str]] = None,
        model_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Ranks existing clips using Ollama AI, predicting hook strength and viral potential."""
        with self._lock:
            if self.is_ranking:
                return list(self.ranked_clips)
            self.is_ranking = True
            self.ranking_logs.clear()
            candidates = list(self.clips)
            if clip_ids:
                candidates = [c for c in candidates if c.get("id") in clip_ids]
            if not model_name:
                model_name = self.editing_prefs.get("model_name")

        self.log_ranking("Initializing AI Ranking Engine...", "system")
        if not candidates:
            self.log_ranking("No clips available to rank. Please generate or auto-clip highlights first.", "warn")
            with self._lock:
                self.is_ranking = False
            return []

        self.log_ranking(f"Found {len(candidates)} candidate clips for AI evaluation (Top {top_n} selection).", "info")

        # Discover or connect to selected Ollama model
        ollama_url = "http://localhost:11434"
        selected_model = (model_name or "").strip()
        if selected_model == "heuristic":
            self.log_ranking("Using Built-in Fast AI heuristic viral analyzer.", "info")
            active_model = "heuristic"
        else:
            active_model = "heuristic"
            try:
                req = urllib.request.Request(f"{ollama_url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    tags_data = json.loads(resp.read().decode())
                    available_models = [m.get("name") for m in tags_data.get("models", [])]
                    if selected_model and any(selected_model.lower() in m.lower() or m.lower() in selected_model.lower() for m in available_models):
                        # Matched chosen model
                        for m in available_models:
                            if selected_model.lower() in m.lower() or m.lower() in selected_model.lower():
                                active_model = m
                                break
                    elif available_models:
                        active_model = available_models[0]
                    
                    if active_model != "heuristic":
                        self.log_ranking(f"Connected to Ollama engine (model: {active_model}).", "success")
                    else:
                        self.log_ranking("No compatible Ollama model found; using Built-in Fast AI.", "warn")
            except Exception:
                self.log_ranking("Ollama local service offline; utilizing heuristic viral retention analyzer.", "warn")
                active_model = "heuristic"

        model_name = active_model

        scored_clips = []
        for idx, clip in enumerate(candidates):
            title = clip.get("title", f"Clip #{idx+1}")
            dur = clip.get("duration", 30)
            sub_text = clip.get("subtitle_text") or clip.get("transcript_snippet") or ""
            cat = clip.get("category", "High-energy moments")
            base_score = float(clip.get("energy_score", 7.5))

            self.log_ranking(f"Analyzing Clip {idx+1}/{len(candidates)}: \"{title}\" ({dur}s)...", "info")

            viral_score = None
            hook_grade = "A"
            verdict = "Strong vertical retention and energetic pacing."

            if model_name != "heuristic":
                prompt = (
                    f"You are an expert viral YouTube Shorts and TikTok content strategist.\n"
                    f"Analyze this short video clip candidate:\n"
                    f"- Title: {title}\n"
                    f"- Category: {cat}\n"
                    f"- Duration: {dur}s\n"
                    f"- Transcript/Audio Hook: {sub_text[:200] if sub_text else 'Exciting livestream moment'}\n\n"
                    f"Evaluate: 1) Hook strength in first 3 seconds, 2) Viewer retention, 3) Shareability.\n"
                    f"Respond strictly in valid JSON with these keys:\n"
                    f"{{\n"
                    f'  "viral_score": a number from 7.0 to 10.0,\n'
                    f'  "hook_grade": "A+" or "A" or "B+",\n'
                    f'  "verdict": "One punchy sentence explaining why this clip will perform well"\n'
                    f"}}\nJSON ONLY:"
                )
                try:
                    chat_payload = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 120},
                    }
                    chat_req = urllib.request.Request(
                        f"{ollama_url}/api/chat",
                        data=json.dumps(chat_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(chat_req, timeout=25) as resp:
                        res = json.loads(resp.read().decode())
                        content = res.get("message", {}).get("content", "").strip()
                        m = re.search(r"\{.*\}", content, re.DOTALL)
                        if m:
                            parsed = json.loads(m.group(0))
                            viral_score = float(parsed.get("viral_score", 8.5))
                            hook_grade = str(parsed.get("hook_grade", "A"))
                            verdict = str(parsed.get("verdict", verdict))
                except Exception as e:
                    self.log_ranking(f"Ollama chat fallback for clip #{idx+1}: {e}", "debug")

            # Fallback heuristic calculation if Ollama was offline or timed out
            if viral_score is None:
                dur_bonus = 1.0 if 20 <= dur <= 45 else 0.5
                text_len_bonus = 0.5 if len(sub_text) > 30 else 0.2
                viral_score = min(9.9, base_score * 0.7 + dur_bonus + text_len_bonus + (idx % 3) * 0.2)
                if viral_score >= 9.2:
                    hook_grade = "A+"
                    verdict = "Peak excitement with instantaneous viewer hook in first 2 seconds."
                elif viral_score >= 8.5:
                    hook_grade = "A"
                    verdict = "High dynamic energy with strong retention trajectory."
                else:
                    hook_grade = "B+"
                    verdict = "Solid conversational highlight with steady watch time."

            viral_score = round(viral_score, 1)
            self.log_ranking(
                f"-> Scored Clip #{idx+1}: Viral {viral_score}/10 | Hook: {hook_grade} | \"{verdict}\"",
                "success" if viral_score >= 9.0 else "info"
            )

            clip_copy = dict(clip)
            clip_copy["viral_score"] = viral_score
            clip_copy["hook_grade"] = hook_grade
            clip_copy["verdict"] = verdict
            clip_copy["ai_verdict"] = verdict
            scored_clips.append(clip_copy)
            time.sleep(0.12)

        # Sort by viral_score descending
        scored_clips.sort(key=lambda c: c.get("viral_score", 0), reverse=True)
        top_clips = scored_clips[:top_n]
        for rank_num, c in enumerate(top_clips, 1):
            c["rank"] = rank_num

        with self._lock:
            self.ranked_clips = top_clips
            self.is_ranking = False
            try:
                (self.clips_dir / "ranked_clips.json").write_text(
                    json.dumps(top_clips, indent=2), encoding="utf-8"
                )
            except Exception as e:
                logger.warning("Could not persist ranked clips: %s", e)

        self.log_ranking(
            f"Ranking Complete! Top {len(top_clips)} clips selected. Top Clip: #{top_clips[0]['rank']} \"{top_clips[0]['title']}\" ({top_clips[0]['viral_score']}/10)",
            "success"
        )
        return top_clips

    def get_ranked_clips(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.ranked_clips)

    def get_ranking_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.ranking_logs)

    def get_status(self) -> dict[str, Any]:
        """Return the current Live Studio state."""
        elapsed = 0.0
        if self.session_active and self.session_start_time and self.status == "live":
            elapsed = time.time() - self.session_start_time

        buf_dur = self.buffer.get_window_duration() if self.buffer else 0.0
        buf_chunks = self.buffer.get_total_chunks() if self.buffer else 0
        has_preview = bool(self.buffer_dir and (self.buffer_dir / "preview_current.jpg").exists())

        return {
            "session_active": self.session_active,
            "status": self.status,
            "status_detail": self.status_detail,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "elapsed_seconds": round(elapsed, 1),
            "buffer_duration_seconds": round(buf_dur, 1),
            "buffer_chunks": buf_chunks,
            "auto_clip_enabled": self.auto_clip_enabled,
            "auto_clip_interval": self.auto_clip_interval,
            "auto_clip_target": self.auto_clip_target,
            "sensitivity": self.sensitivity,
            "metadata": self.stream_metadata,
            "clips_count": len(self.clips),
            "ranked_clips_count": len(self.ranked_clips),
            "is_ranking": self.is_ranking,
            "has_preview": has_preview,
            "editing_prefs": dict(self.editing_prefs),
            "console_logs": list(self.console_logs[-50:]),
        }

    def get_recent_transcripts(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.recent_transcripts)

    def get_clips(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.clips)

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        entry = {
            "type": event_type,
            "data": data,
            "time": time.time(),
        }
        self.live_events.append(entry)
        if len(self.live_events) > 200:
            self.live_events.pop(0)


# Module-level singleton instance
_LIVE_MANAGER: Optional[LiveStudioManager] = None
_INIT_LOCK = threading.Lock()


def get_live_manager(data_dir: Path, ffmpeg_bin: str, python_bin: str) -> LiveStudioManager:
    global _LIVE_MANAGER
    with _INIT_LOCK:
        if _LIVE_MANAGER is None:
            _LIVE_MANAGER = LiveStudioManager(
                data_dir=data_dir,
                ffmpeg_bin=ffmpeg_bin,
                python_bin=python_bin,
            )
        return _LIVE_MANAGER

