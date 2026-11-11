import unittest
from unittest.mock import patch

import subprocess
import windows_process


class HiddenSubprocessTests(unittest.TestCase):
    def test_windows_run_adds_no_window_flag(self):
        captured = {}
        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return "ok"
        with patch.object(subprocess, "run", fake_run):
            with patch.object(windows_process.os, "name", "nt"):
                wrapped = windows_process.install_hidden_subprocess_defaults()
                self.assertEqual(wrapped(["fake-tool"]), "ok")
        self.assertTrue(captured["creationflags"] & subprocess.CREATE_NO_WINDOW)

    def test_existing_creation_flags_are_preserved(self):
        captured = {}
        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return "ok"
        with patch.object(subprocess, "run", fake_run):
            with patch.object(windows_process.os, "name", "nt"):
                wrapped = windows_process.install_hidden_subprocess_defaults()
                wrapped(["fake-tool"], creationflags=0x00000200)
        self.assertEqual(captured["creationflags"], 0x00000200 | subprocess.CREATE_NO_WINDOW)


    def test_ffmpeg_report_environment_is_cleared(self):
        with patch.dict(windows_process.os.environ, {"FFREPORT": "file=should-not-be-created.log:level=32"}):
            windows_process.clear_ffmpeg_report_environment()
            self.assertNotIn("FFREPORT", windows_process.os.environ)

if __name__ == "__main__":
    unittest.main()