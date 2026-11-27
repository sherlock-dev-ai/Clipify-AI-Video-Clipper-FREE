"""AI Highlight Detector for Clipify AI Live Studio.

Detects moments worth clipping from live transcripts using local Ollama
models with deterministic heuristic fallback when Ollama is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("clipify.live.detector")

CATEGORIES = [
    "Funny moments",
    "Exciting moments",
    "Surprising moments",
    "Emotional moments",
    "Important announcements",
    "Gaming highlights",
    "Educational content",
    "Interesting conversations",
    "High-energy moments",
]

# Common energetic / excitement / laughter markers for deterministic detection
HEURISTIC_PATTERNS = {
    "Funny moments": re.compile(r"\b(haha|lmao|lol|rofl|hilarious|dying|can't breathe|so funny|joke)\b", re.I),
    "Exciting moments": re.compile(r"\b(oh my god|omg|let's go|lets go|holy shit|insane|unbelievable|no way|yooo|yo!)\b", re.I),
    "Surprising moments": re.compile(r"\b(what\?|wait what|did you see|how did|are you serious|no shot|what just happened)\b", re.I),
    "Gaming highlights": re.compile(r"\b(clutch|ace|headshot|kill streak|pog|gg|pentakill|boss fight|victory|clutched)\b", re.I),
    "Important announcements": re.compile(r"\b(announcement|big news|official|reveal|releasing|launching|update|breaking)\b", re.I),
    "High-energy moments": re.compile(r"(!{2,}|WOOO+|LETS GOOO+|WHAT THE|NO WAYYY)", re.I),
}


@dataclass
class HighlightCandidate:
    start_sec: float
    end_sec: float
    category: str
    title: str
    score: float # 1.0 to 10.0
    reason: str
    transcript_snippet: str


def resolve_ollama_model(base_url: str = "http://localhost:11434", requested: str = "") -> str:
    """Resolve an available Ollama model prioritizing lightweight Qwen models."""
    if requested and requested not in ("heuristic", "default"):
        return requested
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            installed = [m.get("name", "") for m in data.get("models", [])]
            for pref in ("qwen3:4b", "qwen3:8b", "qwen2.5:3b", "qwen2.5:latest", "qwen:latest"):
                if any(m.startswith(pref) for m in installed):
                    return pref
            if installed:
                return installed[0]
    except Exception:
        pass
    return "qwen3:4b"


class HighlightDetector:
    """Detects highlights in live transcript windows."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model_name: str = "",
        sensitivity: int = 5, # 1 (least sensitive) to 10 (most sensitive)
        min_clip_gap: float = 30.0,
        ai_provider: str = "ollama",
        hf_model: str = "Qwen/Qwen2.5-7B-Instruct",
        hf_token: str = "",
    ):
        import os
        self.ollama_url = ollama_url.rstrip("/")
        self.model_name = resolve_ollama_model(self.ollama_url, model_name)
        self.sensitivity = max(1, min(10, sensitivity))
        self.min_clip_gap = min_clip_gap
        self.ai_provider = (ai_provider or os.getenv("CLIPPEDAI_AI_PROVIDER", "ollama")).strip().lower()
        self.hf_model = hf_model or os.getenv("CLIPPEDAI_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.last_triggered_time = -999.0

    def evaluate(self, transcript_segments: list[Any]) -> Optional[HighlightCandidate]:
        """Examine recent segments and return a candidate if a highlight occurred."""
        if not transcript_segments:
            return None

        recent_text = " ".join(s.text for s in transcript_segments).strip()
        if len(recent_text.split()) < 8: # Need at least a few words
            return None

        window_start = transcript_segments[0].start_sec
        window_end = transcript_segments[-1].end_sec

        # Enforce anti-duplicate spacing
        if (window_start - self.last_triggered_time) < self.min_clip_gap:
            return None

        # 1. Attempt evaluation via selected AI provider (Hugging Face or Local Ollama)
        if self.ai_provider == "huggingface" and self.hf_token:
            candidate = self._evaluate_huggingface(transcript_segments, recent_text, window_start, window_end)
        else:
            candidate = self._evaluate_ollama(transcript_segments, recent_text, window_start, window_end)

        # 2. Fall back to deterministic heuristic detection
        if candidate is None:
            candidate = self._evaluate_heuristic(transcript_segments, recent_text, window_start, window_end)

        # Check sensitivity threshold (e.g. sensitivity 5 requires score >= 6.0; sensitivity 8 requires >= 4.0)
        threshold = max(3.0, 9.5 - (self.sensitivity * 0.7))
        if candidate and candidate.score >= threshold:
            self.last_triggered_time = candidate.end_sec
            return candidate

        return None

    def _evaluate_ollama(
        self,
        segments: list[Any],
        full_text: str,
        start_sec: float,
        end_sec: float,
    ) -> Optional[HighlightCandidate]:
        """Query local Ollama model to score and categorize the moment."""
        categories_str = ", ".join(CATEGORIES)
        prompt = f"""You are an elite live stream clipper. Analyze this recent speech excerpt from a live stream:
"{full_text}"

Determine if this excerpt contains an engaging highlight moment worth clipping into a vertical short video.
Categories: {categories_str}.

Respond strictly in valid JSON with these exact keys:
{{
  "is_highlight": true/false,
  "category": "one of the categories above",
  "score": a number from 1 to 10,
  "title": "catchy 4-7 word title for the short",
  "reason": "short explanation why it's engaging"
}}
JSON ONLY:"""

        payload_chat = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 150},
        }

        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/chat",
                data=json.dumps(payload_chat).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                response_text = data.get("message", {}).get("content", "").strip()
                m = re.search(r"\{.*\}", response_text, re.DOTALL)
                if m:
                    res_json = json.loads(m.group(0))
                    if res_json.get("is_highlight"):
                        category = res_json.get("category", "Exciting moments")
                        if category not in CATEGORIES:
                            category = "Exciting moments"
                        score = float(res_json.get("score", 7.0))
                        title = str(res_json.get("title", "Insane Live Moment!")).strip()
                        reason = str(res_json.get("reason", "")).strip()

                        return HighlightCandidate(
                            start_sec=max(0.0, start_sec - 2.0),
                            end_sec=end_sec + 2.0,
                            category=category,
                            title=title,
                            score=score,
                            reason=reason,
                            transcript_snippet=full_text,
                        )
        except Exception as e:
            logger.debug("Ollama live evaluation via chat failed: %s", e)

        return None

    def _evaluate_huggingface(
        self,
        segments: list[Any],
        full_text: str,
        start_sec: float,
        end_sec: float,
    ) -> Optional[HighlightCandidate]:
        """Query Hugging Face Serverless Inference router to score and categorize the moment."""
        if not self.hf_token:
            return None
        categories_str = ", ".join(CATEGORIES)
        prompt = (
            f'Analyze this live stream speech excerpt:\n"{full_text}"\n\n'
            f'Determine if it contains an engaging highlight worth clipping into a vertical Short. Categories: {categories_str}.\n'
            'Respond strictly in valid JSON: {"is_highlight": true/false, "category": "...", "score": 1-10, "title": "4-7 word title", "reason": "short reason"}'
        )
        payload = {
            "model": self.hf_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 160,
        }
        try:
            req = urllib.request.Request(
                "https://router.huggingface.co/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.hf_token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                response_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                m = re.search(r"\{.*\}", response_text, re.DOTALL)
                if m:
                    res_json = json.loads(m.group(0))
                    if res_json.get("is_highlight"):
                        category = res_json.get("category", "Exciting moments")
                        if category not in CATEGORIES:
                            category = "Exciting moments"
                        return HighlightCandidate(
                            start_sec=max(0.0, start_sec - 2.0),
                            end_sec=end_sec + 2.0,
                            category=category,
                            title=str(res_json.get("title", "Insane Live Moment!")).strip(),
                            score=float(res_json.get("score", 7.0)),
                            reason=str(res_json.get("reason", "")).strip(),
                            transcript_snippet=full_text,
                        )
        except Exception as e:
            logger.debug("Hugging Face live evaluation failed: %s", e)
        return None

    def _evaluate_heuristic(
        self,
        segments: list[Any],
        full_text: str,
        start_sec: float,
        end_sec: float,
    ) -> Optional[HighlightCandidate]:
        """Fast offline rule-based detector based on regex keywords and exclamation density."""
        matched_cat = None
        matched_weight = 0

        for cat, pattern in HEURISTIC_PATTERNS.items():
            matches = pattern.findall(full_text)
            if matches:
                weight = len(matches) * 2
                if weight > matched_weight:
                    matched_weight = weight
                    matched_cat = cat

        # Exclamation density check
        excl_count = full_text.count("!") + full_text.count("?")
        if excl_count >= 3:
            matched_weight += 2
            if not matched_cat:
                matched_cat = "High-energy moments"

        if matched_cat and matched_weight >= 2:
            score = min(10.0, 5.0 + matched_weight)
            # Create a clean title from the first 5 words
            words = full_text.split()
            title_words = words[:6]
            title = " ".join(title_words).strip().title() + "!"

            return HighlightCandidate(
                start_sec=max(0.0, start_sec - 3.0),
                end_sec=end_sec + 2.0,
                category=matched_cat,
                title=title,
                score=score,
                reason="High emotional intensity and keyword density",
                transcript_snippet=full_text,
            )

        return None

