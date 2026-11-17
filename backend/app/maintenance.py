"""Disk usage and clean-up. Everything removed here can be made again (downloaded stock media, proxies, render caches);
a project's own files (uploads, exports, the timeline) are never touched. Deletion stays inside the work folder."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.media.derive import asset_key

DAY = 86400.0
GRACE_S = 3600.0  # files younger than this may belong to something happening right now


def _size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    return sum(_size(c) for c in p.iterdir()) if p.is_dir() else 0


def _newest(p: Path) -> float:
    if p.is_file():
        return p.stat().st_mtime
    times = [_newest(c) for c in p.iterdir()] if p.is_dir() else []
    return max(times, default=p.stat().st_mtime if p.exists() else 0.0)


def _roots(settings: Settings) -> dict[str, Path]:
    work = Path(settings.work_dir)
    return {
        "projects": Path(settings.projects_dir),
        "stock": work / "cache" / "media",
        "proxies": Path(settings.proxy_dir) if settings.proxy_dir else work / "cache" / "proxies",
        "search": work / "cache" / "search",
    }


def referenced_files(settings: Settings) -> set[Path]:
    """Every media file that some project still uses (timeline assets and the scene picks of unedited projects)."""
    used: set[Path] = set()
    projects = _roots(settings)["projects"]
    if not projects.is_dir():
        return used
    for d in projects.iterdir():
        for name, key in (("timeline.json", "assets"), ("assets.json", None)):
            f = d / name
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if key:
                items = list((data.get(key) or {}).values()) if isinstance(data, dict) else []
                paths = [i.get("path") for i in items if isinstance(i, dict)]
            else:
                paths = [(i.get("local_path") if isinstance(i, dict) else None) for i in (data if isinstance(data, list) else [])]
            used.update(Path(p).resolve() for p in paths if p)
    return used


@dataclass
class Item:
    key: str
    label: str
    bytes: int = 0
    reclaimable: int = 0
    paths: list[Path] = field(default_factory=list)  # what a clean would remove


def survey(settings: Settings, days: float = 7.0, segments: bool = True) -> list[Item]:
    """Sizes by category and what could be removed."""
    roots = _roots(settings)
    used = referenced_files(settings)
    now = time.time()
    items = {k: Item(k, label) for k, label in (("projects", "Projects (uploads, previews, exports)"), ("segments", "Render caches inside projects"),
                                                  ("stock", "Downloaded stock media"), ("proxies", "Editing proxies"), ("search", "Search results"))}

    projects = roots["projects"]
    if projects.is_dir():
        for d in projects.iterdir():
            if not d.is_dir():
                continue
            seg_paths = [d / n for n in ("tl_segments", "tl_segments_preview", "audio_mix") if (d / n).exists()]
            seg_bytes = sum(_size(p) for p in seg_paths)
            items["segments"].bytes += seg_bytes
            items["projects"].bytes += _size(d) - seg_bytes
            for p in seg_paths:
                if segments and now - _newest(p) > days * DAY:
                    items["segments"].paths.append(p)
                    items["segments"].reclaimable += _size(p)
            for part in d.rglob("*.part*"):
                if part.is_file() and now - part.stat().st_mtime > GRACE_S:
                    items["segments"].paths.append(part)
                    items["segments"].reclaimable += _size(part)

    stock = roots["stock"]
    if stock.is_dir():
        for f in stock.iterdir():
            items["stock"].bytes += _size(f)
            if f.resolve() not in used and now - _newest(f) > max(days * DAY, GRACE_S):
                items["stock"].paths.append(f)
                items["stock"].reclaimable += _size(f)

    proxies = roots["proxies"]
    if proxies.is_dir():
        live = {asset_key(p) for p in used if p.is_file()}
        for d in proxies.iterdir():
            items["proxies"].bytes += _size(d)
            if d.name not in live and now - _newest(d) > GRACE_S:
                items["proxies"].paths.append(d)
                items["proxies"].reclaimable += _size(d)

    search = roots["search"]
    if search.is_dir():
        for f in search.iterdir():
            items["search"].bytes += _size(f)
            if now - _newest(f) > days * DAY:
                items["search"].paths.append(f)
                items["search"].reclaimable += _size(f)
    return list(items.values())


def clean(settings: Settings, days: float = 7.0, segments: bool = False, dry_run: bool = False) -> dict:
    """Remove what `survey` lists (render caches only when `segments`). Returns {freed, removed, items}."""
    work = Path(settings.work_dir).resolve()
    proxies = _roots(settings)["proxies"].resolve()
    freed = removed = 0
    for item in survey(settings, days, segments):
        for p in item.paths:
            rp = p.resolve()
            if not (rp.is_relative_to(work) or rp.is_relative_to(proxies)) or rp in (work, proxies):  # never outside, never the roots
                continue
            n = _size(rp)
            if not dry_run:
                shutil.rmtree(rp, ignore_errors=True) if rp.is_dir() else rp.unlink(missing_ok=True)
            freed += n
            removed += 1
    return {"freed": freed, "removed": removed, "dry_run": dry_run}
