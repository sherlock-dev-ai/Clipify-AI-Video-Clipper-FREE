from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stage_payload import sync_tree, tree_manifest, verify_payload, wants


class NarratePayloadAssetTests(unittest.TestCase):
    def test_sync_tree_replaces_content_and_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            destination = root / "destination"
            (source / "nested").mkdir(parents=True)
            (destination / "nested").mkdir(parents=True)
            (source / "nested" / "fresh.bin").write_bytes(b"fresh")
            (destination / "nested" / "old.bin").write_bytes(b"old")
            (destination / "old-root.bin").write_bytes(b"old root")

            sync_tree(source, destination)

            self.assertEqual(tree_manifest(source), tree_manifest(destination))
            self.assertFalse((destination / "nested" / "old.bin").exists())
            self.assertFalse((destination / "old-root.bin").exists())

    def test_user_narrate_clips_are_excluded_from_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            standard = root / "narrate clips"
            optional = root / "big narrate clips"
            output = root / "output"
            standard.mkdir()
            optional.mkdir()
            output.mkdir()
            self.assertFalse(wants(standard))
            self.assertFalse(wants(optional))
            self.assertFalse(wants(output))

    def test_payload_verifier_rejects_narration_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            footage = root / "narrate clips" / "user.mp4"
            footage.parent.mkdir()
            footage.write_bytes(b"test")
            _count, problems = verify_payload(root)
            self.assertTrue(any("user-provided narration footage must not ship" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
