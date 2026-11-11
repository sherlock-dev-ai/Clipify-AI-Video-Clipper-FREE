"""Focused offline regression tests for the Qwen candidate-selection contract.

These tests exercise parsing and ranking only. They do not claim a live Ollama
or end-to-end rendering pass.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def _response(candidate_id: int, decision: str, value: float = 8.0) -> str:
    dims = {
        key: value
        for key in (
            "hook", "curiosity", "emotion", "surprise", "story", "payoff",
            "pacing", "standalone", "rewatch", "conflict", "coherence",
        )
    }
    return json.dumps({"candidates": [{"candidate_id": candidate_id,
                                       "decision": decision, **dims}]})


class AISelectionContractTests(unittest.TestCase):
    def test_prompt_treats_podcast_punchline_as_payoff_without_weakening_keep_gate(self):
        clip = SimpleNamespace(start_time=75.0, end_time=110.0)
        with patch.object(main, "EDIT_MODE", "viral"):
            prompt = main.build_clip_analysis_prompt([
                (0, clip, [{"word": "roast"}], "setup, punchline, and host reaction")
            ])
        system = prompt[0]["content"]
        self.assertIn("podcast or roast", system)
        self.assertIn("conventional story arc", system)
        self.assertIn("not an automatic rejection", system)
        self.assertIn("decision must agree with the scores and reason", system)
        rejected = main.parse_ai_clip_scores(_response(0, "reject"), [0])[0]
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(
            [(0, clip, 50.0, rejected)]
        )
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_rejected_all")

    def test_funny_prompt_recognizes_setup_punchline_and_reaction(self):
        clip = SimpleNamespace(start_time=0.0, end_time=35.0)
        with patch.object(main, "EDIT_MODE", "funny"):
            prompt = main.build_clip_analysis_prompt([
                (0, clip, [{"word": "joke"}], "a funny setup and punchline")
            ])
        self.assertIn("setup, punchline, and reaction", prompt[0]["content"])
    def test_clear_keep_and_reject_decisions_are_preserved(self):
        keep = main.parse_ai_clip_scores(_response(0, "keep"), [0])
        reject = main.parse_ai_clip_scores(_response(1, "reject"), [1])
        self.assertTrue(keep[0]["ai_valid"])
        self.assertEqual(keep[0]["decision"], "keep")
        self.assertTrue(reject[1]["ai_valid"])
        self.assertEqual(reject[1]["decision"], "reject")

    def test_malformed_and_unrequested_candidates_are_not_ai_scores(self):
        self.assertEqual(main.parse_ai_clip_scores("not json", [0]), {})
        self.assertEqual(main.parse_ai_clip_scores(_response(9, "keep"), [0]), {})

    def test_missing_or_unknown_decision_is_malformed_not_implicit_keep(self):
        missing = json.loads(_response(0, "keep"))
        missing["candidates"][0].pop("decision")
        unknown = json.loads(_response(0, "keep"))
        unknown["candidates"][0]["decision"] = "maybe"
        self.assertEqual(main.parse_ai_clip_scores(json.dumps(missing), [0]), {})
        self.assertEqual(main.parse_ai_clip_scores(json.dumps(unknown), [0]), {})

    def test_missing_non_numeric_or_out_of_range_score_is_malformed(self):
        missing = json.loads(_response(0, "keep"))
        missing["candidates"][0].pop("coherence")
        text_score = json.loads(_response(0, "keep"))
        text_score["candidates"][0]["payoff"] = "8"
        out_of_range = json.loads(_response(0, "keep"))
        out_of_range["candidates"][0]["hook"] = 11
        for response in (missing, text_score, out_of_range):
            self.assertEqual(main.parse_ai_clip_scores(json.dumps(response), [0]), {})

    def test_keep_outscores_equal_reject_without_discarding_reject(self):
        clips = [SimpleNamespace(start_time=0.0, end_time=40.0),
                 SimpleNamespace(start_time=80.0, end_time=120.0)]
        scores = {
            **main.parse_ai_clip_scores(_response(0, "reject"), [0]),
            **main.parse_ai_clip_scores(_response(1, "keep"), [1]),
        }
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates(clips, object(), scores)
        self.assertEqual([row[0] for row in ranked], [1, 0])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[-1][3]["decision"], "reject")

    def test_all_rejected_candidates_remain_explicitly_marked(self):
        clips = [SimpleNamespace(start_time=0.0, end_time=40.0),
                 SimpleNamespace(start_time=80.0, end_time=120.0)]
        scores = {
            **main.parse_ai_clip_scores(_response(0, "reject"), [0]),
            **main.parse_ai_clip_scores(_response(1, "reject"), [1]),
        }
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates(clips, object(), scores)
        self.assertEqual(len(ranked), 2)
        self.assertTrue(all(row[3]["decision"] == "reject" for row in ranked))

    def test_rejected_candidate_is_skipped_and_next_explicit_keep_can_fill_slot(self):
        clips = [SimpleNamespace(start_time=0.0, end_time=40.0),
                 SimpleNamespace(start_time=80.0, end_time=120.0)]
        scores = {
            **main.parse_ai_clip_scores(_response(0, "reject", value=10), [0]),
            **main.parse_ai_clip_scores(_response(1, "keep", value=7), [1]),
        }
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates(clips, object(), scores)
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(status, "qwen_approved")
        self.assertEqual([row[0] for row in eligible], [1])
        self.assertEqual(eligible[0][3]["decision"], "keep")

    def test_all_explicit_rejections_stop_without_deterministic_override(self):
        clips = [SimpleNamespace(start_time=0.0, end_time=40.0),
                 SimpleNamespace(start_time=80.0, end_time=120.0)]
        scores = {
            **main.parse_ai_clip_scores(_response(0, "reject"), [0]),
            **main.parse_ai_clip_scores(_response(1, "reject"), [1]),
        }
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates(clips, object(), scores)
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_rejected_all")

    def test_malformed_candidates_do_not_override_a_valid_qwen_rejection(self):
        rejected = main.parse_ai_clip_scores(_response(0, "reject"), [0])[0]
        malformed = {"ai_valid": False, "decision": "keep"}
        ranked = [(0, object(), 40.0, rejected), (1, object(), 50.0, malformed)]
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_rejected_all")

    def test_no_valid_qwen_decision_blocks_all_render_candidates(self):
        fallback = {"ai_valid": False, "decision": None}
        ranked = [(0, object(), 50.0, fallback)]
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_unavailable")

    def test_malformed_or_missing_decisions_cannot_reach_render_gate(self):
        clip = SimpleNamespace(start_time=0.0, end_time=40.0)
        malformed_results = main.parse_ai_clip_scores("not json", [0])
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates([clip], object(), malformed_results)
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_unavailable")

    def test_qwen_timeout_cannot_reach_render_gate(self):
        clip = SimpleNamespace(start_time=0.0, end_time=40.0)
        with patch.object(main, "extract_candidate_transcript", return_value=("sample", [])), \
             patch.object(main, "build_clip_analysis_prompt", return_value=[]), \
             patch.object(main, "call_ollama", return_value=None) as call, \
             patch.object(main, "calculate_engagement_score", return_value=0.5):
            scores = main.analyze_candidates_with_ai([clip], object(), batch_size=1)
            ranked = main.rank_candidates([clip], object(), scores)
            eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(call.call_count, 2)  # One batch attempt and one individual retry.
        self.assertEqual(eligible, [])
        self.assertEqual(status, "qwen_unavailable")

    def test_process_does_not_enter_renderer_when_qwen_has_no_valid_keep(self):
        clip = SimpleNamespace(start_time=0.0, end_time=40.0)
        finder = SimpleNamespace(find_clips=lambda **kwargs: [clip])
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / "cached-transcript.pkl"
            transcript_path.write_bytes(b"fixture")
            with patch.object(main, "load_existing_transcription", return_value=object()), \
                 patch.object(main, "create_candidate_clip_finder", return_value=finder), \
                 patch.object(main, "_dedupe_candidates", side_effect=lambda clips: clips), \
                 patch.object(main, "_add_sentence_aligned_prefix_candidates", side_effect=lambda clips, _transcript: clips), \
                 patch.object(main, "calculate_engagement_score", return_value=0.5), \
                 patch.object(main, "analyze_candidates_with_ai", return_value={}), \
                 patch.object(main, "resize_to_vertical_with_zoom") as resize, \
                 patch.object(main, "create_animated_subtitles") as captions:
                messages = io.StringIO()
                with redirect_stdout(messages):
                    outputs = main.process_single_video(
                        input_path="fixture.mp4",
                        transcription_path=str(transcript_path),
                        max_clips=1,
                        video_index=1,
                        total_videos=1,
                    )
        self.assertEqual(outputs, [])
        self.assertIn("[ERROR] No valid Qwen keep decision", messages.getvalue())
        resize.assert_not_called()
        captions.assert_not_called()

    def test_only_explicit_keeps_survive_when_other_responses_are_unscored(self):
        clips = [SimpleNamespace(start_time=0.0, end_time=40.0),
                 SimpleNamespace(start_time=80.0, end_time=120.0)]
        scores = main.parse_ai_clip_scores(_response(0, "keep"), [0])
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            ranked = main.rank_candidates(clips, object(), scores)
        eligible, status = main.gate_ranked_candidates_by_qwen_decision(ranked)
        self.assertEqual(status, "qwen_approved")
        self.assertEqual([row[0] for row in eligible], [0])
        self.assertTrue(all(row[3]["ai_valid"] and row[3]["decision"] == "keep" for row in eligible))

    def test_unscored_candidate_is_marked_as_unavailable_not_ai_valid(self):
        clip = SimpleNamespace(start_time=0.0, end_time=40.0)
        with patch.object(main, "calculate_engagement_score", return_value=0.5):
            score, meta = main.compute_final_score(0, clip, object(), {})
        self.assertEqual(score, 50.0)
        self.assertFalse(meta["ai_valid"])
        self.assertEqual(meta["reason"], "AI score unavailable for this candidate.")

    def test_keep_provenance_records_model_and_decision(self):
        provenance = main.selection_provenance({
            "ai_valid": True, "decision": "keep",
        })
        self.assertEqual(provenance["method"], "qwen")
        self.assertEqual(provenance["model"], main.OLLAMA_MODEL)
        self.assertEqual(provenance["decision"], "keep")
        self.assertFalse(provenance["recovery_used"])

    def test_reject_provenance_preserves_rejection_without_recovery(self):
        provenance = main.selection_provenance({
            "ai_valid": True, "decision": "reject",
        })
        self.assertEqual(provenance["method"], "qwen")
        self.assertEqual(provenance["decision"], "reject")
        self.assertFalse(provenance["recovery_used"])
        self.assertIn("not eligible for output", provenance["note"])

    def test_unavailable_qwen_provenance_marks_candidate_ineligible(self):
        provenance = main.selection_provenance({
            "ai_valid": False, "reason": "AI score unavailable",
        })
        self.assertEqual(provenance["method"], "unavailable")
        self.assertIsNone(provenance["model"])
        self.assertIsNone(provenance["decision"])
        self.assertFalse(provenance["recovery_used"])
        self.assertIn("not eligible", provenance["note"])

    def test_empty_candidates_do_not_call_ollama(self):
        with patch.object(main, "call_ollama") as call:
            self.assertEqual(main.analyze_candidates_with_ai([], object()), {})
        call.assert_not_called()

    def test_unusable_model_response_gets_one_individual_retry(self):
        candidate = SimpleNamespace(start_time=0.0, end_time=40.0)
        with patch.object(main, "extract_candidate_transcript", return_value=("sample", [])), \
             patch.object(main, "build_clip_analysis_prompt", return_value=[]), \
             patch.object(main, "call_ollama", return_value=None) as call:
            result = main.analyze_candidates_with_ai([candidate], object(), batch_size=1)
        self.assertEqual(result, {})
        self.assertEqual(call.call_count, 2)

    def test_malformed_response_gets_one_individual_retry_then_stops(self):
        candidate = SimpleNamespace(start_time=0.0, end_time=40.0)
        malformed = json.dumps({"candidates": [{"candidate_id": 0, "decision": "maybe"}]})
        with patch.object(main, "extract_candidate_transcript", return_value=("sample", [])), \
             patch.object(main, "build_clip_analysis_prompt", return_value=[]), \
             patch.object(main, "call_ollama", return_value=malformed) as call:
            result = main.analyze_candidates_with_ai([candidate], object(), batch_size=1)
        self.assertEqual(result, {})
        self.assertEqual(call.call_count, 2)

    def test_near_duplicate_candidate_is_removed_and_later_candidate_kept(self):
        clips = [SimpleNamespace(start_time=0.0),
                 SimpleNamespace(start_time=5.0),
                 SimpleNamespace(start_time=14.0)]
        result = main._dedupe_candidates(clips, min_overlap_gap=12.0)
        self.assertEqual(result, [clips[0], clips[2]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
