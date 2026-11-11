from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from narrate.pipeline import NarratePipeline
from narrate.tts import KokoroTTS, sanitize_narration_text


class _FakeTTS:
    def __init__(self, audio: Path):
        self.audio = audio
        self.received = None

    def generate(self, script: str, output: Path) -> Path:
        self.received = script
        output.write_bytes(self.audio.read_bytes())
        return output


class NarrationUnicodeTests(unittest.TestCase):
    def test_repairs_lone_surrogates_and_preserves_unicode(self):
        lone = chr(0xDC9D)
        emoji = chr(0x1F600)
        paired_emoji = chr(0xD83D) + chr(0xDE80)
        script = "Cafe" + lone + "story. Caf" + chr(0xE9) + " " + emoji + " " + paired_emoji
        expected = "Cafe story. Caf" + chr(0xE9) + " " + emoji + " " + chr(0x1F680)
        self.assertEqual(sanitize_narration_text(script), expected)

    def test_kokoro_runtime_fallback_receives_clean_text(self):
        lone = chr(0xDC9D)
        target = Path("narration.wav")
        with patch("narrate.tts._kokoro_pipeline", side_effect=ImportError("use runtime")), \
             patch("narrate.tts._generate_via_runtime", return_value=target) as runtime:
            result = KokoroTTS("am_adam").generate("Cafe" + lone + "story", target)
        self.assertEqual(result, target)
        self.assertEqual(runtime.call_args.args[1], "Cafe story")

    def test_render_sanitizes_audio_captions_and_saved_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = root / "narrate clips"
            library.mkdir()
            background = library / "background.mp4"
            background.write_bytes(b"fixture")
            source_audio = root / "source.wav"
            with wave.open(str(source_audio), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(100)
                wav.writeframes(bytes(400))

            fake_tts = _FakeTTS(source_audio)
            pipeline = NarratePipeline(root)
            output_dir = root / "output"
            lone = chr(0xDC9D)
            accent = chr(0xE9)
            emoji = chr(0x1F600)
            bad_script = "The caf" + lone + "story. Caf" + accent + " " + emoji
            sanitized = "The caf story. Caf" + accent + " " + emoji

            def fake_run(command, **_kwargs):
                if Path(command[0]).name.lower() == "ffmpeg.exe":
                    Path(command[-1]).write_bytes(b"x" * 2048)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "streams": [{"codec_type": "audio", "duration": "2.0"}]
                }), stderr="")

            with patch("narrate.pipeline.create_tts", return_value=fake_tts), \
                 patch.object(pipeline, "_probe", return_value={
                     "duration": 8.0, "width": 1920, "height": 1080
                 }), \
                 patch("narrate.pipeline.subprocess.run", side_effect=fake_run):
                pipeline.render(output_dir, bad_script, "am_adam", background.name)

            self.assertEqual(fake_tts.received, sanitized)
            metadata = json.loads((output_dir / "narrated_short.json").read_text(encoding="utf-8"))
            captions = (output_dir / "narration.ass").read_text(encoding="utf-8-sig")
            self.assertEqual(metadata["script"], sanitized)
            self.assertIn(accent, captions)
            self.assertIn(emoji, captions)
            for value in (fake_tts.received, metadata["script"], captions):
                self.assertFalse(any(0xD800 <= ord(char) <= 0xDFFF for char in value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
