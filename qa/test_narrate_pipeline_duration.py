from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from narrate.pipeline import NarratePipeline


class _FakeTTS:
    def __init__(self, source_audio: Path):
        self.source_audio = source_audio

    def generate(self, _script: str, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.source_audio.read_bytes())
        return output


class NarratePipelineDurationTests(unittest.TestCase):
    def test_render_duration_matches_speech_without_silent_tail(self):
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
                wav.writeframes(b"\0\0" * 200)

            pipeline = NarratePipeline(root)
            output_dir = root / "output"
            ffmpeg_command: list[str] = []

            def fake_run(command, **_kwargs):
                nonlocal ffmpeg_command
                if Path(command[0]).name.lower() == "ffmpeg.exe":
                    ffmpeg_command = list(command)
                    Path(command[-1]).write_bytes(b"x" * 2048)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"streams": [{"codec_type": "audio", "duration": "2.0"}]}),
                    stderr="",
                )

            with patch("narrate.pipeline.create_tts", return_value=_FakeTTS(source_audio)), \
                    patch.object(pipeline, "_probe", return_value={"duration": 8.0, "width": 1920, "height": 1080}), \
                    patch("narrate.pipeline.subprocess.run", side_effect=fake_run):
                result = pipeline.render(
                    output_dir,
                    "A short narration script ends here.",
                    "am_adam",
                    background.name,
                )

            self.assertEqual(result["duration"], 2.0)
            self.assertEqual(result["metadata"]["duration"], 2.0)
            time_index = ffmpeg_command.index("-t")
            self.assertEqual(ffmpeg_command[time_index + 1], "2.000")
            filter_complex = ffmpeg_command[ffmpeg_command.index("-filter_complex") + 1]
            self.assertIn("trim=duration=2.000", filter_complex)
            self.assertIn("atrim=duration=2.000", filter_complex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
