"""Regression tests for WhisperX's NLTK Punkt resource path compatibility."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import main  # noqa: E402


class WhisperXPunktCompatibilityTests(unittest.TestCase):
    def test_existing_whisperx_resource_is_used_without_fallback(self):
        expected = object()
        loader = Mock(return_value=expected)
        data_find = Mock()
        tokenizer_factory = Mock()

        actual = main._load_whisperx_alignment_resource(
            "tokenizers/punkt_tab/english.pickle",
            loader=loader,
            data_find=data_find,
            tokenizer_factory=tokenizer_factory,
        )

        self.assertIs(actual, expected)
        data_find.assert_not_called()
        tokenizer_factory.assert_not_called()

    def test_current_nltk_directory_loads_the_cached_language_tokenizer(self):
        expected = object()
        loader = Mock(side_effect=LookupError("legacy .pickle resource missing"))
        data_find = Mock(return_value=object())
        tokenizer_factory = Mock(return_value=expected)

        actual = main._load_whisperx_alignment_resource(
            "tokenizers/punkt_tab/english.pickle",
            loader=loader,
            data_find=data_find,
            tokenizer_factory=tokenizer_factory,
        )

        self.assertIs(actual, expected)
        data_find.assert_called_once_with("tokenizers/punkt_tab/english/")
        tokenizer_factory.assert_called_once_with("english")

    def test_missing_current_nltk_directory_still_fails_loudly(self):
        loader = Mock(side_effect=LookupError("legacy resource missing"))
        data_find = Mock(side_effect=LookupError("language data missing"))
        tokenizer_factory = Mock()

        with self.assertRaisesRegex(LookupError, "language data missing"):
            main._load_whisperx_alignment_resource(
                "tokenizers/punkt_tab/english.pickle",
                loader=loader,
                data_find=data_find,
                tokenizer_factory=tokenizer_factory,
            )
        tokenizer_factory.assert_not_called()

    def test_non_punkt_resources_do_not_get_a_punkt_fallback(self):
        loader = Mock(side_effect=LookupError("resource missing"))
        data_find = Mock()
        tokenizer_factory = Mock()

        with self.assertRaisesRegex(LookupError, "resource missing"):
            main._load_whisperx_alignment_resource(
                "tokenizers/other/resource.pickle",
                loader=loader,
                data_find=data_find,
                tokenizer_factory=tokenizer_factory,
            )
        data_find.assert_not_called()
        tokenizer_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
