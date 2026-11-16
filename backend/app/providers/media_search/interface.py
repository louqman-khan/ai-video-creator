from __future__ import annotations

from typing import Protocol

from app.models import MediaAsset, MediaKind


class MediaSearch(Protocol):
    name: str
    kinds: frozenset[str]

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        """Return legally reusable candidates, each with license + attribution filled in."""
        ...
