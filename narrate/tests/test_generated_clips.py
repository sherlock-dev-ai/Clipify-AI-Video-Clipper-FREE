import json
import tempfile
import unittest
from pathlib import Path

from narrate.pipeline import NarratePipeline


class GeneratedClipDiscoveryTests(unittest.TestCase):
    def test_successful_project_exports_are_addressable_without_basename_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            data = Path(temporary) / "profile"
            library = data / "narrate clips"
            output = data / "jobs" / "project-one" / "output"
            library.mkdir(parents=True)
            output.mkdir(parents=True)

            # Same basename in the user's library and project output must be
            # selectable by opaque ID, while legacy basename lookup is refused.
            (library / "short_01.mp4").write_bytes(b"x" * 2048)
            (output / "short_01.mp4").write_bytes(b"y" * 4096)
            (output / "short_01.json").write_text(json.dumps({"title": "Forest story"}), encoding="utf-8")
            (output / "short_02.mp4").write_bytes(b"z" * 2048)
            (output / "short_02.txt").write_text("Title: Text sidecar export", encoding="utf-8")
            (output / "short_03.mp4").write_bytes(b"p" * 4096)  # Partial: no sidecar.
            (output / "short_01_clean.mp4").write_bytes(b"c" * 4096)
            (output / "_tmp_vertical_01.mp4").write_bytes(b"t" * 4096)

            pipeline = NarratePipeline(root, data)
            pipeline._probe = lambda _path: {"duration": 12.5, "width": 1080, "height": 1920}
            videos = pipeline.scan_videos()
            generated = [video for video in videos if video["generated"]]
            self.assertEqual({video["filename"] for video in generated}, {"short_01.mp4", "short_02.mp4"})
            self.assertEqual(next(video["name"] for video in generated if video["filename"] == "short_01.mp4"), "Forest story")
            self.assertTrue(all(video["id"].startswith("clip-") for video in videos))
            self.assertEqual(len({video["id"] for video in videos}), len(videos))
            self.assertIsNone(pipeline._find_video("short_01.mp4"), "duplicate basename must not select an arbitrary project")

            project_clip = next(video for video in generated if video["filename"] == "short_01.mp4")
            self.assertEqual(pipeline._find_video(project_clip["id"]), output / "short_01.mp4")
            self.assertEqual(project_clip["id"], pipeline.video_id(output / "short_01.mp4"))


if __name__ == "__main__":
    unittest.main()
