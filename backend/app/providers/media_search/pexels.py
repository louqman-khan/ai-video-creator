"""Optional source: only enabled when PEXELS_API_KEY is set."""

from __future__ import annotations

import httpx

from app.http import get_json, make_client
from app.models import MediaAsset, MediaKind

VIDEO_URL = "https://api.pexels.com/videos/search"
IMAGE_URL = "https://api.pexels.com/v1/search"
LICENSE = "Pexels License"
LICENSE_URL = "https://www.pexels.com/license/"


class PexelsSearch:
    name = "pexels"
    kinds = frozenset({"video", "image"})

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or make_client()

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        params = {"query": query, "per_page": max(1, min(limit, 40)), "orientation": orientation}
        headers = {"Authorization": self.api_key}
        if kind == "video":
            data = get_json(self.client, VIDEO_URL, params=params, headers=headers)
            items = [self._video(v) for v in data.get("videos", [])]
        else:
            data = get_json(self.client, IMAGE_URL, params=params, headers=headers)
            items = [self._image(p) for p in data.get("photos", [])]
        return [a for a in items if a]

    @staticmethod
    def _video(v: dict) -> MediaAsset | None:
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        if not files:
            return None
        best = min(files, key=lambda f: abs(int(f.get("width") or 0) - 1920))
        user = v.get("user") or {}
        return MediaAsset(
            id=f"pexels:{v['id']}",
            source="pexels",
            kind="video",
            url=best["link"],
            thumb_url=v.get("image", ""),
            page_url=v.get("url", ""),
            width=int(best.get("width") or 0),
            height=int(best.get("height") or 0),
            duration=float(v["duration"]) if v.get("duration") else None,
            license=LICENSE,
            license_url=LICENSE_URL,
            author=user.get("name", ""),
            author_url=user.get("url", ""),
            attribution=f"Video by {user.get('name', 'a Pexels contributor')} on Pexels ({v.get('url', '')})",
        )

    @staticmethod
    def _image(p: dict) -> MediaAsset | None:
        src = p.get("src") or {}
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            return None
        return MediaAsset(
            id=f"pexels:{p['id']}",
            source="pexels",
            kind="image",
            url=url,
            thumb_url=src.get("medium", ""),
            page_url=p.get("url", ""),
            width=int(p.get("width") or 0),
            height=int(p.get("height") or 0),
            title=p.get("alt", "") or "",
            license=LICENSE,
            license_url=LICENSE_URL,
            author=p.get("photographer", ""),
            author_url=p.get("photographer_url", ""),
            attribution=f"Photo by {p.get('photographer', 'a Pexels contributor')} on Pexels ({p.get('url', '')})",
        )
