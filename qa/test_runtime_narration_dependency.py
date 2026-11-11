from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-runtime.txt"
INSTALLER = ROOT / "build" / "installer_app" / "lib" / "installer.js"
MODEL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)
MODEL_SHA256 = "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"


class RuntimeNarrationDependencyTests(unittest.TestCase):
    def test_runtime_manifest_pins_official_compatible_model_wheel_and_hash(self):
        content = REQUIREMENTS.read_text(encoding="utf-8")
        matching = [
            line.strip()
            for line in content.splitlines()
            if line.strip().lower().startswith("en-core-web-sm @")
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn(MODEL_URL, matching[0])
        self.assertIn(f"#sha256={MODEL_SHA256}", matching[0])

    def test_installer_runtime_gate_imports_and_loads_kokoro_english_model(self):
        content = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("'en_core_web_sm'", content)
        self.assertIn("spacy.load('en_core_web_sm', enable=['tok2vec', 'tagger'])", content)
        self.assertIn("failures.append('Kokoro English model:", content)
        self.assertIn("Kokoro English model is outside the selected runtime", content)

    def test_runtime_builder_requires_the_kokoro_model_before_reporting_ready(self):
        content = (ROOT / "build" / "build_runtime.py").read_text(encoding="utf-8")
        self.assertIn('Path("Lib", "site-packages", "en_core_web_sm")', content)
        self.assertIn("spacy.load('en_core_web_sm', enable=['tok2vec', 'tagger'])", content)
        self.assertIn("Kokoro English model is outside the selected runtime", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
