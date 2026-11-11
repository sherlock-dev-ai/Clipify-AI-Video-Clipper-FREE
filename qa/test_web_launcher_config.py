from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebLauncherConfigTests(unittest.TestCase):
    def test_start_launcher_uses_configured_port_and_default(self):
        script = (ROOT / "start_web.bat").read_text(encoding="utf-8")
        self.assertIn('if not defined CLIPPEDAI_PORT set "CLIPPEDAI_PORT=5000"', script)
        self.assertIn('http://127.0.0.1:%CLIPPEDAI_PORT%/', script)
        self.assertNotIn('http://127.0.0.1:5000/', script)

    def test_wrapper_uses_its_own_directory(self):
        script = (ROOT / "run_web.bat").read_text(encoding="utf-8")
        self.assertIn('call "%~dp0start_web.bat"', script)
        self.assertNotIn("L:\\ClippedAI\\start_web.bat", script)


if __name__ == "__main__":
    unittest.main()
