from __future__ import annotations

import hashlib
import itertools
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
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

    def __init__(self, sources: list[MediaSearch], cache_dir: Path | None = None, deadline: float = 15.0,
                 breaker_failures: int = 2, breaker_pause: float = 180.0) -> None:
        self.sources = sources
        # circuit breaker: a source that failed or stalled this many times in a row is left out for `breaker_pause` seconds (a site that is down
        # for this network must not add its timeout to every single search)
        self._fails: dict[str, int] = {}
        self._paused_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self.breaker_failures, self.breaker_pause = breaker_failures, breaker_pause
        self.deadline = deadline  # seconds one search may take in total: a stalled site must not hold a whole video back
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _note(self, name: str, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails[name] = 0
                return
            self._fails[name] = self._fails.get(name, 0) + 1
            if self._fails[name] >= self.breaker_failures:
                self._paused_until[name] = time.monotonic() + self.breaker_pause
                self._fails[name] = 0
                log.warning("%s keeps failing: leaving it out of searches for %.0f s", name, self.breaker_pause)

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
        now = time.monotonic()
        with self._lock:
            active = [s for s in self.sources if kind in s.kinds and self._paused_until.get(s.name, 0) <= now]
        pool = ThreadPoolExecutor(max_workers=max(1, len(active)), thread_name_prefix="search")
        try:
            futures = {pool.submit(s.search, query, kind, orientation=orientation, limit=limit): s for s in active}
            done, late = wait(futures, timeout=self.deadline)
            for f in futures:  # keep the sources' own order, so the interleaving stays the same
                src = futures[f]
                if f in late:
                    failed = True
                    log.warning("%s search for %r took longer than %.0f s: skipped", src.name, query, self.deadline)
                    self._note(src.name, ok=False)
                    continue
                try:
                    per_source.append(f.result())
                    self._note(src.name, ok=True)
                except Exception as e:  # one broken source must not kill the run
                    failed = True
                    log.warning("%s search failed for %r: %s", src.name, query, e)
                    self._note(src.name, ok=False)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # a stalled request is left to time out by itself; we do not wait for it
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
