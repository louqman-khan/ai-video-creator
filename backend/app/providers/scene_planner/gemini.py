"""Gemini planner. Timing is NOT left to the LLM: scenes are cut from word timestamps
(pipeline.scenes) and the LLM only writes English search queries for each scene's text,
which also translates Urdu into queries the stock sites understand."""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.http import HttpError, make_client, post_json
from app.models import Scene, Transcript
from app.pipeline.scenes import chunk_scenes

from .interface import PlannerError

log = logging.getLogger("avc.planner")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
BATCH = 40

PROMPT = """You help a video editor choose stock footage. Language of the narration: {lang}.
For each numbered scene below, write what should be SHOWN on screen while it is spoken.
Return ONLY a JSON array, one object per scene:
{{"id": <scene id>, "query_en": "<2-5 English words: concrete, visual, searchable on a stock site>",
 "keywords": ["<3 alternative English queries>"], "preferred_kind": "video" | "image"}}
Rules: always English (translate if the narration is Urdu); prefer concrete nouns and places
over abstract ideas; no names of private people; no quotes or punctuation in queries.
Scenes:
{scenes}"""


class Annotation(BaseModel):
    id: int
    query_en: str
    keywords: list[str] = Field(default_factory=list)
    preferred_kind: Literal["video", "image"] | None = None


def parse_annotations(raw: str) -> list[Annotation]:
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    data = json.loads(text)
    if isinstance(data, dict):  # model wrapped the array in an object
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return [Annotation.model_validate(d) for d in data]


class GeminiPlanner:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        min_s: float = 3.0,
        max_s: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise PlannerError("GEMINI_API_KEY is not set (or use SCENE_PLANNER=heuristic for English).")
        self.api_key, self.model = api_key, model
        self.min_s, self.max_s = min_s, max_s
        self.client = client or make_client(read_timeout=120.0)  # LLM calls can be slow

    def _ask(self, lang: str, scenes: list[Scene]) -> list[Annotation]:
        listing = "\n".join(f"{s.id}. {s.text}" for s in scenes)
        body = {
            "contents": [{"parts": [{"text": PROMPT.format(lang=lang, scenes=listing)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
        }
        try:
            data = post_json(
                self.client,
                ENDPOINT.format(model=self.model),
                json=body,
                headers={"x-goog-api-key": self.api_key},  # header, so the key never lands in a URL
            )
        except (httpx.HTTPError, HttpError) as e:
            raise PlannerError(f"Gemini request failed: {type(e).__name__}: {e}") from None
        try:
            return parse_annotations(data["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as e:
            raise PlannerError(f"Gemini returned an unusable answer: {type(e).__name__}") from e

    def plan(self, transcript: Transcript) -> list[Scene]:
        scenes = chunk_scenes(transcript, self.min_s, self.max_s)
        by_id = {s.id: s for s in scenes}
        for i in range(0, len(scenes), BATCH):
            batch = scenes[i : i + BATCH]
            wanted = {s.id for s in batch}
            for attempt in (1, 2):
                try:
                    anns = self._ask(transcript.language, [by_id[j] for j in sorted(wanted)])
                except PlannerError:
                    if attempt == 2:
                        raise
                    continue
                for a in anns:
                    if a.id in wanted and a.query_en.strip():
                        s = by_id[a.id]
                        s.query_en = a.query_en.strip()
                        s.keywords = [k.strip() for k in a.keywords if k.strip()][:3]
                        s.preferred_kind = a.preferred_kind
                        wanted.discard(a.id)
                if not wanted:
                    break
                log.warning("Gemini missed scenes %s (attempt %d)", sorted(wanted), attempt)
            if wanted:
                raise PlannerError(f"No query produced for scenes {sorted(wanted)}")
        return scenes
