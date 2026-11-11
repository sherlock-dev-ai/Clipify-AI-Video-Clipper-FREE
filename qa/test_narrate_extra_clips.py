from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from narrate.pipeline import NarratePipeline


class NarrateExtraClipsTests(unittest.TestCase):
    def test_extra_clips_detection_and_toggle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_library = root / "narrate clips"
            base_library.mkdir()
            (base_library / "clip1.mp4").write_bytes(b"test1")
            (base_library / "clip2.mp4").write_bytes(b"test2")

            extra_library = root / "narrate download"
            extra_library.mkdir()
            (extra_library / "extra1.mp4").write_bytes(b"extra1")
            (extra_library / "extra2.mp4").write_bytes(b"extra2")
            (extra_library / "extra3.mp4").write_bytes(b"extra3")

            pipeline = NarratePipeline(root)
            self.assertTrue(pipeline.has_extra_clips())
            self.assertEqual(pipeline.extra_clips_count(), 3)
            self.assertFalse(pipeline.extra_clips_enabled())

            with patch.object(pipeline, "_probe", return_value={"duration": 10.0, "width": 1080, "height": 1920}):
                # When extra clips disabled: only base clips
                initial_clips = pipeline.scan_videos()
                self.assertEqual(len(initial_clips), 2)
                for clip in initial_clips:
                    self.assertEqual(clip["library"], "standard")

                # Enable extra clips
                pipeline.set_extra_clips_enabled(True)
                self.assertTrue(pipeline.extra_clips_enabled())

                expanded_clips = pipeline.scan_videos()
                self.assertEqual(len(expanded_clips), 5)
                extra_found = [c for c in expanded_clips if c["library"] == "extra"]
                self.assertEqual(len(extra_found), 3)

                # Disable extra clips
                pipeline.set_extra_clips_enabled(False)
                self.assertFalse(pipeline.extra_clips_enabled())
                restored_clips = pipeline.scan_videos()
                self.assertEqual(len(restored_clips), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

