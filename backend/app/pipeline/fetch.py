"""Scene -> search -> rank -> download. Never fails a whole run because one scene has no media."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.media.cache import MediaCache
from app.models import MediaKind, Scene, ScenePick
from app.providers.media_ranker import MediaRanker
from app.providers.media_search import CompositeSearch

log = logging.getLogger("avc.fetch")


def fetch_media(
    scenes: list[Scene],
    search: CompositeSearch,
    ranker: MediaRanker,
    cache: MediaCache,
    orientation: str = "landscape",
    on_scene: Callable[[int, int], None] | None = None,
) -> list[ScenePick]:
    picks: list[ScenePick] = []
    used: set[str] = set()
    for n, scene in enumerate(scenes):
        if on_scene:
            on_scene(n, len(scenes))
        queries = [q for q in [scene.query_en, *scene.keywords] if q]
        kinds: list[MediaKind] = ["image", "video"] if scene.preferred_kind == "image" else ["video", "image"]
        pick = ScenePick(scene_id=scene.id)
        for query in queries:
            candidates = []
            for kind in kinds:
                candidates += search.search(query, kind, orientation=orientation, limit=10)
            if not candidates:
                log.info("scene %d: nothing for %r, trying next query", scene.id, query)
                continue
            for asset in ranker.rank(scene, candidates, used=used):
                try:
                    path = cache.get(asset)
                except Exception as e:  # dead link, hotlink block, timeout: try the next one
                    log.warning("scene %d: download failed (%s): %s", scene.id, asset.id, e)
                    continue
                pick = ScenePick(scene_id=scene.id, asset=asset, local_path=str(path))
                used.add(asset.id)
                break
            if pick.asset:
                break
        if not pick.asset:
            log.warning("scene %d: no media found, using a black placeholder", scene.id)
        picks.append(pick)
    return picks
