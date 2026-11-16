"""No-LLM fallback: English only. Query = the scene's most informative words."""

from __future__ import annotations

import re

from app.models import Scene, Transcript
from app.pipeline.scenes import chunk_scenes

from .interface import PlannerError

_STOP = set(
    """a an the and or but if then so of to in on at by for with from as is are was were be been
    being it its this that these those i you he she we they me my your his her our their there here
    not no yes do does did have has had will would can could should just very really about into
    over out up down than too also what which who whom how why when where""".split()
)


def keywords_from(text: str, n: int = 4) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z']+", text.lower()) if w not in _STOP and len(w) > 2]
    seen: dict[str, int] = {}
    for w in words:
        seen.setdefault(w, len(w))
    return sorted(seen, key=lambda w: -seen[w])[:n]


class HeuristicPlanner:
    def __init__(self, min_s: float = 3.0, max_s: float = 8.0) -> None:
        self.min_s, self.max_s = min_s, max_s

    def plan(self, transcript: Transcript) -> list[Scene]:
        if transcript.language != "en":
            raise PlannerError(
                f"The heuristic planner only supports English (got '{transcript.language}'). "
                "Use SCENE_PLANNER=gemini to translate Urdu scenes into English search queries."
            )
        scenes = chunk_scenes(transcript, self.min_s, self.max_s)
        for s in scenes:
            kws = keywords_from(s.text)
            s.query_en = " ".join(kws[:3]) or "abstract background"
            s.keywords = kws
        return scenes
