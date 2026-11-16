from __future__ import annotations

from app.config import Settings
from app.providers.base import Registry

from .heuristic import HeuristicRanker
from .interface import MediaRanker

registry: Registry[MediaRanker] = Registry("media ranker")


@registry.register("heuristic")
def _heuristic(settings: Settings, landscape: bool = True) -> MediaRanker:
    return HeuristicRanker(landscape)


def create_ranker(settings: Settings, landscape: bool = True) -> MediaRanker:
    return registry.create(settings.media_ranker, settings, landscape)


__all__ = ["MediaRanker", "create_ranker"]
