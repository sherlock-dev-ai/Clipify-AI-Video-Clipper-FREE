from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import app as app_module


GOOD_SCRIPT = (
    "I thought the shortcut would save me time, but every turn led to another locked gate. "
    "My friends kept telling me to quit, so I tried one last route. It looked completely wrong, "
    "then it opened the fastest path and everyone started laughing."
)
BAD_SCRIPT = (
    "[Upbeat synth music fades in]\n\n**Narrator (voiceover):** You ever notice the moon looks bigger? "
    "Well, it is perspective. [Music fades out]"
)


class FakeResponse:
    def __init__(self, content: str):
        self.body = json.dumps({"message": {"content": content}}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class NarrateScriptQualityTests(unittest.TestCase):
    def test_plain_complete_narration_is_accepted_and_stage_directions_are_rejected(self):
        self.assertTrue(app_module._script_is_complete(GOOD_SCRIPT))
        self.assertFalse(app_module._script_is_complete(BAD_SCRIPT))
        self.assertFalse(app_module._script_is_complete("This draft is far too short."))

    def test_normal_story_words_are_not_mistaken_for_reasoning_headers(self):
        narration = (
            "I kept thinking about the plan while everyone watched me take the wrong turn. "
            "The analysis was simple: I had ignored the sign, missed the exit, and sent us toward the beach. "
            "We laughed, found another route, and arrived before the rain started."
        )
        self.assertTrue(app_module._script_is_complete(narration))
        self.assertFalse(app_module._script_is_complete("Analysis: the story needs a better ending."))

    def test_incomplete_model_response_gets_one_bounded_retry(self):
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(BAD_SCRIPT), FakeResponse(GOOD_SCRIPT)]) as call:
            result = app_module._call_ollama_script_prompt("plain narration", "make a story", "fallback")
        self.assertEqual(result, GOOD_SCRIPT)
        self.assertEqual(call.call_count, 2)
        retry_payload = json.loads(call.call_args_list[1].args[0].data)
        self.assertIn("no headings", retry_payload["messages"][1]["content"])

    def test_two_incomplete_responses_use_transparent_fallback(self):
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(BAD_SCRIPT), FakeResponse("Too short.")]) as call:
            result = app_module._call_ollama_script_prompt("plain narration", "make a story", "known fallback")
        self.assertEqual(result, "known fallback")
        self.assertEqual(call.call_count, 2)

    def test_transport_error_falls_back_without_retries(self):
        with patch("urllib.request.urlopen", side_effect=OSError("offline")) as call:
            result = app_module._call_ollama_script_prompt("plain narration", "make a story", "known fallback")
        self.assertEqual(result, "known fallback")
        self.assertEqual(call.call_count, 1)

    def test_random_script_endpoint_reports_template_fallback(self):
        client = app_module.app.test_client()
        base_url = f"http://127.0.0.1:{app_module.APP_PORT}"
        observed = {}

        def use_fallback(system_prompt, user_prompt, fallback, model=""):
            observed.update(system_prompt=system_prompt, user_prompt=user_prompt, fallback=fallback)
            return fallback

        with patch.object(app_module, "_random_script", return_value=GOOD_SCRIPT), patch.object(
            app_module, "_call_ollama_script_prompt", side_effect=use_fallback
        ):
            response = client.post("/api/narrate/random-script", base_url=base_url, json={"target_duration": 45})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["used_ai"])
        self.assertEqual(payload["target_duration"], 45)
        self.assertEqual(payload["target_word_count"], 144)
        self.assertGreaterEqual(len(payload["script"].split()), 144)
        self.assertIn("144-156 words", observed["system_prompt"])

    def test_random_script_fallback_is_fitted_to_the_default_thirty_seconds(self):
        script = app_module._fit_script_to_duration(GOOD_SCRIPT, 30)
        self.assertGreaterEqual(len(script.split()), 96)


if __name__ == "__main__":
    unittest.main(verbosity=2)
