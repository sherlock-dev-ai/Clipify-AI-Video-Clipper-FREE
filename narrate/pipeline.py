from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable

from .tts import create_tts, sanitize_narration_text, strip_script_metadata

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

#: Environment override holding one or more clip-library folders, separated by
#: the platform path separator (or a semicolon, which always works on Windows).
CLIPS_ENV = "CLIPPEDAI_NARRATE_CLIPS"

#: Where a persisted, user-chosen library folder is recorded.
LIBRARY_FILE = "narrate-library.txt"


class NarratePipeline:
    """Locates and renders Narrate background clips.

    The library is *not* bundled with the product: an installed copy has no
    ``narrate clips`` folder at all, because shipping a user's footage is not
    an installer's job. The folder used to be looked up only next to the
    executable, so an installed user always saw "No Narrate clips found" even
    with a perfectly good library sitting somewhere else on the disk.

    Folders are therefore resolved from several places, in order:
      1. ``CLIPPEDAI_NARRATE_CLIPS`` (explicit override)
      2. the folder the user picked in the UI, remembered in the data dir
      3. the user data dir's own ``narrate clips`` / ``big narrate clips``
      4. the same two folders beside the executable (the dev-checkout layout)
    """

    def __init__(self, root: str | Path, data_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        self.data_dir = Path(data_dir).resolve() if data_dir else self.root
        # ffmpeg still ships beside the executable, so those paths stay put.
        self.ffmpeg = self.root / "tools" / "ffmpeg" / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffmpeg.exe"
        self.ffprobe = self.root / "tools" / "ffmpeg" / "ffmpeg-9.0.1-essentials_build" / "bin" / "ffprobe.exe"
        self._probe_cache: dict[tuple[str, int, float], dict[str, Any]] = {}

    # ------------------------------------------------------------- library

    @property
    def library_file(self) -> Path:
        return self.data_dir / LIBRARY_FILE

    @property
    def extra_clips_file(self) -> Path:
        return self.data_dir / "extra-clips-enabled.txt"

    def extra_clips_folder(self) -> Path | None:
        for base in (self.root, self.data_dir):
            candidate = base / "narrate download"
            if candidate.is_dir():
                return candidate
        return None

    def has_extra_clips(self) -> bool:
        return self.extra_clips_folder() is not None

    def extra_clips_count(self) -> int:
        folder = self.extra_clips_folder()
        if not folder:
            return 0
        try:
            return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
        except OSError:
            return 0

    def extra_clips_enabled(self) -> bool:
        return self.extra_clips_file.is_file()

    def set_extra_clips_enabled(self, enable: bool) -> bool:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if enable:
                self.extra_clips_file.write_text("enabled", encoding="utf-8")
            else:
                if self.extra_clips_file.is_file():
                    self.extra_clips_file.unlink()
        except OSError:
            pass
        return self.extra_clips_enabled()

    def _remembered_library(self) -> Path | None:
        try:
            raw = self.library_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_dir() else None

    def remember_library(self, folder: str | Path) -> Path:
        """Persist a user-chosen clip library folder and return it resolved."""
        path = Path(folder).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.library_file.write_text(str(path), encoding="utf-8")
        except OSError:
            # A read-only data dir must not stop the folder being used now.
            pass
        return path

    def _env_libraries(self) -> list[Path]:
        raw = os.environ.get(CLIPS_ENV, "").strip()
        if not raw:
            return []
        parts = [p for chunk in raw.split(os.pathsep) for p in chunk.split(";")]
        found = []
        for part in parts:
            part = part.strip().strip('"')
            if not part:
                continue
            try:
                path = Path(part).expanduser()
            except (OSError, ValueError):
                continue
            if path.is_dir():
                found.append(path)
        return found

    def library_folders(self) -> list[Path]:
        """Every folder that may hold clips, in priority order, de-duplicated."""
        candidates: list[Path] = []
        candidates.extend(self._env_libraries())
        remembered = self._remembered_library()
        if remembered:
            candidates.append(remembered)
        for base in (self.data_dir, self.root):
            candidates.append(base / "narrate clips")
            candidates.append(base / "big narrate clips")
            if self.extra_clips_enabled():
                candidates.append(base / "narrate download")

        seen: set[str] = set()
        unique: list[Path] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            key = str(resolved).lower()
            if key in seen or not resolved.is_dir():
                continue
            seen.add(key)
            unique.append(resolved)
        return unique

    def default_library(self) -> Path:
        """The folder offered to the user and created on demand."""
        remembered = self._remembered_library()
        if remembered:
            return remembered
        return self.data_dir / "narrate clips"

    def reset_library(self) -> Path:
        """Forget a user-chosen folder and fall back to the default location.

        ``ensure_library`` alone cannot do this: it resolves through
        ``default_library``, which still prefers the remembered folder, so an
        empty "change folder" request kept returning the old choice forever.
        """
        try:
            self.library_file.unlink()
        except OSError:
            pass
        return self.ensure_library()

    def has_custom_library(self) -> bool:
        """True when the user has pointed the library somewhere of their own."""
        return self._remembered_library() is not None

    def ensure_library(self) -> Path:
        """Make sure a library folder exists, so the UI is never a dead end."""
        target = self.default_library()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return target

    def library_label(self) -> str:
        folders = self.library_folders()
        return str(folders[0]) if folders else str(self.default_library())

    # ------------------------------------------------------------- scanning

    def scan_videos(self) -> list[dict[str, Any]]:
        result = []
        standard = self.default_library()
        for path in self._video_paths():
            info = self._probe(path)
            generated = self._is_generated_clip(path)
            try:
                same = path.parent.resolve() == standard.resolve()
            except OSError:
                same = False
            metadata = self._clip_metadata(path) if generated else {}
            label = str(metadata.get("title") or path.stem.replace("_", " ")).strip()
            result.append({"id": self.video_id(path), "name": label, "filename": path.name,
                           "duration": info["duration"], "duration_label": self._duration_label(info["duration"]),
                           "width": info["width"], "height": info["height"], "size": path.stat().st_size,
                           "library": "generated" if generated else "standard" if same else "extra",
                           "generated": generated,
                           "folder": str(path.parent)})
        return result

    @staticmethod
    def video_id(path: str | Path) -> str:
        """Return a stable opaque identity that remains unique across folders."""
        canonical = str(Path(path).resolve()).casefold().encode("utf-8", errors="surrogatepass")
        return "clip-" + hashlib.sha256(canonical).hexdigest()[:24]

    @staticmethod
    def _clip_metadata(path: Path) -> dict[str, Any]:
        stem = re.sub(r"_edited(?:_\d+)?$", "", path.stem, flags=re.IGNORECASE)
        metadata_path = path.with_name(stem + ".json")
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _is_generated_clip(path: Path) -> bool:
        return path.parent.name.lower() == "output" and path.parent.parent.parent.name.lower() == "jobs"

    def _generated_video_paths(self) -> list[Path]:
        jobs_dir = self.data_dir / "jobs"
        if not jobs_dir.is_dir():
            return []
        found: list[Path] = []
        try:
            job_dirs = sorted(jobs_dir.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return []
        for job_dir in job_dirs:
            output_dir = job_dir / "output"
            if not output_dir.is_dir():
                continue
            try:
                entries = sorted(output_dir.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for path in entries:
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                # The clipping pipeline writes short_XX.mp4 only for finished
                # exports. Its JSON or text sidecar distinguishes those from
                # partial renders and unrelated media in the shared jobs tree.
                if not re.fullmatch(r"short_\d+(?:_edited(?:_\d+)?)?", path.stem, re.IGNORECASE):
                    continue
                try:
                    if path.stat().st_size < 1024:
                        continue
                except OSError:
                    continue
                metadata_stem = re.sub(r"_edited(?:_\d+)?$", "", path.stem, flags=re.IGNORECASE)
                # A valid export can have either sidecar: the JSON used by the
                # UI or the text summary written by the worker.
                json_exists = (output_dir / f"{metadata_stem}.json").is_file()
                text_exists = (output_dir / f"{metadata_stem}.txt").is_file()
                if not json_exists and not text_exists:
                    continue
                found.append(path)
        return found

    def _video_paths(self) -> list[Path]:
        found: list[tuple[int, str, Path]] = []
        seen: set[str] = set()
        for index, folder in enumerate(self.library_folders()):
            try:
                entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for path in entries:
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append((index, path.name.lower(), path))
        generated_index = len(self.library_folders())
        for path in self._generated_video_paths():
            try:
                key = str(path.resolve()).casefold()
            except OSError:
                key = str(path).casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append((generated_index, str(path).casefold(), path))
        # Library order first, then by name, so the primary folder reads first.
        found.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in found]

    def _find_video(self, filename: str) -> Path | None:
        requested = str(filename or "").strip()
        paths = self._video_paths()
        if re.fullmatch(r"clip-[0-9a-f]{24}", requested, re.IGNORECASE):
            return next((path for path in paths if self.video_id(path) == requested.lower()), None)
        # Backward compatibility for older clients is deliberately limited to
        # unique basenames. A duplicated short_01.mp4 must never resolve to a
        # different project just because it appeared first in a folder scan.
        basename = Path(requested).name
        matches = [path for path in paths if path.name == basename]
        return matches[0] if len(matches) == 1 else None

    def _probe(self, path: Path) -> dict[str, Any]:
        try:
            st = path.stat()
            cache_key = (str(path.resolve()).lower(), st.st_size, st.st_mtime)
            if hasattr(self, "_probe_cache") and cache_key in self._probe_cache:
                return self._probe_cache[cache_key]
        except OSError:
            cache_key = None

        try:
            proc = subprocess.run([str(self.ffprobe), "-v", "error", "-show_entries", "format=duration:stream=width,height",
                                   "-of", "json", str(path)], capture_output=True, text=True, check=True)
            data = json.loads(proc.stdout)
            video = next((s for s in data.get("streams", []) if s.get("width") and s.get("height")), {})
            res = {"duration": float(data.get("format", {}).get("duration") or 0), "width": int(video.get("width") or 0), "height": int(video.get("height") or 0)}
            if cache_key and hasattr(self, "_probe_cache"):
                self._probe_cache[cache_key] = res
            return res
        except (OSError, subprocess.CalledProcessError, ValueError, StopIteration):
            return {"duration": 0.0, "width": 0, "height": 0}

    @staticmethod
    def _duration_label(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        return f"{total // 60:02d}:{total % 60:02d}"

    def render(self, job_dir: str | Path, script: str, voice: str, video_name: str, speed: int = 0,
               caption_mode: str = "sync-yellow", caption_size: int = 96,
               target_duration: float | None = None,
               progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        script = strip_script_metadata(sanitize_narration_text(script))

        def step(value: int, label: str) -> None:
            if progress:
                progress(value, label)
        if not script.strip():
            raise ValueError("Enter a script before generating narration.")
        source = self._find_video(video_name)
        if source is None:
            raise ValueError("Choose a valid Narrate background clip.")
        out_dir = Path(job_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        step(10, "Preparing script")
        audio = create_tts(voice, speed).generate(script, out_dir / "narration.wav")
        step(35, "Generating voice")
        with wave.open(str(audio), "rb") as wav:
            duration = wav.getnframes() / float(wav.getframerate())
        if duration <= 0:
            raise ValueError("Narration audio has no duration.")
        step(45, "Measuring narration")
        output = out_dir / "narrated_short.mp4"
        caption_size = max(64, min(120, int(caption_size)))
        # The selected AI length guides script generation, but never pads the
        # finished video with silent background after the actual narration.
        seconds = duration
        tempo = 1.0
        words = script.strip().split()
        subtitle_file = out_dir / "narration.ass"
        speech_seconds = min(seconds, duration)
        weights = []
        pause_weights = []
        for word in words:
            weight = 1.0
            weight += min(1.4, len(re.sub(r"[^A-Za-z0-9']", "", word)) / 12)
            pause = 0.0
            if re.search(r"[,;:]$", word):
                pause = 0.16
            if re.search(r"[.!?]$", word):
                pause = 0.48
            weights.append(weight)
            pause_weights.append(pause)
        pause_total = min(speech_seconds * 0.3, sum(pause_weights))
        pause_scale = pause_total / sum(pause_weights) if sum(pause_weights) else 0.0
        word_budget = max(0.1, speech_seconds - pause_total)
        total_weight = sum(weights) or 1.0
        word_starts = []
        word_ends = []
        elapsed = 0.0
        for weight, pause in zip(weights, pause_weights):
            word_starts.append(elapsed)
            word_duration = word_budget * weight / total_weight
            elapsed += word_duration + pause * pause_scale
            word_ends.append(elapsed)

        def ass_time(value: float) -> str:
            total = max(0, int(round(value * 100)))
            hours, rest = divmod(total, 360000)
            minutes, rest = divmod(rest, 6000)
            secs, centis = divmod(rest, 100)
            return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

        def ass_text(value: str) -> str:
            return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

        with subtitle_file.open("w", encoding="utf-8-sig") as handle:
            handle.write(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
                "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                f"Style: Narrate,Montserrat Extra Bold,{caption_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,70,70,0,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            )
            groups = []
            group_start = 0
            for word_index, word in enumerate(words):
                group_size = word_index - group_start + 1
                ends_sentence = bool(re.search(r"[.!?]$", word))
                if ends_sentence or group_size >= 4:
                    groups.append((group_start, words[group_start:word_index + 1]))
                    group_start = word_index + 1
            if group_start < len(words):
                groups.append((group_start, words[group_start:]))

            for start_index, group in groups:
                group_end = min(speech_seconds, word_ends[start_index + len(group) - 1])
                for active_index, word in enumerate(group):
                    word_index = start_index + active_index
                    start = word_starts[word_index]
                    end = min(group_end, word_ends[word_index])
                    important = {index for index, item in enumerate(words)
                                 if len(re.sub(r"[^A-Za-z0-9']", "", item)) >= 7 or
                                 (index > 0 and re.sub(r"[^A-Za-z0-9']", "", item).lower() in {"but", "now", "never", "always", "only", "because"})}
                    def word_color(index: int) -> str:
                        if caption_mode == "sync-yellow":
                            return "&H00FFFF&" if index == word_index else "&H00FFFFFF&"
                        if caption_mode == "color-words" and index in important:
                            return ("&H00FFFF&", "&H00FF00&", "&H0000FF&")[index % 3]
                        if index not in important:
                            return "&H00FFFFFF&"
                        return "&H00FFFF&"
                    caption = " ".join(
                        "{\\c" + word_color(word_index) + "}" + ass_text(item) + "{\\rNarrate}"
                        for index, item in enumerate(group)
                        for word_index in [start_index + index]
                    )
                    handle.write(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Narrate,,0,0,0,,{caption}\n")
        clip_sources = [source]
        clip_duration = self._probe(source)["duration"]
        available_clips = [path for path in self._video_paths() if path != source and self._probe(path)["duration"] > 0]
        if clip_duration <= 0:
            raise ValueError("Selected background clip has no readable duration.")
        total_clip_duration = clip_duration
        while total_clip_duration < seconds and available_clips:
            next_clip = available_clips.pop(0)
            clip_sources.append(next_clip)
            total_clip_duration += self._probe(next_clip)["duration"]
        while total_clip_duration < seconds:
            clip_sources.append(source)
            total_clip_duration += clip_duration

        subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        video_inputs = []
        video_filters = []
        for index, clip_path in enumerate(clip_sources):
            video_inputs.extend(["-i", str(clip_path)])
            video_filters.append(
                f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
                f"trim=duration={max(0.1, self._probe(clip_path)['duration']):.3f},setpts=PTS-STARTPTS[v{index}]"
            )
        concat_inputs = "".join(f"[v{index}]" for index in range(len(clip_sources)))
        filter_complex = (
            ";".join(video_filters) + ";"
            f"{concat_inputs}concat=n={len(clip_sources)}:v=1:a=0,trim=duration={seconds:.3f},setpts=PTS-STARTPTS,"
            f"subtitles='{subtitle_path}'[vout];"
            f"[{len(clip_sources)}:a]atempo={tempo:.6f},aresample=async=1:first_pts=0,atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        command = [str(self.ffmpeg), "-y", *video_inputs, "-i", str(audio),
                   "-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]", "-t", f"{seconds:.3f}",
                   "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)]
        step(60, "Building vertical composition")
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0 or not output.exists() or output.stat().st_size < 1024:
            raise RuntimeError(f"Narrate render failed: {(proc.stderr or proc.stdout)[-1800:]}")
        probe = subprocess.run(
            [str(self.ffprobe), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type,duration", "-of", "json", str(output)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        try:
            audio_streams = json.loads(probe.stdout).get("streams", [])
        except (TypeError, ValueError):
            audio_streams = []
        if not audio_streams:
            raise RuntimeError("Narrate render completed without an audio stream.")
        step(92, "Validating final video")
        title_words = script.strip().replace("\n", " ").split()
        title = " ".join(title_words[:9]).rstrip(".,!?…") or "Your Narrated Short"
        if len(title_words) > 9:
            title += "..."
        metadata = {"title": title, "description": script.strip(), "voice": voice, "background": source.name,
                "duration": round(seconds, 3), "source_voice_duration": round(duration, 3),
                "resolution": "1080x1920", "script": script}
        (out_dir / "narrated_short.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "project.json").write_text(json.dumps({"name": title, "type": "narrate", "voice": voice, "background": source.name}, ensure_ascii=False, indent=2), encoding="utf-8")
        step(100, "Complete")
        return {"filename": output.name, "duration": seconds, "metadata": metadata}

    @staticmethod
    def _srt_time(seconds: float) -> str:
        total_ms = max(0, int(seconds * 1000))
        hours, rest = divmod(total_ms, 3600000)
        minutes, rest = divmod(rest, 60000)
        secs, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
