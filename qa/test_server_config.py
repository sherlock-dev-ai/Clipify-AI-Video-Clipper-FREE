import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server_config import configured_port


class ServerPortTests(unittest.TestCase):
    def test_default_port_is_unchanged(self):
        self.assertEqual(configured_port({}), 5000)

    def test_custom_port_is_used(self):
        self.assertEqual(configured_port({"CLIPPEDAI_PORT": "51737"}), 51737)

    def test_invalid_port_is_rejected(self):
        for value in ("nope", "0", "65536", "-1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "CLIPPEDAI_PORT"):
                configured_port({"CLIPPEDAI_PORT": value})


if __name__ == "__main__":
    unittest.main()
