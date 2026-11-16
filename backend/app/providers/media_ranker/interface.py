from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from app.models import MediaAsset, Scene


class MediaRanker(Protocol):
    def rank(
        self, scene: Scene, candidates: list[MediaAsset], *, used: Collection[str] = ()
    ) -> list[MediaAsset]:
        """Best first. `used` = asset ids already placed in other scenes."""
        ...
