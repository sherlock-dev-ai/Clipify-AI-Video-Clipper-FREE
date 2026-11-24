"""Incremental speech transcription for Clipify AI Live Studio.

Utilizes in-memory faster-whisper CTranslate2 model for sub-second,
real-time transcription of incoming live stream audio chunks.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("clipify.live.transcriber")


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _ensure_cuda_dlls():
    """Ensure CUDA 12 and cuDNN dynamic libraries are discoverable on Windows."""
    import sys
    if sys.platform != "win32":
        return
    import site
    search_dirs = []
    try:
        for base in site.getsitepackages():
            nv_dir = Path(base) / "nvidia"
            if nv_dir.is_dir():
                for sub in nv_dir.iterdir():
                    bin_dir = sub / "bin"
                    if bin_dir.is_dir():
                        search_dirs.append(str(bin_dir))
            ct2_dir = Path(base) / "ctranslate2"
            if ct2_dir.is_dir():
                search_dirs.append(str(ct2_dir))
    except Exception:
        pass
    app_data = os.environ.get("LOCALAPPDATA", "")
    if app_data:
        runtime_nv = Path(app_data) / "Programs" / "ClipifyAI" / "runtime" / "Lib" / "site-packages" / "nvidia"
        if runtime_nv.is_dir():
            for sub in runtime_nv.iterdir():
                b = sub / "bin"
                if b.is_dir():
                    search_dirs.append(str(b))
    for d in search_dirs:
        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
            if d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


def _detect_default_device() -> str:
    _ensure_cuda_dlls()
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


@dataclass
class LiveTranscriptSegment:
    start_sec: float
    end_sec: float
    text: str
    speaker: str = "Host"
    confidence: float = 1.0


class LiveTranscriber:
    """Manages high-speed incremental transcription of live stream audio chunks."""

    def __init__(
        self,
        python_bin: str,
        ffmpeg_bin: str,
        model_name: str = "tiny",
        device: Optional[str] = None,
        on_segment: Optional[Callable[[LiveTranscriptSegment], None]] = None,
    ):
        self.python_bin = python_bin
        self.ffmpeg_bin = ffmpeg_bin
        self.model_name = model_name or "tiny"
        self.device = device or _detect_default_device()
        self.on_segment = on_segment

        self.audio_queue: queue.Queue[tuple[Path, float, float]] = queue.Queue(maxsize=150)
        self.transcripts: list[LiveTranscriptSegment] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._model_instance: Any = None
        self._model_loaded: bool = False

    def start(self) -> None:
        """Start the background transcription processor."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        """Stop transcription processing."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=3)
            self._worker_thread = None

    def enqueue_chunk(self, chunk_wav_path: Path, start_sec: float, duration: float) -> None:
        """Submit a newly extracted WAV segment for transcription."""
        try:
            self.audio_queue.put_nowait((chunk_wav_path, start_sec, duration))
        except queue.Full:
            logger.warning("Live audio transcription queue is full; dropping older chunk")

    def get_recent_transcripts(self, last_n_seconds: float = 300.0) -> list[LiveTranscriptSegment]:
        """Retrieve transcribed utterances within the last N seconds."""
        with self._lock:
            if not self.transcripts:
                return []
            latest_time = self.transcripts[-1].end_sec
            min_time = latest_time - last_n_seconds
            return [s for s in self.transcripts if s.end_sec >= min_time]

    def get_full_transcript_text(self) -> str:
        """Return full text transcribed so far."""
        with self._lock:
            return " ".join(s.text for s in self.transcripts)

    def _get_model(self) -> Any:
        """Lazy-load the in-memory faster-whisper model on GPU with CPU fallback."""
        if not self._model_loaded:
            _ensure_cuda_dlls()
            try:
                from faster_whisper import WhisperModel
                m_name = "tiny" if self.model_name in ("tiny", "default", "") else "base"
                compute_type = "float16" if self.device == "cuda" else "int8"
                logger.info("Initializing in-memory WhisperModel (%s, %s, device=%s)...", m_name, compute_type, self.device)
                try:
                    self._model_instance = WhisperModel(m_name, device=self.device, compute_type=compute_type)
                except Exception as cuda_exc:
                    if self.device == "cuda":
                        logger.warning("CUDA WhisperModel initialization failed (%s); falling back to CPU int8", cuda_exc)
                        self.device = "cpu"
                        self._model_instance = WhisperModel(m_name, device="cpu", compute_type="int8")
                    else:
                        raise cuda_exc
                logger.info("WhisperModel successfully initialized in-memory on %s.", self.device)
            except Exception as e:
                logger.warning("In-memory faster-whisper load failed (%s); will fallback to subproc", e)
                self._model_instance = None
            self._model_loaded = True
        return self._model_instance

    def _worker_loop(self) -> None:
        """Pulls audio chunks from the queue and transcribes them with sub-100ms latency."""
        os.environ.setdefault("OMP_STACKSIZE", "64M")
        os.environ.setdefault("KMP_STACKSIZE", "64M")
        os.environ.setdefault("OMP_NUM_THREADS", "2")

        # Pre-warm model
        self._get_model()

        while not self._stop_event.is_set():
            try:
                item = self.audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            wav_path, chunk_start, chunk_duration = item
            try:
                segments = self._transcribe_wav(wav_path, chunk_start)
                if segments:
                    with self._lock:
                        self.transcripts.extend(segments)
                    for seg in segments:
                        if self.on_segment:
                            try:
                                self.on_segment(seg)
                            except Exception as e:
                                logger.exception("Error in on_segment callback: %s", e)
            except Exception as e:
                logger.debug("Transcription error for chunk %s: %s", wav_path.name, e)
            finally:
                self.audio_queue.task_done()
                try:
                    if wav_path.exists():
                        wav_path.unlink()
                except Exception:
                    pass

    def _transcribe_wav(self, wav_path: Path, chunk_start: float) -> list[LiveTranscriptSegment]:
        """Transcribe an isolated 16kHz WAV file."""
        if not wav_path.exists() or wav_path.stat().st_size < 1000:
            return []

        segments: list[LiveTranscriptSegment] = []
        model = self._get_model()

        # In-memory execution (sub-100ms)
        if model is not None:
            try:
                segs, _ = model.transcribe(
                    str(wav_path),
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    condition_on_previous_text=False,
                )
                for s in segs:
                    txt = s.text.strip()
                    if txt:
                        seg_start = chunk_start + float(s.start)
                        seg_end = chunk_start + float(s.end)
                        segments.append(
                            LiveTranscriptSegment(
                                start_sec=round(seg_start, 2),
                                end_sec=round(max(seg_end, seg_start + 0.6), 2),
                                text=txt,
                            )
                        )
                return segments
            except Exception as e:
                logger.debug("In-memory faster-whisper transcribe failed (%s), trying fallback", e)

        # Fallback to subprocess if in-memory fails
        code = f"""
import os, sys, json
try:
    from live.transcriber import _ensure_cuda_dlls, _detect_default_device
    _ensure_cuda_dlls()
    dev = _detect_default_device()
    ctype = 'float16' if dev == 'cuda' else 'int8'
    from faster_whisper import WhisperModel
    try:
        m = WhisperModel('tiny', device=dev, compute_type=ctype)
    except Exception:
        m = WhisperModel('tiny', device='cpu', compute_type='int8')
    segs, _ = m.transcribe(r'{str(wav_path)}', beam_size=1)
    res = [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in segs if s.text.strip()]
    print('JSON:' + json.dumps(res))
except Exception as e:
    print('ERR:' + str(e))
"""
        proc = subprocess.run(
            [self.python_bin, "-c", code],
            capture_output=True, text=True,
            timeout=15, creationflags=_hidden_flags(),
        )

        for line in proc.stdout.splitlines():
            if line.startswith("JSON:"):
                try:
                    raw_segs = json.loads(line[5:])
                    for s in raw_segs:
                        text = s.get("text", "").strip()
                        if text:
                            seg_start = chunk_start + float(s.get("start", 0.0))
                            seg_end = chunk_start + float(s.get("end", 0.0))
                            segments.append(
                                LiveTranscriptSegment(
                                    start_sec=round(seg_start, 2),
                                    end_sec=round(max(seg_end, seg_start + 0.6), 2),
                                    text=text,
                                )
                            )
                except Exception as ex:
                    logger.debug("Failed parsing fallback whisper output: %s", ex)

        return segments
