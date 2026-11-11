from __future__ import annotations

import json
import html
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any


class TTSUnavailable(RuntimeError):
    pass


KOKORO_VOICES = {
    "af_alloy": ("Kokoro Alloy", "Natural Female"), "af_aoede": ("Kokoro Aoede", "Natural Female"),
    "af_bella": ("Kokoro Bella", "Natural Female"), "af_heart": ("Kokoro Heart", "Natural Female"),
    "af_jessica": ("Kokoro Jessica", "Natural Female"), "af_kore": ("Kokoro Kore", "Natural Female"),
    "af_nicole": ("Kokoro Nicole", "Natural Female"), "af_nova": ("Kokoro Nova", "Natural Female"),
    "af_river": ("Kokoro River", "Natural Female"), "af_sarah": ("Kokoro Sarah", "Natural Female"),
    "af_sky": ("Kokoro Sky", "Natural Female"), "am_adam": ("Kokoro Adam", "Natural Male"),
    "am_echo": ("Kokoro Echo", "Natural Male"), "am_eric": ("Kokoro Eric", "Natural Male"),
    "am_fenrir": ("Kokoro Fenrir", "Natural Male"), "am_liam": ("Kokoro Liam", "Natural Male"),
    "am_michael": ("Kokoro Michael", "Natural Male"), "am_onyx": ("Kokoro Onyx", "Natural Male"),
    "am_puck": ("Kokoro Puck", "Natural Male"), "am_santa": ("Kokoro Santa", "Natural Male"),
    "bf_alice": ("Kokoro Alice", "Natural Female"), "bf_emma": ("Kokoro Emma", "Natural Female"),
    "bf_isabella": ("Kokoro Isabella", "Natural Female"), "bf_lily": ("Kokoro Lily", "Natural Female"),
    "bm_daniel": ("Kokoro Daniel", "Natural Male"), "bm_fable": ("Kokoro Fable", "Natural Male"),
    "bm_george": ("Kokoro George", "Natural Male"), "bm_lewis": ("Kokoro Lewis", "Natural Male"),
}
_KOKORO_PIPELINES: dict[str, Any] = {}
_KOKORO_LOCK = threading.Lock()


def sanitize_narration_text(text: str) -> str:
    """Replace invalid lone UTF-16 surrogates while preserving valid Unicode."""
    raw = str(text or "")
    cleaned = []
    index = 0
    while index < len(raw):
        codepoint = ord(raw[index])
        if 0xD800 <= codepoint <= 0xDBFF and index + 1 < len(raw):
            low = ord(raw[index + 1])
            if 0xDC00 <= low <= 0xDFFF:
                cleaned.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)))
                index += 2
                continue
        cleaned.append(" " if 0xD800 <= codepoint <= 0xDFFF else raw[index])
        index += 1
    return "".join(cleaned)


def strip_script_metadata(text: str) -> str:
    """Strip prompt/structural metadata headers, stage directions, and markdown prefixes from narration script.

    Strips:
    - Pure metadata lines (Concept:, Topic:, Instructions:, Notes:, Scene description:, Title:, etc.)
    - Speaker/structure prefixes from dialogue lines (Hook:, Narrator:, Voiceover:, Host:, etc.)
    - Markdown headings (# Concept, ## Hook)
    - Bold/italic wrappers around headers (**Hook:**, *Scene:*)
    - Bracketed or parenthetical stage directions ([Music fades in], (laughter), [applause])
    - Markdown formatting artifacts like **, *, _, `
    Preserves:
    - Natural dialogue and sentences containing those words within the body of a phrase.
    """
    if not text:
        return ""
    lines = text.splitlines()
    cleaned_lines = []

    # Pure metadata lines that should be dropped entirely
    metadata_line_pattern = re.compile(
        r"^(?:[\s*#_>-]*)"
        r"(?:concept|topic|instructions?|notes?|scene(?:\s+description)?|description|title|background(?:\s+music|\s+video)?|audio(?:\s+cues?)?)"
        r"(?:\s*\(.*?\))?"
        r"(?:[\s*_]*:[\s*_]*|\s*[-–—]\s*)",
        re.IGNORECASE,
    )

    # Speaker/section prefixes where we only strip the prefix and keep the spoken text
    spoken_prefix_pattern = re.compile(
        r"^(?:[\s*#_>-]*)"
        r"(?:hook|filler|voice[- ]?over|narrator|host|speaker(?:\s*\d+)?|intro|outro)"
        r"(?:\s*\(.*?\))?"
        r"(?:[\s*_]*:[\s*_]*|\s*[-–—]\s*)",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue

        # Drop standalone stage directions: [Music fades in] or (laughter)
        if re.match(r"^\[[^\]]+\]$", stripped) or re.match(r"^\([^)]+\)$", stripped):
            continue

        # Check for pure metadata line e.g. Concept: Animals in the wild
        if metadata_line_pattern.match(stripped):
            continue

        # Strip markdown header hashes (# Hook, ## Intro)
        if re.match(r"^#{1,6}\s+", stripped):
            remainder = re.sub(r"^#{1,6}\s+", "", stripped).strip()
            if metadata_line_pattern.match(remainder + ":") or spoken_prefix_pattern.match(remainder + ":"):
                continue
            stripped = remainder

        # Strip spoken prefix e.g. **Hook:** Once upon a time... -> Once upon a time...
        prev = None
        while prev != stripped:
            prev = stripped
            stripped = spoken_prefix_pattern.sub("", stripped).strip()

        if not stripped:
            continue

        # Strip inline stage directions like [laughter], [Music], (sighs)
        stripped = re.sub(r"\[(?:music|sound|laughter|applause|cheering|pause|beat|giggles|fades?)[^\]]*\]", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\((?:music|sound|laughter|applause|cheering|pause|beat|giggles|sighs|fades?)[^)]*\)", "", stripped, flags=re.IGNORECASE)

        # Strip bold/italic markdown characters from prose (**word** -> word)
        stripped = re.sub(r"\*\*([^*]+)\*\*", r"\1", stripped)
        stripped = re.sub(r"\*([^*]+)\*", r"\1", stripped)
        stripped = re.sub(r"__([^_]+)__", r"\1", stripped)
        stripped = re.sub(r"_([^_]+)_", r"\1", stripped)
        stripped = re.sub(r"`([^`]+)`", r"\1", stripped)

        stripped = re.sub(r"[ \t]+", " ", stripped).strip()
        if stripped:
            cleaned_lines.append(stripped)

    result = "\n".join(cleaned_lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


def _kokoro_installed() -> bool:
    """Can Kokoro be run at all: here in-process, or in the Tier-B runtime?

    The shipped app is a Tier A binary and never imports kokoro itself, so
    checking only the current interpreter reported every Kokoro voice as
    unavailable in the installed product.
    """
    if importlib.util.find_spec("kokoro") is not None:
        return True
    return _kokoro_in_runtime()


def _normalize_script(text: str) -> str:
    """Normalize layout without removing paragraph pauses from the script."""
    text = strip_script_metadata(sanitize_narration_text(text))
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n+", text):
        clean = re.sub(r"[ \t\r\f\v]+", " ", paragraph).strip()
        # Speech engines often spell out all-caps names letter by letter.
        clean = re.sub(
            r"\b[A-Z][A-Z'-]{1,}\b",
            lambda match: match.group(0).title(),
            clean,
        )
        if clean:
            paragraphs.append(clean)
    return "\n\n".join(paragraphs)


def _powershell() -> str:
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe") or "powershell.exe"


def _run(script: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TTSUnavailable(f"Windows speech engine could not start: {exc}") from exc
    if result.returncode:
        raise TTSUnavailable((result.stderr or result.stdout or "Windows speech engine failed.").strip())
    return result.stdout.strip()


def _voice_category(name: str, gender: str | None = None) -> str:
    lower = (name or "").lower()
    if gender:
        g = gender.lower()
        if "female" in g:
            return "Natural Female"
        if "male" in g:
            return "Natural Male"
    keywords = {
        "natural female": "Natural Female",
        "natural male": "Natural Male",
        "female": "Natural Female",
        "male": "Natural Male",
        "storyteller": "Storyteller",
        "documentary": "Documentary",
        "dramatic": "Dramatic",
        "cartoon": "Cartoon-style",
        "villain": "Villain",
        "robot": "Robot",
        "elder": "Elderly",
        "gaming": "Gaming",
        "meme": "Meme",
        "comic": "Comedic",
        "calm": "Calm",
        "energetic": "Energetic",
        "deep": "Deep",
    }
    for keyword, category in keywords.items():
        if keyword in lower:
            return category
    return "Standard"


def available_voices() -> list[dict[str, Any]]:
    voices_by_id: dict[str, dict[str, Any]] = {}
    if _kokoro_installed():
        for voice_id, (label, category) in KOKORO_VOICES.items():
            voices_by_id[voice_id] = {
                "id": voice_id,
                "name": label,
                "category": category,
                "engine": "Kokoro 82M",
                "language": "English",
                "gender": "Female" if "Female" in category else "Male",
                "description": "Local Kokoro neural voice.",
                "preview": True,
                "speed": True,
            }

    script = """
Add-Type -AssemblyName System.Speech
$items = [System.Speech.Synthesis.SpeechSynthesizer]::new().GetInstalledVoices() |
  ForEach-Object { $v=$_.VoiceInfo; [pscustomobject]@{id=$v.Name; name=$v.Name; language=$v.Culture.Name; gender=$v.Gender.ToString(); age=$v.Age.ToString()} }
$items | ConvertTo-Json -Compress
"""
    try:
        raw = _run(script)
        if not raw:
            return sorted(voices_by_id.values(), key=lambda item: item["name"].lower())
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        for item in data if isinstance(data, list) else []:
            name = str(item.get("name", "") or item.get("id", "")).strip()
            if not name:
                continue
            category = _voice_category(name, str(item.get("gender") or ""))
            voice = {
                "id": name,
                "name": name,
                "category": category,
                "engine": "Windows SAPI",
                "language": str(item.get("language", "en-US")),
                "gender": str(item.get("gender", "Unknown")),
                "description": f"Installed local {category.lower()} voice.",
                "preview": True,
                "speed": True,
            }
            voices_by_id.setdefault(name, voice)
    except (json.JSONDecodeError, TTSUnavailable):
        pass
    return sorted(voices_by_id.values(), key=lambda item: (item["engine"], item["name"].lower()))


def _kokoro_pipeline(lang_code: str):
    with _KOKORO_LOCK:
        pipeline = _KOKORO_PIPELINES.get(lang_code)
        if pipeline is None:
            try:
                from kokoro import KPipeline
                pipeline = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
            except Exception as exc:
                raise TTSUnavailable(f"Kokoro could not initialize: {exc}") from exc
            _KOKORO_PIPELINES[lang_code] = pipeline
        return pipeline


def _kokoro_in_runtime() -> bool:
    """Is a Tier-B runtime venv available to run Kokoro in a child process?

    The shipped app is a Tier A binary: torch, kokoro, soundfile and jinja2 are
    deliberately left out of it and live in the runtime venv beside it. Importing
    Kokoro in-process therefore always fails in the installed product, which used
    to surface to the user as "Kokoro could not initialize: No module named
    'jinja2.sandbox'" and blocked every narrated Short.
    """
    try:
        from clippedai_runtime import runtime_python
    except Exception:
        return False
    try:
        python = runtime_python()
    except Exception:
        return False
    return bool(python) and Path(python).exists()


#: Worker executed by the runtime venv. Kept as plain source with no imports from
#: this module so it can run standalone under the child's interpreter.
_KOKORO_WORKER = r'''
import json, sys
import numpy as np
import soundfile as sf
from kokoro import KPipeline

payload = json.loads(sys.stdin.read())
lang = "a" if payload["voice"].startswith("a") else "b"
pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
chunks = []
for _, _, audio in pipeline(payload["text"], voice=payload["voice"], speed=payload["speed"]):
    chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
if not chunks:
    raise SystemExit("Kokoro returned no audio.")
sf.write(payload["out"], np.concatenate(chunks), 24000)
print("ok")
'''


def _generate_via_runtime(voice: str, text: str, speed: float, target: Path) -> Path:
    """Synthesize with the runtime venv in a child process."""
    from clippedai_runtime import runtime_python

    python = runtime_python()
    if not python or not Path(python).exists():
        raise TTSUnavailable(
            "Narration needs the AI runtime. Re-run the installer with the "
            '"AI runtime" option enabled, or pick a Windows voice.'
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    text = sanitize_narration_text(text)
    payload = json.dumps(
        {"text": text, "voice": voice, "speed": speed, "out": str(target)},
        ensure_ascii=False,
    )
    try:
        result = subprocess.run(
            [str(python), "-c", _KOKORO_WORKER],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TTSUnavailable(f"Narration could not start: {exc}") from exc
    if result.returncode or not target.exists() or target.stat().st_size < 1024:
        detail = (result.stderr or result.stdout or "").strip()
        tail = detail[-400:] if detail else f"exit code {result.returncode}"
        raise TTSUnavailable(f"Kokoro synthesis failed in the AI runtime: {tail}")
    return target


class KokoroTTS:
    def __init__(self, voice: str, rate: int = 0):
        if voice not in KOKORO_VOICES:
            raise TTSUnavailable("That Kokoro voice is not available.")
        self.voice = voice
        self.rate = max(-10, min(10, int(rate)))

    def generate(self, text: str, output_path: str | Path) -> Path:
        clean = _normalize_script(text)
        if not clean:
            raise ValueError("Enter a script before generating narration.")
        speech_speed = max(0.82, min(1.08, 1.0 + self.rate * 0.04))
        try:
            import numpy as np
            import soundfile as sf
            pipeline = _kokoro_pipeline("a" if self.voice.startswith("a") else "b")
            chunks = []
            # Keep the natural setting close to Kokoro's normal pace while
            # retaining distinct slower and faster UI controls.
            for _, _, audio in pipeline(clean, voice=self.voice, speed=speech_speed):
                chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
            if not chunks:
                raise TTSUnavailable("Kokoro returned no audio.")
            target = Path(output_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(target), np.concatenate(chunks), 24000)
            if not target.exists() or target.stat().st_size < 1024:
                raise TTSUnavailable("Kokoro returned no usable audio.")
            return target
        except ImportError:
            # Tier B is not inside this binary; hand the job to the runtime venv.
            return _generate_via_runtime(self.voice, clean, speech_speed, Path(output_path).resolve())
        except TTSUnavailable as exc:
            # A missing module reported through TTSUnavailable (the wrapper catches
            # every Exception around the pipeline) is still the same situation.
            if "No module named" not in str(exc) and "could not initialize" not in str(exc):
                raise
            return _generate_via_runtime(self.voice, clean, speech_speed, Path(output_path).resolve())
        except Exception as exc:
            raise TTSUnavailable(f"Kokoro synthesis failed: {exc}") from exc

    def preview(self, output_dir: str | Path) -> Path:
        target = Path(output_dir) / f"preview_kokoro_{self.voice}_v2.wav"
        if target.exists() and target.stat().st_size >= 1024:
            return target
        return self.generate(f"This is a preview of the {KOKORO_VOICES[self.voice][0]} voice.", target)


def create_tts(voice: str, rate: int = 0):
    if voice in KOKORO_VOICES:
        if not _kokoro_installed():
            raise TTSUnavailable(
                "Narration needs the AI runtime. Re-run the installer with the "
                '"AI runtime" option enabled, or select a Windows voice.'
            )
        return KokoroTTS(voice, rate)
    return SapiTTS(voice, rate)


class SapiTTS:
    def __init__(self, voice: str, rate: int = 0):
        installed = {item["id"] for item in available_voices()}
        if voice not in installed:
            raise TTSUnavailable("That voice is not installed on this computer.")
        self.voice = voice
        self.rate = max(-10, min(10, int(rate)))

    def generate(self, text: str, output_path: str | Path) -> Path:
        clean = _normalize_script(text)
        if not clean:
            raise ValueError("Enter a script before generating narration.")
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        ssml = html.escape(clean, quote=False)
        ssml = ssml.replace("\n\n", '<break time="350ms"/>')
        ssml = re.sub(r"([,;:])", r'\1<break time="90ms"/>', ssml)
        ssml = re.sub(r"([.!?])", r'\1<break time="220ms"/>', ssml)
        escaped_ssml = ssml.replace("'", "''")
        escaped_path = str(target).replace("'", "''")
        escaped_voice = self.voice.replace("'", "''")
        script = f"""
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$s.SelectVoice('{escaped_voice}')
$s.Rate = {self.rate}
$s.SetOutputToWaveFile('{escaped_path}')
    $s.SpeakSsml('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{escaped_ssml}</speak>')
$s.Dispose()
"""
        _run(script, timeout=max(60, min(900, len(clean) // 2 + 60)))
        if not target.exists() or target.stat().st_size < 1024:
            raise TTSUnavailable("The speech engine returned no usable audio.")
        return target

    def preview(self, output_dir: str | Path) -> Path:
        target = Path(output_dir) / f"preview_{abs(hash(self.voice))}.wav"
        return self.generate(f"This is a preview of the {self.voice} voice.", target)
