"""User-supplied media: files in a folder, matched by filename words."""

from __future__ import annotations

import re
from pathlib import Path

from app.models import MediaAsset, MediaKind

_VIDEO = {".mp4", ".mov", ".mkv", ".webm"}
_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}


class LocalFolderSearch:
    name = "local"
    kinds = frozenset({"video", "image"})

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        exts = _VIDEO if kind == "video" else _IMAGE
        words = set(re.findall(r"\w+", query.lower()))
        scored: list[tuple[int, Path]] = []
        for f in sorted(self.folder.rglob("*")):
            if f.suffix.lower() not in exts:
                continue
            hits = len(words & set(re.findall(r"\w+", f.stem.lower())))
            scored.append((hits, f))
        scored.sort(key=lambda t: -t[0])  # stable: no match still returns files as a last resort
        return [
            MediaAsset(
                id=f"local:{f.name}",
                source="local",
                kind=kind,
                url=f.resolve().as_uri(),
                title=f.stem,
                license="User-provided",
                attribution="User-provided media",
            )
            for _, f in scored[:limit]
        ]
