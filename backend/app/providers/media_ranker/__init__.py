from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.providers.base import Registry

from .heuristic import HeuristicRanker
from .interface import MediaRanker

registry: Registry[MediaRanker] = Registry("media ranker")


@registry.register("heuristic")
def _heuristic(settings: Settings, landscape: bool = True) -> MediaRanker:
    return HeuristicRanker(landscape)


@registry.register("clip")
def _clip(settings: Settings, landscape: bool = True) -> MediaRanker:
    from .clip import ClipRanker

    return ClipRanker(Path(settings.clip_dir), Path(settings.work_dir) / "cache" / "clip", landscape)


@registry.register("auto")
def _auto(settings: Settings, landscape: bool = True) -> MediaRanker:
    from .clip import models_present

    return _clip(settings, landscape) if models_present(Path(settings.clip_dir)) else _heuristic(settings, landscape)


def create_ranker(settings: Settings, landscape: bool = True) -> MediaRanker:
    return registry.create(settings.media_ranker, settings, landscape)


__all__ = ["MediaRanker", "create_ranker"]
