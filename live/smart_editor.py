"""Smart AI Editor for Live Studio Shorts.

Orchestrates intelligent editing decisions:
- Automatic content classification (gaming facecam, talking head, podcast, reaction)
- Face tracking and stabilized 9:16 crop box
- Dynamic gaming split-screen layout (gameplay top, facecam bottom)
- Word-level animated ASS subtitles with 5 styling presets
- Subtle energy-based zoom / punch-in
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from live.caption_styler import CaptionStyler, ffmpeg_ass_filter
from live.content_analyzer import ContentAnalyzer, ContentProfile
from live.face_tracker import FaceTracker

logger = logging.getLogger("clipify.live.smart_editor")


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@dataclass
class EditDecision:
    layout: str  # "gaming_split", "talking_head", "podcast_split", "blurred_frame"
    content_type: str
    face_tracked: bool = False
    facecam_detected: bool = False
    captions_applied: bool = False
    caption_style: str = "highlight"
    energy_zoom: bool = False
    badges: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SmartEditor:
    """Intelligent Shorts video editing engine."""

    def __init__(self, ffmpeg_bin: str, python_bin: Optional[str] = None):
        self.ffmpeg_bin = ffmpeg_bin
        self.python_bin = python_bin
        self.analyzer = ContentAnalyzer(ffmpeg_bin)
        self.caption_styler = CaptionStyler()

    _shared_direct_whisper = None

    def _transcribe_direct(self, raw_video_path: Path, language: str = "en") -> list[dict[str, Any]]:
        """Run fast local speech recognition directly on the extracted raw clip."""
        if not raw_video_path.exists() or raw_video_path.stat().st_size < 1000:
            return []
        
        lang_arg = None if language in ("auto", "", None) else ("hi" if language in ("hinglish", "hi-en") else language)

        # 1. Try in-process faster-whisper if available
        try:
            logger.info("Running fast direct clip transcription for %s (lang=%s)...", raw_video_path.name, lang_arg or "auto")
            from faster_whisper import WhisperModel
            try:
                from clipify.platform.gpu_manager import get_whisper_device_and_type
                w_dev, w_ctype = get_whisper_device_and_type()
            except Exception:
                w_dev, w_ctype = ("cpu", "int8")
            if SmartEditor._shared_direct_whisper is None or getattr(SmartEditor, "_shared_direct_whisper_dev", None) != w_dev:
                try:
                    SmartEditor._shared_direct_whisper = WhisperModel("base", device=w_dev, compute_type=w_ctype)
                    SmartEditor._shared_direct_whisper_dev = w_dev
                except Exception:
                    SmartEditor._shared_direct_whisper = WhisperModel("base", device="cpu", compute_type="int8")
                    SmartEditor._shared_direct_whisper_dev = "cpu"
            model = SmartEditor._shared_direct_whisper
            kwargs: Dict[str, Any] = {
                "word_timestamps": True,
                "beam_size": 1,
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 500},
                "no_speech_threshold": 0.6,
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
                "condition_on_previous_text": False,
            }
            if lang_arg:
                kwargs["language"] = lang_arg
            segments, _ = model.transcribe(str(raw_video_path), **kwargs)
            try:
                from hindi_transliterator import has_devanagari, transliterate_devanagari_to_hinglish
            except Exception:
                has_devanagari = lambda s: False
                transliterate_devanagari_to_hinglish = lambda s: s
            results = []
            for seg in segments:
                words = []
                if hasattr(seg, "words") and seg.words:
                    for w in seg.words:
                        w_text = w.word.strip()
                        if w_text and has_devanagari(w_text):
                            w_text = transliterate_devanagari_to_hinglish(w_text)
                        if w_text:
                            words.append({
                                "word": w_text,
                                "start": round(w.start, 2),
                                "end": round(w.end, 2),
                            })
                txt = seg.text.strip()
                if txt and has_devanagari(txt):
                    txt = transliterate_devanagari_to_hinglish(txt)
                if txt:
                    results.append({
                        "start": round(seg.start, 2),
                        "end": round(seg.end, 2),
                        "text": txt,
                        "words": words,
                    })
            if results:
                logger.info("In-process direct clip transcription completed: %d segment(s)", len(results))
                return results
        except Exception as e:
            logger.debug("In-process direct whisper unavailable: %s. Trying subprocess python_bin...", e)

        # 2. Subprocess fallback using self.python_bin (where faster_whisper / whisperx is installed)
        try:
            py_bin = self.python_bin
            if not py_bin or not Path(py_bin).exists():
                test_py = Path(r"L:\tester\runtime\Scripts\python.exe")
                if test_py.is_file():
                    py_bin = str(test_py)
                else:
                    py_bin = sys.executable

            code = (
                "import sys, json\n"
                "try:\n"
                "    from faster_whisper import WhisperModel\n"
                "    m = WhisperModel('tiny', device='cpu', compute_type='int8')\n"
                f"    lang = {repr(lang_arg)}\n"
                "    kwargs = {'word_timestamps': True, 'beam_size': 1}\n"
                "    if lang: kwargs['language'] = lang\n"
                "    segs, _ = m.transcribe(sys.argv[1], **kwargs)\n"
                "    out = []\n"
                "    for s in segs:\n"
                "        words = [{'word': w.word.strip(), 'start': round(w.start, 2), 'end': round(w.end, 2)} for w in (s.words or []) if w.word.strip()]\n"
                "        if s.text.strip():\n"
                "            out.append({'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip(), 'words': words})\n"
                "    print(json.dumps(out))\n"
                "except Exception as ex:\n"
                "    print(json.dumps([]))\n"
            )

            res = subprocess.run(
                [py_bin, "-c", code, str(raw_video_path)],
                capture_output=True,
                text=True,
                timeout=45,
                creationflags=_hidden_flags()
            )
            if res.returncode == 0 and res.stdout.strip():
                lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip().startswith("[")]
                if lines:
                    parsed = json.loads(lines[-1])
                    if isinstance(parsed, list) and parsed:
                        logger.info("Subprocess direct clip transcription completed: %d segment(s)", len(parsed))
                        return parsed
        except Exception as ex:
            logger.warning("Subprocess direct clip transcription failed: %s", ex)

        return []

    def edit(
        self,
        raw_video_path: Path,
        output_vertical: Path,
        transcripts: List[Dict[str, Any]],
        clip_start: float,
        clip_duration: float,
        editing_prefs: Optional[Dict[str, Any]] = None,
        energy_score: float = 7.0,
    ) -> EditDecision:
        """Process raw clip into an intelligently edited vertical Short."""
        prefs = editing_prefs or {}
        auto_edit_enabled = bool(prefs.get("auto_edit", True))
        face_track_enabled = bool(prefs.get("face_tracking", True))
        gaming_layout_enabled = bool(prefs.get("gaming_layout", True))
        auto_captions_enabled = bool(prefs.get("auto_captions", True))
        caption_style = str(prefs.get("caption_style", "highlight"))
        caption_font = str(prefs.get("caption_font", "Montserrat Extra Bold"))
        caption_language = str(prefs.get("caption_language", "en")).strip().lower()
        background_style = str(prefs.get("background_style", "soft_blur"))
        background_color = str(prefs.get("background_color", "#000000"))
        custom_text = str(prefs.get("custom_text", "")).strip()
        custom_text_pos = str(prefs.get("custom_text_pos", "top-center"))
        custom_text_color = str(prefs.get("custom_text_color", "#FFFFFF"))

        # 1. Content Analysis
        transcript_snippet = " ".join(t.get("text", "") for t in transcripts)
        profile = self.analyzer.analyze(raw_video_path, transcript_text=transcript_snippet, sample_count=6)
        logger.info(
            "Content profile for %s: mode=%s, facecam=%s, faces=%d",
            raw_video_path.name, profile.mode, bool(profile.facecam_box), profile.faces_detected,
        )

        # 2. Layout Decision
        layout = "blurred_frame"
        face_tracked = False
        facecam_detected = False
        badges: List[str] = []

        if auto_edit_enabled and gaming_layout_enabled:
            layout = "gaming_split"
            facecam_detected = True
            badges.append("🎮 Gaming Split")
        elif auto_edit_enabled and not gaming_layout_enabled:
            layout = "podcast_split"
            badges.append("🎙️ Two-Person Split")
        elif auto_edit_enabled and face_track_enabled and profile.mode == "talking_head":
            layout = "talking_head"
            face_tracked = True
            badges.append("👤 Face Tracked")
        else:
            layout = "blurred_frame"
            badges.append("✨ Smart Fit")

        # Background badge if customized
        if background_style == "solid_black":
            badges.append("⬛ Black BG")
        elif background_style == "custom_color":
            badges.append("🎨 Custom BG")
        elif background_style == "heavy_blur":
            badges.append("🎬 Cinematic Blur")

        # 3. Energy Zoom Check
        energy_zoom = auto_edit_enabled and (energy_score >= 8.5)
        if energy_zoom:
            badges.append("⚡ Dynamic Zoom")

        # 4. Generate Subtitles ASS & Custom Text Overlay
        ass_path: Optional[str] = None
        captions_applied = False
        should_render_captions = auto_captions_enabled and (caption_style.lower() != "none")
        has_custom_text = bool(custom_text)

        effective_transcripts = list(transcripts) if transcripts else []
        effective_start = clip_start
        effective_duration = clip_duration

        if should_render_captions:
            words = self.caption_styler._extract_clip_words(
                effective_transcripts, effective_start, effective_start + effective_duration, uppercase=False
            )
            # If no speech words detected from stream intervals, run direct on-the-fly transcription
            if not words:
                direct_segs = self._transcribe_direct(raw_video_path, language=caption_language)
                if direct_segs:
                    effective_transcripts = direct_segs
                    effective_start = 0.0
                    effective_duration = clip_duration
                    words = self.caption_styler._extract_clip_words(
                        effective_transcripts, 0.0, effective_duration, uppercase=False
                    )

            # If audio was silent or non-verbal, only use custom_text if provided (never spam fake words)
            if not words and custom_text:
                words_list = custom_text.split()[:8]
                step = effective_duration / max(1, len(words_list))
                words = [
                    {
                        "word": w,
                        "start": round(effective_start + i * step, 2),
                        "end": round(effective_start + (i + 1) * step, 2),
                    }
                    for i, w in enumerate(words_list)
                ]
                effective_transcripts = [{
                    "start": round(effective_start, 2),
                    "end": round(effective_start + effective_duration, 2),
                    "text": " ".join(words_list),
                    "words": words,
                }]

        if should_render_captions or has_custom_text:
            temp_ass = output_vertical.parent / "subtitles.ass"
            try:
                ass_path = self.caption_styler.build_ass(
                    transcripts=effective_transcripts if should_render_captions else [],
                    clip_start=effective_start,
                    clip_duration=effective_duration,
                    output_ass_path=str(temp_ass),
                    style_preset="none" if not should_render_captions else caption_style,
                    layout_mode=layout,
                    custom_font=caption_font,
                    custom_text=custom_text if has_custom_text else None,
                    custom_text_pos=custom_text_pos,
                    custom_text_color=custom_text_color,
                )
                if ass_path and os.path.exists(ass_path):
                    if should_render_captions and effective_transcripts:
                        captions_applied = True
                        badges.append("💬 Auto Captions")
                    if has_custom_text:
                        badges.append("🏷️ Custom Text")
            except Exception as e:
                logger.warning("Caption/Watermark generation failed: %s", e)
                ass_path = None

        # 5. Build FFmpeg Filter Complex
        filter_str = self._build_filter_complex(
            raw_video_path=raw_video_path,
            layout=layout,
            profile=profile,
            ass_path=ass_path,
            energy_zoom=energy_zoom,
            background_style=background_style,
            background_color=background_color,
            webcam_position=str(prefs.get("webcam_position", "auto")),
        )

        # 6. Execute FFmpeg Rendering with synchronized audio resampling
        try:
            from clipify.platform.gpu_manager import get_ffmpeg_video_encoder_flags
            enc_flags = get_ffmpeg_video_encoder_flags(bitrate="12M", preset="fast", crf=16)
        except Exception:
            enc_flags = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "16M", "-pix_fmt", "yuv420p"]

        cmd = [
            self.ffmpeg_bin, "-y",
            "-i", str(raw_video_path),
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "0:a?",
            *enc_flags,
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "192k",
            "-fps_mode", "cfr",
            "-movflags", "+faststart",
            str(output_vertical),
        ]

        logger.info("Executing smart render (layout=%s, captions=%s, bg=%s)...", layout, captions_applied, background_style)
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=120, creationflags=_hidden_flags(),
        )

        if res.returncode != 0 or not output_vertical.exists() or output_vertical.stat().st_size < 1000:
            logger.error("FFmpeg smart render failed (code %d): %s", res.returncode, res.stderr[-500:])
            # Fallback to standard safe blur
            self._render_safe_fallback(
                raw_video_path, output_vertical, ass_path,
                background_style=background_style, background_color=background_color,
            )

        # Clean temporary ASS file
        if ass_path and os.path.exists(ass_path):
            try:
                os.remove(ass_path)
            except Exception:
                pass

        return EditDecision(
            layout=layout,
            content_type=profile.mode,
            face_tracked=face_tracked,
            facecam_detected=facecam_detected,
            captions_applied=captions_applied,
            caption_style=caption_style,
            energy_zoom=energy_zoom,
            badges=badges,
            metadata={
                "energy_score": energy_score,
                "profile_confidence": profile.confidence,
                "faces_detected": profile.faces_detected,
                "background_style": background_style,
                "custom_font": caption_font,
                "has_custom_text": has_custom_text,
            },
        )

    def _build_filter_complex(
        self,
        raw_video_path: Path,
        layout: str,
        profile: ContentProfile,
        ass_path: Optional[str],
        energy_zoom: bool,
        background_style: str = "soft_blur",
        background_color: str = "#000000",
        webcam_position: str = "auto",
    ) -> str:
        """Assemble the FFmpeg filter graph string."""
        ass_filter = f",{ffmpeg_ass_filter(ass_path)}" if ass_path else ""

        # Build canvas background stream
        clean_bg_color = background_color.strip()
        if not clean_bg_color.startswith("#"):
            clean_bg_color = "#" + clean_bg_color
        if not re.match(r"^#[0-9a-fA-F]{6}$", clean_bg_color):
            clean_bg_color = "#000000"

        if background_style == "solid_black":
            bg_stream = "color=c=black:s=1080x1920:r=30[bg]"
        elif background_style == "custom_color":
            bg_stream = f"color=c='{clean_bg_color}':s=1080x1920:r=30[bg]"
        elif background_style == "heavy_blur":
            bg_stream = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=45:5[bg]"
        else:  # soft_blur
            bg_stream = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:3[bg]"

        if layout == "gaming_split":
            box = profile.facecam_box
            user_webcam_pos = (webcam_position or "").lower()
            cam_presets = {
                "bottom_right": {"x": 0.76, "y": 0.68, "w": 0.22, "h": 0.26},
                "bottom_left": {"x": 0.04, "y": 0.68, "w": 0.22, "h": 0.26},
                "top_right": {"x": 0.76, "y": 0.06, "w": 0.22, "h": 0.26},
                "top_left": {"x": 0.04, "y": 0.06, "w": 0.22, "h": 0.26},
            }
            if user_webcam_pos in cam_presets:
                box = cam_presets[user_webcam_pos]
            elif not box:
                # If primary face is stationary in an outer corner (cx <= 0.25 or >= 0.75), use it.
                # Never pick an in-game portrait in mid-lateral areas (0.25 < fx < 0.75) to avoid game character duplication.
                if profile.primary_face_x is not None and (profile.primary_face_x <= 0.25 or profile.primary_face_x >= 0.75):
                    fx = profile.primary_face_x
                    fy = profile.primary_face_y if profile.primary_face_y is not None else 0.68
                    cw, ch = 0.20, 0.26
                    cx = max(0.0, min(1.0 - cw, fx - cw / 2.0))
                    cy = max(0.0, min(1.0 - ch, fy - ch / 2.0))
                    box = {"x": cx, "y": cy, "w": cw, "h": ch}
                else:
                    # Default to standard streamer bottom-right webcam position
                    box = {"x": 0.76, "y": 0.68, "w": 0.22, "h": 0.26}

            if isinstance(box, dict):
                cx, cy, cw, ch = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
            else:
                cx, cy, cw, ch = [float(v) for v in box]

            # Ensure high-fidelity webcam crop strictly focused on the streamer's person (zero gameplay bleed)
            cw = max(0.18, min(0.30, cw))
            ch = max(0.20, min(0.32, ch))
            cx = max(0.0, min(1.0 - cw, cx))
            cy = max(0.0, min(1.0 - ch, cy))

            cam_crop = (
                f"crop=w='trunc(iw*{cw:.4f}/2)*2':h='trunc(ih*{ch:.4f}/2)*2':"
                f"x='trunc(iw*{cx:.4f}/2)*2':y='trunc(ih*{cy:.4f}/2)*2'"
            )
            zoom_expr = ",crop=w='trunc(iw/1.05/2)*2':h='trunc(ih/1.05/2)*2',scale=1080:1080" if energy_zoom else ""

            # Top: Pure gameplay (center square crop cleanly excludes the corner facecam)
            # Bottom: Streamer's camera only, scaled to fill 1080x800 with Lanczos + unsharp clarity
            filters = (
                f"{bg_stream};"
                f"[0:v]crop=w='min(iw,ih)':h='min(iw,ih)':x='(iw-min(iw,ih))/2':y='(ih-min(iw,ih))/2',scale=1080:1080:flags=lanczos{zoom_expr}[gameplay];"
                f"[0:v]{cam_crop},scale=1080:800:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,crop=1080:800,unsharp=5:5:0.8:3:3:0.4[facecam];"
                "[bg][gameplay]overlay=0:20[tmp1];"
                f"[tmp1][facecam]overlay=0:1120[vcomp];"
                f"[vcomp]null{ass_filter}[vout]"
            )
            return filters

        elif layout == "talking_head":
            tracker = FaceTracker()
            crop_box = tracker.compute_static_crop(raw_video_path, face_cx=profile.primary_face_x)
            nx, ny, nw, nh = crop_box
            zoom_expr = ",crop=w='trunc(iw/1.05/2)*2':h='trunc(ih/1.05/2)*2',scale=1080:1920" if energy_zoom else ""

            crop_expr = (
                f"crop=w='trunc(iw*{nw:.4f}/2)*2':h='trunc(ih*{nh:.4f}/2)*2':"
                f"x='trunc(iw*{nx:.4f}/2)*2':y='trunc(ih*{ny:.4f}/2)*2'"
            )
            filters = (
                f"[0:v]{crop_expr},"
                f"scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920{zoom_expr}[vcomp];"
                f"[vcomp]null{ass_filter}[vout]"
            )
            return filters

        elif layout == "podcast_split":
            if profile.faces_detected >= 2 and profile.primary_face_x is not None:
                p_x = profile.primary_face_x
                s_x = profile.secondary_face_x if profile.secondary_face_x is not None else (0.75 if p_x < 0.5 else 0.25)
                left_x, right_x = min(p_x, s_x), max(p_x, s_x)
                if (right_x - left_x) < 0.25:
                    left_x, right_x = 0.20, 0.75
                cx1 = max(0.0, min(1.0 - 0.45, right_x - 0.225))  # Top panel: right speaker
                cx2 = max(0.0, min(1.0 - 0.45, left_x - 0.225))   # Bottom panel: left speaker
            elif profile.primary_face_x is not None:
                p_x = profile.primary_face_x
                if p_x < 0.5:
                    cx1 = 0.55  # Top panel: opposite side
                    cx2 = max(0.0, min(1.0 - 0.45, p_x - 0.225))  # Bottom panel: detected speaker
                else:
                    cx1 = max(0.0, min(1.0 - 0.45, p_x - 0.225))  # Top panel: detected speaker
                    cx2 = 0.05  # Bottom panel: opposite side
            else:
                cx1 = 0.55
                cx2 = 0.05

            filters = (
                f"{bg_stream};"
                f"[0:v]crop=w='trunc(iw*0.45/2)*2':h=ih:x='trunc(iw*{cx1:.4f}/2)*2':y=0,scale=1080:920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:920[p1];"
                f"[0:v]crop=w='trunc(iw*0.45/2)*2':h=ih:x='trunc(iw*{cx2:.4f}/2)*2':y=0,scale=1080:920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:920[p2];"
                "[bg][p1]overlay=0:20[tmp1];"
                "[tmp1][p2]overlay=0:980[vcomp];"
                f"[vcomp]null{ass_filter}[vout]"
            )
            return filters

        else:
            zoom_expr = ",crop=w='trunc(iw/1.05/2)*2':h='trunc(ih/1.05/2)*2',scale=1080:608" if energy_zoom else ""
            filters = (
                f"{bg_stream};"
                f"[0:v]scale=1080:608:force_original_aspect_ratio=decrease{zoom_expr}[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[vcomp];"
                f"[vcomp]null{ass_filter}[vout]"
            )
            return filters

    def _render_safe_fallback(
        self,
        raw_video_path: Path,
        output_vertical: Path,
        ass_path: Optional[str],
        background_style: str = "soft_blur",
        background_color: str = "#000000",
    ) -> None:
        """Safe fallback render in case filter complex triggers FFmpeg error."""
        ass_filter = f",{ffmpeg_ass_filter(ass_path)}" if ass_path else ""

        clean_bg_color = background_color.strip()
        if not clean_bg_color.startswith("#"):
            clean_bg_color = "#" + clean_bg_color
        if not re.match(r"^#[0-9a-fA-F]{6}$", clean_bg_color):
            clean_bg_color = "#000000"

        if background_style == "solid_black":
            bg_stream = "color=c=black:s=1080x1920:r=30[bg]"
        elif background_style == "custom_color":
            bg_stream = f"color=c='{clean_bg_color}':s=1080x1920:r=30[bg]"
        elif background_style == "heavy_blur":
            bg_stream = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=45:5[bg]"
        else:
            bg_stream = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:4[bg]"

        fallback_filter = (
            f"{bg_stream};"
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{ass_filter}[v]"
        )
        try:
            from clipify.platform.gpu_manager import get_ffmpeg_video_encoder_flags
            enc_flags = get_ffmpeg_video_encoder_flags(bitrate="12M", preset="fast", crf=16)
        except Exception:
            enc_flags = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "16M", "-pix_fmt", "yuv420p"]

        cmd = [
            self.ffmpeg_bin, "-y",
            "-i", str(raw_video_path),
            "-filter_complex", fallback_filter,
            "-map", "[v]", "-map", "0:a?",
            *enc_flags,
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "192k",
            "-fps_mode", "cfr",
            "-movflags", "+faststart",
            str(output_vertical),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_hidden_flags())
