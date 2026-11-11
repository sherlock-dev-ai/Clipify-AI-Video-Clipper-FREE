"""Tests for avoiding needless NLTK downloads when tokenizer data is cached."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

import main  # noqa: E402


class OfflineNltkResourceTests(unittest.TestCase):
    def test_modern_english_punkt_tab_cache_satisfies_punkt_requirement(self):
        data = Mock()
        data.find.side_effect = lambda resource: (
            object() if resource == "tokenizers/punkt_tab/english/"
            else (_ for _ in ()).throw(LookupError(resource))
        )

        self.assertTrue(main._nltk_resource_available(data, (
            "tokenizers/punkt",
            "tokenizers/punkt/english.pickle",
            "tokenizers/punkt_tab/english/",
        )))

    def test_unavailable_resources_remain_unavailable(self):
        data = Mock()
        data.find.side_effect = LookupError("not cached")
        self.assertFalse(main._nltk_resource_available(data, (
            "tokenizers/punkt/english.pickle",
            "tokenizers/punkt_tab/english/",
        )))

    def test_existing_modern_punkt_data_prevents_download_attempts(self):
        data = Mock()
        data.find.side_effect = lambda resource: (
            object() if resource == "tokenizers/punkt_tab/english/"
            else (_ for _ in ()).throw(LookupError(resource))
        )
        download = Mock()
        fake_nltk = SimpleNamespace(data=data, download=download)

        with patch.dict(sys.modules, {"nltk": fake_nltk}):
            self.assertTrue(main._ensure_nltk_punkt())

        download.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
