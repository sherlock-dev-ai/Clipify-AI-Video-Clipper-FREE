"""Regression coverage for keeping Qwen input candidates inside job bounds."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import main  # noqa: E402


class CandidateGenerationBoundsTests(unittest.TestCase):
    def test_environment_accepts_short_source_duration_bounds(self):
        with patch.dict(os.environ, {"MIN_CLIP_DURATION": "5"}):
            self.assertEqual(main._env_duration("MIN_CLIP_DURATION", 25), 5)

    def test_duration_enforcement_uses_current_bounds(self):
        clip = SimpleNamespace(start_time=0.0, end_time=6.7, start_char=0, end_char=10)
        transcription = SimpleNamespace(
            get_word_info=lambda: [],
            get_sentence_info=lambda: [],
        )
        with patch.object(main, "MIN_CLIP_DURATION", 5), \
             patch.object(main, "MAX_CLIP_DURATION", 7), \
             patch.object(main, "PREFERRED_MIN_CLIP_DURATION", 5), \
             patch.object(main, "PREFERRED_MAX_CLIP_DURATION", 7):
            result = main.enforce_duration_bounds(clip, transcription, verbose=False)

        self.assertIs(result, clip)

    def test_cli_preserves_bounds_fitted_to_short_source_video(self):
        torch_stub = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        with patch.object(main, "_init_ml_runtime"), \
             patch.object(main, "find_input_videos_auto", return_value=[]), \
             patch.object(main, "MIN_CLIP_DURATION", 25), \
             patch.object(main, "MAX_CLIP_DURATION", 60), \
             patch.object(main, "PREFERRED_MIN_CLIP_DURATION", 30), \
             patch.object(main, "PREFERRED_MAX_CLIP_DURATION", 55), \
             patch.dict(sys.modules, {"torch": torch_stub}), \
             patch.object(sys, "argv", ["main.py", "--auto", "--min-duration", "5", "--max-duration", "7"]):
            main.main()

            self.assertEqual(main.MIN_CLIP_DURATION, 5)
            self.assertEqual(main.MAX_CLIP_DURATION, 7)

    def test_clipsai_receives_the_requested_short_duration_bounds(self):
        captured = {}

        def finder_factory(**kwargs):
            captured.update(kwargs)
            return object()

        with patch.dict(sys.modules, {"clipsai": SimpleNamespace(ClipFinder=finder_factory)}):
            with patch.object(main, "MIN_CLIP_DURATION", 30), patch.object(main, "MAX_CLIP_DURATION", 45):
                main.create_candidate_clip_finder()

        self.assertEqual(captured, {
            "min_clip_duration": 30,
            "max_clip_duration": 45,
            "cutoff_policy": "high",
        })

    def test_candidate_bounds_clamp_to_supported_short_range(self):
        captured = {}

        def finder_factory(**kwargs):
            captured.update(kwargs)
            return object()

        with patch.dict(sys.modules, {"clipsai": SimpleNamespace(ClipFinder=finder_factory)}):
            with patch.object(main, "MIN_CLIP_DURATION", 2), patch.object(main, "MAX_CLIP_DURATION", 900):
                main.create_candidate_clip_finder()

        self.assertEqual(captured["min_clip_duration"], 5)
        self.assertEqual(captured["max_clip_duration"], 60)

    def test_overlong_candidate_gets_a_sentence_aligned_preferred_prefix(self):
        base = SimpleNamespace(
            start_time=347.255,
            end_time=398.242,
            start_char=4297,
            end_char=4932,
        )
        sentence_rows = [
            {"start_time": 347.255, "start_char": 4297, "end_time": 348.215, "end_char": 4323},
            {"start_time": 380.953, "start_char": 4777, "end_time": 382.834, "end_char": 4792},
            {"start_time": 397.742, "start_char": 4920, "end_time": 398.242, "end_char": 4932},
        ]

        class FakeClip:
            def __init__(self, start_time, end_time, start_char, end_char):
                self.start_time = start_time
                self.end_time = end_time
                self.start_char = start_char
                self.end_char = end_char

        transcription = SimpleNamespace(get_sentence_info=lambda: sentence_rows)
        with patch.object(main, "MIN_CLIP_DURATION", 25), \
             patch.object(main, "MAX_CLIP_DURATION", 60), \
             patch.object(main, "PREFERRED_MIN_CLIP_DURATION", 30), \
             patch.object(main, "_clip_class", return_value=FakeClip):
            actual = main._add_sentence_aligned_prefix_candidates([base], transcription)

        self.assertEqual(len(actual), 2)
        prefix = actual[1]
        self.assertEqual(prefix.start_time, 347.255)
        self.assertEqual(prefix.end_time, 382.834)
        self.assertEqual(prefix.start_char, 4297)
        self.assertEqual(prefix.end_char, 4792)
        self.assertGreaterEqual(prefix.end_time - prefix.start_time, 25)
        self.assertLessEqual(prefix.end_time - prefix.start_time, 60)

    def test_materially_shorter_prefix_survives_candidate_deduplication(self):
        full = SimpleNamespace(start_time=347.255, end_time=398.242)
        prefix = SimpleNamespace(start_time=347.255, end_time=382.834)
        near_duplicate = SimpleNamespace(start_time=348.0, end_time=399.0)

        actual = main._dedupe_candidates([full, prefix, near_duplicate])

        self.assertEqual(actual, [full, prefix])

    def test_no_prefix_is_added_when_no_complete_sentence_near_target_exists(self):
        base = SimpleNamespace(start_time=100.0, end_time=160.0, start_char=10, end_char=80)
        sentence_rows = [
            {"start_time": 100.0, "start_char": 10, "end_time": 101.0, "end_char": 20},
            {"start_time": 150.0, "start_char": 60, "end_time": 151.0, "end_char": 70},
        ]
        transcription = SimpleNamespace(get_sentence_info=lambda: sentence_rows)
        with patch.object(main, "_clip_class", return_value=object):
            actual = main._add_sentence_aligned_prefix_candidates([base], transcription)
        self.assertEqual(actual, [base])


if __name__ == "__main__":
    unittest.main(verbosity=2)
