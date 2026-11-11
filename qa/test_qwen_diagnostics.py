import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as web_app
import main as worker


class QwenDiagnosticPersistenceTests(unittest.TestCase):
    def test_pipeline_failure_reports_worker_error_instead_of_generic_no_output(self):
        detail = web_app._pipeline_failure_detail(
            0,
            [],
            ["[ERROR] Qwen explicitly rejected every valid candidate; no Short was created."],
        )
        self.assertIn("Qwen explicitly rejected", detail)

    def test_job_events_are_persisted_redacted_and_replayable_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous_jobs_dir = web_app.JOBS
            job_id = "diagnostic-job-01"
            job_dir = Path(tmp) / job_id
            job_dir.mkdir()
            web_app.JOBS = Path(tmp)
            web_app.jobs[job_id] = {"id": job_id, "events": [], "status": "error"}
            try:
                web_app.emit(job_id, "log", "Authorization: Bearer token-value-123456")
                journal = job_dir / "events.jsonl"
                self.assertTrue(journal.is_file())
                saved = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
                self.assertNotIn("token-value-123456", saved["event"]["message"])
                self.assertIn("[REDACTED]", saved["event"]["message"])

                # Simulate a server restart: only the durable per-job journal remains.
                web_app.jobs.pop(job_id)
                response = web_app.app.test_client().get(
                    f"/api/events/{job_id}",
                    base_url=f"http://127.0.0.1:{web_app.APP_PORT}",
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"[REDACTED]", response.data)
            finally:
                web_app.jobs.pop(job_id, None)
                web_app.JOBS = previous_jobs_dir

    def test_qwen_response_and_parsed_decisions_are_saved_without_prompt_text(self):
        response = json.dumps({
            "candidates": [{
                "candidate_id": 4,
                "decision": "keep",
                "hook": 8, "curiosity": 7, "emotion": 6, "surprise": 7,
                "story": 8, "payoff": 9, "pacing": 8, "standalone": 8,
                "rewatch": 7, "conflict": 6, "coherence": 9,
                "reason": "A coherent setup and payoff.",
            }],
            "api_key": "example-secret-value",
        })
        parsed = worker.parse_ai_clip_scores(response, [4])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "diagnostics" / "qwen.jsonl"
            with patch.dict(os.environ, {"CLIPPEDAI_QWEN_DIAGNOSTIC_LOG": str(target)}):
                worker._record_qwen_diagnostic("clip_ranking_1", [4], response, parsed)
            saved_text = target.read_text(encoding="utf-8")
            record = json.loads(saved_text.splitlines()[0])
        self.assertEqual(record["response_state"], "parsed")
        self.assertEqual(record["parsed_candidates"][0]["decision"], "keep")
        self.assertIn("[REDACTED]", record["raw_response"])
        self.assertNotIn("example-secret-value", saved_text)
        self.assertNotIn("transcript", record)

    def test_candidate_analyzer_journals_real_batch_response_and_parse(self):
        response = json.dumps({"candidates": [{
            "candidate_id": 0, "decision": "reject",
            "hook": 5, "curiosity": 5, "emotion": 5, "surprise": 5,
            "story": 5, "payoff": 5, "pacing": 5, "standalone": 5,
            "rewatch": 5, "conflict": 5, "coherence": 5,
            "reason": "The moment has no clear payoff.",
        }]})
        words = [
            {"word": "A", "start_time": 0.1, "end_time": 0.3},
            {"word": "short", "start_time": 0.4, "end_time": 0.7},
            {"word": "test", "start_time": 0.8, "end_time": 1.1},
        ]
        transcription = SimpleNamespace(get_word_info=lambda: words)
        clip = SimpleNamespace(start_time=0.0, end_time=1.5)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "qwen.jsonl"
            with patch.dict(os.environ, {"CLIPPEDAI_QWEN_DIAGNOSTIC_LOG": str(target)}):
                with patch.object(worker, "call_ollama", return_value=response):
                    results = worker.analyze_candidates_with_ai([clip], transcription)
            record = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(results[0]["decision"], "reject")
        self.assertEqual(record["task"], "clip_ranking_1")
        self.assertEqual(record["parsed_candidates"][0]["decision"], "reject")
        self.assertIn('"decision": "reject"', record["raw_response"])

    def test_empty_or_malformed_qwen_response_is_recorded_as_unavailable_or_unscored(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "qwen.jsonl"
            with patch.dict(os.environ, {"CLIPPEDAI_QWEN_DIAGNOSTIC_LOG": str(target)}):
                worker._record_qwen_diagnostic("clip_ranking_1", [1], None, {})
                worker._record_qwen_diagnostic("clip_retry_2", [2], "not-json", {})
            records = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[0]["response_state"], "unavailable")
        self.assertEqual(records[1]["response_state"], "malformed_or_unscored")


if __name__ == "__main__":
    unittest.main()
