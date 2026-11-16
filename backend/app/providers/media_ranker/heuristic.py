"""Zero-dependency ranker: source order + resolution/orientation/duration sanity.
A CLIP-based ranker (image-text similarity) can replace this behind the same interface."""

from __future__ import annotations

import re
from collections.abc import Collection

from app.models import MediaAsset, Scene


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


class HeuristicRanker:
    def __init__(self, landscape: bool = True) -> None:
        self.landscape = landscape

    def _score(self, scene: Scene, a: MediaAsset, used: Collection[str]) -> float:
        s = 0.0
        if a.id in used:
            s -= 100
        # keyword match: scene query/keywords vs the asset's tags + title (max 3 words count)
        wanted = _tokens(" ".join([scene.query_en, *scene.keywords]))
        have = _tokens(" ".join([*a.tags, a.title]))
        s += 1.5 * min(len(wanted & have), 3)
        if a.width and a.height:
            if (a.width >= a.height) != self.landscape:
                s -= 20
            s += 3 if a.width >= 1920 else 2 if a.width >= 1280 else -5 if a.width < 1000 else 0
        if a.kind == "video":
            s += 2
            if a.duration and a.duration < scene.duration * 0.5:
                s -= 3
        if scene.preferred_kind and a.kind == scene.preferred_kind:
            s += 2
        return s

    def rank(
        self, scene: Scene, candidates: list[MediaAsset], *, used: Collection[str] = ()
    ) -> list[MediaAsset]:
        scored = [(self._score(scene, a, used) - i * 0.01, a) for i, a in enumerate(candidates)]
        return [a for _, a in sorted(scored, key=lambda t: -t[0])]
