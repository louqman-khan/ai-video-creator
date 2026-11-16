from __future__ import annotations

import hashlib
import itertools
import json
import logging
from pathlib import Path

from app.config import Settings
from app.models import MediaAsset, MediaKind

from .interface import MediaSearch
from .local_folder import LocalFolderSearch
from .openverse import OpenverseSearch
from .pexels import PexelsSearch
from .pixabay import PixabaySearch
from .wikimedia import WikimediaSearch

log = logging.getLogger("avc.search")

__all__ = ["CompositeSearch", "MediaSearch", "build_sources", "create_search"]


class CompositeSearch:
    """Queries every enabled source, interleaves results (so one source cannot dominate),
    survives a failing source, and caches results on disk."""

    name = "composite"
    kinds = frozenset({"video", "image"})

    def __init__(self, sources: list[MediaSearch], cache_dir: Path | None = None) -> None:
        self.sources = sources
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, query: str, kind: str, orientation: str) -> Path | None:
        if not self.cache_dir:
            return None
        names = ",".join(s.name for s in self.sources)
        key = hashlib.sha1(f"{names}|{kind}|{orientation}|{query.lower()}".encode()).hexdigest()
        return self.cache_dir / f"search_{key}.json"

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        cache = self._cache_path(query, kind, orientation)
        if cache and cache.exists():
            return [MediaAsset.model_validate(a) for a in json.loads(cache.read_text("utf-8"))]
        per_source: list[list[MediaAsset]] = []
        failed = False
        for src in self.sources:
            if kind not in src.kinds:
                continue
            try:
                per_source.append(src.search(query, kind, orientation=orientation, limit=limit))
            except Exception as e:  # one broken source must not kill the run
                failed = True
                log.warning("%s search failed for %r: %s", src.name, query, e)
        merged = [
            a
            for a in itertools.chain.from_iterable(itertools.zip_longest(*per_source))
            if a is not None
        ]
        if cache and not failed:
            cache.write_text(json.dumps([a.model_dump() for a in merged]), "utf-8")
        return merged


def build_sources(settings: Settings) -> list[MediaSearch]:
    """Instantiate enabled sources; sources that need a missing key are skipped."""
    sources: list[MediaSearch] = []
    if settings.local_media_dir and Path(settings.local_media_dir).is_dir():
        sources.append(LocalFolderSearch(settings.local_media_dir))
    for name in settings.source_names:
        if name == "pixabay":
            if settings.pixabay_api_key:
                sources.append(PixabaySearch(settings.pixabay_api_key))
            else:
                log.warning("pixabay enabled but PIXABAY_API_KEY is empty: skipping")
        elif name == "pexels":
            if settings.pexels_api_key:
                sources.append(PexelsSearch(settings.pexels_api_key))
            else:
                log.info("pexels: no key set, skipping (optional)")
        elif name == "openverse":
            sources.append(OpenverseSearch())
        elif name == "wikimedia":
            sources.append(WikimediaSearch())
        else:
            log.warning("unknown media source %r ignored", name)
    return sources


def create_search(settings: Settings) -> CompositeSearch:
    sources = build_sources(settings)
    if not sources:
        raise RuntimeError("No media sources available. Set PIXABAY_API_KEY or enable openverse/wikimedia.")
    return CompositeSearch(sources, cache_dir=Path(settings.work_dir) / "cache" / "search")
