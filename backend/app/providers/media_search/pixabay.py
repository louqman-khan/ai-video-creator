from __future__ import annotations

import httpx

from app.http import get_json, make_client
from app.models import MediaAsset, MediaKind

IMAGE_URL = "https://pixabay.com/api/"
VIDEO_URL = "https://pixabay.com/api/videos/"
LICENSE = "Pixabay Content License"
LICENSE_URL = "https://pixabay.com/service/license-summary/"
MAX_IMAGE_WIDTH = 1280  # largeImageURL is capped at 1280 px wide without extra API approval


class PixabaySearch:
    name = "pixabay"
    kinds = frozenset({"video", "image"})

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or make_client()

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        params: dict = {
            "key": self.api_key,
            "q": query[:100],
            "per_page": max(3, min(limit, 50)),
            "safesearch": "true",
        }
        if kind == "video":
            data = get_json(self.client, VIDEO_URL, params=params)
            parse = self._parse_video
        else:
            params["orientation"] = "vertical" if orientation == "portrait" else "horizontal"
            params["image_type"] = "photo"
            data = get_json(self.client, IMAGE_URL, params=params)
            parse = self._parse_image
        out = []
        for hit in data.get("hits", []):
            asset = parse(hit)
            if asset:
                out.append(asset)
        return out

    @staticmethod
    def _credit(kind: str, user: str, page: str) -> str:
        who = user or "a Pixabay contributor"
        return f"{kind} by {who} from Pixabay ({page})"

    def _parse_image(self, h: dict) -> MediaAsset | None:
        url = h.get("largeImageURL") or h.get("webformatURL")
        if not url:
            return None
        w, hgt = int(h.get("imageWidth") or 0), int(h.get("imageHeight") or 0)
        if w > MAX_IMAGE_WIDTH:  # what we can actually download
            hgt, w = round(hgt * MAX_IMAGE_WIDTH / w), MAX_IMAGE_WIDTH
        user = h.get("user", "")
        return MediaAsset(
            id=f"pixabay:{h['id']}",
            source="pixabay",
            kind="image",
            url=url,
            thumb_url=h.get("previewURL", ""),
            page_url=h.get("pageURL", ""),
            width=w,
            height=hgt,
            tags=[t.strip() for t in h.get("tags", "").split(",") if t.strip()],
            license=LICENSE,
            license_url=LICENSE_URL,
            author=user,
            author_url=f"https://pixabay.com/users/{user}-{h['user_id']}/" if h.get("user_id") else "",
            attribution=self._credit("Image", user, h.get("pageURL", "")),
            attribution_required=False,
        )

    def _parse_video(self, h: dict) -> MediaAsset | None:
        renditions = [v for v in (h.get("videos") or {}).values() if v.get("url")]
        if not renditions:
            return None
        # closest to 1080p wide: sharp enough, not a 4K download
        best = min(renditions, key=lambda v: abs(int(v.get("width") or 0) - 1920))
        user = h.get("user", "")
        return MediaAsset(
            id=f"pixabay:{h['id']}",
            source="pixabay",
            kind="video",
            url=best["url"],
            thumb_url=best.get("thumbnail", ""),
            page_url=h.get("pageURL", ""),
            width=int(best.get("width") or 0),
            height=int(best.get("height") or 0),
            duration=float(h["duration"]) if h.get("duration") else None,
            tags=[t.strip() for t in h.get("tags", "").split(",") if t.strip()],
            license=LICENSE,
            license_url=LICENSE_URL,
            author=user,
            attribution=self._credit("Video", user, h.get("pageURL", "")),
            attribution_required=False,
        )
