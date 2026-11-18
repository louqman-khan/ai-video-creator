"""Optional clean-up of recognised text with an LLM (Gemini): fix mis-heard and misspelled words using the context, without adding or removing content.

Used on text only; the caller aligns the corrected text back onto the word timings (pipeline.align), so timing never depends on the LLM.
Always optional and always checked: a chunk whose answer changes too much (length, or too many words) is rejected and the original kept."""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.http import HttpError, make_client, post_json

log = logging.getLogger("avc.correct")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You are correcting the output of an automatic speech recogniser. Language: {lang}.
The text below was heard from a speaker; some words are misheard or misspelled (for Urdu: wrong letters, split or merged words, honorifics spelled wrongly).
Fix ONLY clear recognition mistakes, using the surrounding sentences and well-known names and religious or technical terms.
Rules: keep the same sentences in the same order; do not add, remove, translate, summarise or explain anything; do not add punctuation or numbering;
if you are not sure about a word, leave it as it is.{glossary}
Return ONLY JSON: {{"text": "<the corrected text>"}}

Text:
{text}"""


def _words(text: str) -> list[str]:
    return text.split()


def acceptable(original: str, corrected: str, max_change: float = 0.6) -> bool:
    """A correction may fix spelling, not rewrite: the word count stays within 15 % and most words stay recognisable."""
    a, b = _words(original), _words(corrected)
    if not a or not b or not 0.85 <= len(b) / len(a) <= 1.15:
        return False
    same = len(set(a) & set(b)) / max(1, len(set(a)))
    return same >= 1 - max_change


class GeminiCorrector:
    def __init__(self, api_key: str, model: str = "gemini-flash-lite-latest,gemini-3-flash-preview,gemini-3.5-flash", glossary: str = "",
                 client: httpx.Client | None = None, chunk_words: int = 70) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self.api_key = api_key
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.glossary = glossary.strip()
        self.client = client or make_client(read_timeout=60.0)
        self.chunk_words = chunk_words

    def _ask(self, lang: str, text: str) -> str | None:
        gl = f"\nNames and terms that may occur (spell them like this): {self.glossary}" if self.glossary else ""
        body = {"contents": [{"parts": [{"text": PROMPT.format(lang=lang, glossary=gl, text=text)}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
        for model in self.models:
            try:
                data = post_json(self.client, ENDPOINT.format(model=model), json=body, headers={"x-goog-api-key": self.api_key}, retries=False)
                return str(json.loads(data["candidates"][0]["content"]["parts"][0]["text"])["text"]).strip()
            except (httpx.HTTPError, HttpError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                log.warning("Gemini %s failed: %s", model, type(e).__name__)
                time.sleep(1)
        return None

    def correct(self, text: str, lang: str) -> tuple[str, dict]:
        """(corrected text, stats). Chunks the text by words; a rejected or failed chunk keeps its original words."""
        words = _words(text)
        out: list[str] = []
        stats = {"chunks": 0, "accepted": 0, "rejected": 0, "failed": 0}
        for i in range(0, len(words), self.chunk_words):
            chunk = " ".join(words[i:i + self.chunk_words])
            stats["chunks"] += 1
            fixed = self._ask(lang, chunk)
            if fixed is None:
                stats["failed"] += 1
                out.append(chunk)
            elif acceptable(chunk, fixed):
                stats["accepted"] += 1
                out.append(fixed)
            else:
                stats["rejected"] += 1
                out.append(chunk)
        return " ".join(out), stats
