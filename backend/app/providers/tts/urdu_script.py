"""Urdu sentences -> the same sentences in Devanagari, so Kokoro's Hindi voice can read them (Gemini does the writing; checked, never trusted blindly)."""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.http import HttpError, make_client, post_json
from app.providers.tts import TTSUnavailable

log = logging.getLogger("avc.tts")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
ARABIC = re.compile(r"[\u0600-\u06FF]")

PROMPT = """Write each Urdu sentence below in Devanagari script exactly as it is pronounced in spoken Urdu: same words, same order, same sounds.
Do NOT translate and do NOT change Urdu words into Hindi words (keep Persian/Arabic-origin words such as "मंज़र", "ख़ूबसूरत", "इलाक़ों"; keep the nukta: ज़ ख़ ग़ फ़ क़).
Write numbers out as words. Keep the sentence-end marks (। ? !). Do not add or drop anything.
Return ONLY JSON: {{"sentences": [<one Devanagari string per input sentence, same order>]}}

Sentences (JSON):
{items}"""


class GeminiTransliterator:
    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None, batch: int = 12) -> None:
        self.api_key = api_key
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.client = client or make_client(read_timeout=60.0)
        self.batch = batch

    def _ask(self, items: list[str]) -> list[str] | None:
        body = {"contents": [{"parts": [{"text": PROMPT.format(items=json.dumps(items, ensure_ascii=False))}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
        for model in self.models:
            try:
                data = post_json(self.client, ENDPOINT.format(model=model), json=body, headers={"x-goog-api-key": self.api_key}, retries=False)
                out = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])["sentences"]
                if isinstance(out, list) and len(out) == len(items) and all(isinstance(x, str) and self.usable(x) for x in out):
                    return [x.strip() for x in out]
                log.warning("Gemini %s gave an unusable transliteration", model)
            except (httpx.HTTPError, HttpError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                log.warning("Gemini %s failed: %s", model, type(e).__name__)
            time.sleep(1)
        return None

    @staticmethod
    def usable(text: str) -> bool:
        """Devanagari (or digits/punctuation only) and no Arabic-script left over."""
        return bool(DEVANAGARI.search(text)) and not ARABIC.search(text)

    def __call__(self, sentences: list[str]) -> list[str]:
        out: list[str] = []
        for i in range(0, len(sentences), self.batch):
            chunk = sentences[i:i + self.batch]
            got = self._ask(chunk)
            if got is None:
                raise TTSUnavailable("The Urdu text could not be prepared for the voice just now (the Gemini service did not answer). Please try again.")
            out += got
        return out
