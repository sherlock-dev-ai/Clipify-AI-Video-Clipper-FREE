"""Regression coverage for vertical framing when a source has no detectable face."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import main  # noqa: E402


class VerticalFramingFallbackTests(unittest.TestCase):
    def test_missing_subject_trajectory_preserves_full_frame(self):
        with patch.object(main, "_detect_person_trajectory", return_value=([], {})), \
             patch.object(main, "_run_hidden") as run_hidden, \
             patch.object(main, "_validate_camera_render", return_value=True), \
             patch.object(main.os.path, "isfile", return_value=True), \
             patch.object(main.os.path, "getsize", return_value=2048):
            self.assertTrue(main.resize_to_vertical_with_zoom("input.mp4", "output.mp4"))

        command = run_hidden.call_args.args[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("boxblur=18:2", filter_complex)
        self.assertIn("overlay=", filter_complex)
        self.assertIn("0:a?", command)


if __name__ == "__main__":
    unittest.main()
