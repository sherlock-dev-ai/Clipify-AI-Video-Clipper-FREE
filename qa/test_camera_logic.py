"""Small deterministic regressions for camera control math."""
import json
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class CameraMathTests(unittest.TestCase):
    def test_deadzone_holds_without_residual_motion(self):
        camera_x = 500.0
        for detected_target in (512.0, 487.0, 520.0, 493.0, 501.0):
            camera_x, step = main._camera_follow_axis(
                camera_x, detected_target, deadzone=38.0
            )
            self.assertEqual(step, 0.0)
            self.assertEqual(camera_x, 500.0)

    def test_large_subject_move_follows_without_overshoot(self):
        x, step = main._camera_follow_axis(500.0, 900.0, deadzone=38.0)
        self.assertGreater(step, 0.0)
        self.assertGreater(x, 500.0)
        self.assertLess(x, 900.0)
        x, _ = main._camera_follow_axis(x, 900.0, deadzone=38.0)
        self.assertGreater(x, 660.0)
        self.assertLess(x, 900.0)

    def test_unsafe_face_overrides_deadzone(self):
        x, step = main._camera_follow_axis(
            500.0, 520.0, deadzone=38.0, unsafe_face=True
        )
        self.assertNotEqual(step, 0.0)
        self.assertGreater(x, 500.0)

    def test_track_gate_rejects_identity_jump_but_keeps_jitter(self):
        track = {"cx": 0.370, "cy": 0.25, "w": 0.10,
                 "velocity_x": 0.0, "velocity_y": 0.0}
        jitter = {"cx": 0.376, "cy": 0.252, "w": 0.102}
        poster_jump = {"cx": 0.237, "cy": 0.30, "w": 0.10}
        self.assertIsNotNone(main._camera_track_association_cost(track, jitter, 0.2))
        self.assertIsNone(main._camera_track_association_cost(track, poster_jump, 0.2))

    def test_motion_prediction_keeps_a_moving_subject_associated(self):
        track = {"cx": 0.370, "cy": 0.25, "w": 0.10,
                 "velocity_x": 0.15, "velocity_y": 0.0}
        detection = {"cx": 0.400, "cy": 0.25, "w": 0.10}
        self.assertIsNotNone(main._camera_track_association_cost(track, detection, 0.2))

    def test_challenger_switch_requires_real_prominence_and_separation(self):
        self.assertTrue(main._camera_challenger_qualifies(
            0.9429, 0.9504, challenger_visible=12, separation_px=900,
            score_gap=0.006, min_separation_px=270,
        ))
        self.assertFalse(main._camera_challenger_qualifies(
            0.9429, 0.9450, challenger_visible=12, separation_px=900,
            score_gap=0.006, min_separation_px=270,
        ))
        self.assertFalse(main._camera_challenger_qualifies(
            0.9429, 0.9504, challenger_visible=1, separation_px=900,
            score_gap=0.006, min_separation_px=270,
        ))
        self.assertFalse(main._camera_challenger_qualifies(
            0.9429, 0.9504, challenger_visible=12, separation_px=100,
            score_gap=0.006, min_separation_px=270,
        ))

    def test_face_box_safety_checks_edges_not_only_center(self):
        face = {"cx": 0.5, "w": 0.10}
        self.assertTrue(main._camera_face_fits_crop(1166.0, 1080, 3413.0, face))
        self.assertFalse(main._camera_face_fits_crop(1500.0, 1080, 3413.0, face))

    def test_face_box_safety_rejects_a_head_cut_by_the_top_edge(self):
        face = {"cx": 0.5, "cy": 0.1, "w": 0.10, "h": 0.08}
        self.assertTrue(main._camera_face_fits_crop(
            1166.0, 1080, 3413.0, face, 0.0, 960, 1920.0
        ))
        self.assertFalse(main._camera_face_fits_crop(
            1166.0, 1080, 3413.0, face, 120.0, 960, 1920.0
        ))

    def test_split_hold_rejects_a_face_cut_by_panel_edge(self):
        self.assertTrue(main._camera_face_box_fits_panel(
            [180.0, 90.0, 360.0, 300.0], 640, 569
        ))
        self.assertFalse(main._camera_face_box_fits_panel(
            [0.0, 90.0, 130.0, 240.0], 640, 569
        ))

    def test_split_hold_rejects_head_clipped_above_face_box(self):
        # The face box itself is below the edge, but the expanded head envelope
        # would cross the panel top.
        self.assertFalse(main._camera_face_box_fits_panel(
            [180.0, 18.0, 360.0, 253.0], 640, 569
        ))

    def test_safe_poster_face_cannot_mask_clipped_primary_speaker(self):
        detections = [
            ([-18.3, 53.2, 112.0, 210.7], 0.9993),
            ([157.1, 25.3, 207.0, 95.9], 0.8697),
        ]
        self.assertFalse(main._camera_split_primary_face_is_safe(
            detections, 640, 569
        ))

    def test_split_hold_changes_only_on_validation_samples(self):
        self.assertTrue(main._camera_split_hold_state(True, False, False))
        self.assertFalse(main._camera_split_hold_state(True, True, True))
        self.assertFalse(main._camera_split_hold_state(False, False, False))
        self.assertTrue(main._camera_split_hold_state(False, True, False))

    def test_split_panel_hold_is_short_and_never_uses_a_future_face(self):
        self.assertFalse(main._split_panel_hold_for_gap(None, 0.5))
        self.assertFalse(main._split_panel_hold_for_gap(1.0, 1.1))
        self.assertTrue(main._split_panel_hold_for_gap(1.0, 1.3))
        self.assertFalse(main._split_panel_hold_for_gap(1.0, 1.61))

    def test_sparse_keyframe_holds_until_the_declared_change_time(self):
        series = [
            {"time": 0.0, "x": 735.0, "y": 0.0},
            {"time": 4.8, "x": 735.0, "y": 0.0, "state": "LOCKED"},
            {"time": 4.8, "x": 2255.0, "y": 0.0, "state": "SNAP"},
        ]
        expression = main._camera_expression(series, "x")
        self.assertTrue(expression.startswith("735.00+"))
        self.assertIn("gte(t\\,4.800)", expression)
        self.assertEqual(expression.count("clip("), 0)

    def test_camera_expression_keeps_snap_when_reducing_dense_path(self):
        series = [
            {"time": i * 0.2, "x": i * 10.0, "y": 0.0, "state": "FOLLOWING"}
            for i in range(51)
        ]
        series[20] = {
            "time": 4.0, "x": 1000.0, "y": 0.0,
            "state": "SNAP", "reason": "SCENE_CUT: reacquire",
        }
        expression = main._camera_expression(series, "x", max_kf=12)
        self.assertIn("*gte(t\\,4.000)", expression)

    def test_normal_camera_can_keep_existing_snap_interpolation(self):
        series = [
            {"time": 0.0, "x": 100.0, "y": 0.0},
            {"time": 1.0, "x": 100.0, "y": 0.0, "state": "LOCKED"},
            {"time": 1.0, "x": 900.0, "y": 0.0, "state": "SNAP"},
        ]
        expression = main._camera_expression(
            series, "x", preserve_snap_events=False
        )
        self.assertIn("clip((t-1.000)/0.200", expression)
        self.assertNotIn("gte(", expression)

    def test_saved_split_top_path_tracks_visible_subject_between_real_cuts(self):
        path = (Path(__file__).resolve().parent / "qa-live-20261008" /
                "camera_split_zoom18_debug" /
                "split_camera_path_topfix_20261009.json")
        plan = json.loads(path.read_text(encoding="utf-8"))
        top = plan["top_keyframes"]
        bottom = plan["bottom_keyframes"]

        def value_at(points, time_s, key):
            ordered = sorted(points, key=lambda point: point["time"])
            left = max((point for point in ordered if point["time"] <= time_s),
                       key=lambda point: point["time"])
            right = min((point for point in ordered if point["time"] >= time_s),
                        key=lambda point: point["time"])
            if right["time"] == left["time"]:
                return left[key]
            amount = (time_s - left["time"]) / (right["time"] - left["time"])
            return left[key] + amount * (right[key] - left[key])

        for time_s in (24.0, 27.0, 29.5, 31.0):
            for key in ("x", "y"):
                self.assertAlmostEqual(value_at(top, time_s, key),
                                       value_at(bottom, time_s, key), places=5)

        snaps = [point["time"] for point in top
                 if point.get("state") == "SNAP" and 20.6 <= point["time"] <= 31.6]
        self.assertEqual(snaps, [20.6, 31.6])
        self.assertTrue(all(
            0 <= point["x"] <= plan["scaled_w"] - plan["panel_w"] and
            0 <= point["y"] <= plan["scaled_h"] - plan["panel_h"]
            for point in top
        ))
        expression = main._camera_expression(top, "x", max_kf=30)
        self.assertIn("gte(t\\,20.600)", expression)
        self.assertIn("gte(t\\,31.600)", expression)
        self.assertNotIn("gte(t\\,27.400)", expression)

    def test_saved_split_bottom_path_reacquires_visible_subject_at_316s_cut(self):
        base = (Path(__file__).resolve().parent / "qa-live-20261008" /
                "camera_split_zoom18_debug")
        original = json.loads(
            (base / "split_camera_path_topfix_20261009.json").read_text(
                encoding="utf-8"))
        corrected = json.loads(
            (base / "split_camera_path_bottomfix_20261010.json").read_text(
                encoding="utf-8"))
        self.assertEqual(corrected["top_keyframes"], original["top_keyframes"])

        start, end = 31.6, 32.6
        expected = [point for point in original["top_keyframes"]
                    if start <= point["time"] <= end]
        actual = [point for point in corrected["bottom_keyframes"]
                  if start <= point["time"] <= end]
        self.assertEqual(actual, expected)
        self.assertTrue(any(point["time"] == 31.6 and
                            point.get("state") == "SNAP"
                            for point in actual))
        self.assertTrue(all(
            0 <= point["x"] <= corrected["scaled_w"] - corrected["panel_w"] and
            0 <= point["y"] <= corrected["scaled_h"] - corrected["panel_h"]
            for point in actual
        ))

    def test_split_smoothing_preserves_exact_reacquisition_snap(self):
        path = main._locked_follow_series([
            {"time": 0.0, "x": 200.0, "y": 0.0},
            {"time": 1.0, "x": 200.0, "y": 0.0, "state": "LOCKED"},
            {"time": 1.0, "x": 1500.0, "y": 0.0, "state": "SNAP",
             "reason": "SCENE_CUT: reacquire"},
            {"time": 2.0, "x": 1500.0, "y": 0.0},
        ])
        snaps = [point for point in path if point.get("state") == "SNAP"]
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["time"], 1.0)
        self.assertEqual(snaps[0]["x"], 1500.0)
        self.assertIn("gte(t\\,1.000)", main._camera_expression(path, "x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
