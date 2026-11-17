"""Openverse (CC-licensed images). No API key needed for light anonymous use."""

from __future__ import annotations

import httpx

from app.http import get_json, make_client
from app.models import MediaAsset, MediaKind

API_URL = "https://api.openverse.org/v1/images/"
AUDIO_URL = "https://api.openverse.org/v1/audio/"
_OK_EXT = (".jpg", ".jpeg", ".png", ".webp")
_NO_ATTRIBUTION = {"cc0", "pdm"}


def license_label(code: str, version: str) -> str:
    code = (code or "").lower()
    if code == "cc0":
        return "CC0 1.0"
    if code == "pdm":
        return "Public Domain Mark 1.0"
    return f"CC {code.upper()} {version}".strip()


class OpenverseSearch:
    name = "openverse"
    kinds = frozenset({"image"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        if kind != "image":
            return []
        params = {
            "q": query,
            "page_size": max(1, min(limit * 2, 40)),  # over-fetch: we filter below
            "license_type": "commercial,modification",  # no NC / ND
            "aspect_ratio": "tall" if orientation == "portrait" else "wide",
        }
        data = get_json(self.client, API_URL, params=params)
        out: list[MediaAsset] = []
        for r in data.get("results", []):
            url = r.get("url") or ""
            if not url.lower().split("?")[0].endswith(_OK_EXT):
                continue
            code = (r.get("license") or "").lower()
            label = license_label(code, r.get("license_version") or "")
            out.append(
                MediaAsset(
                    id=f"openverse:{r['id']}",
                    source="openverse",
                    kind="image",
                    url=url,
                    thumb_url=r.get("thumbnail") or "",
                    page_url=r.get("foreign_landing_url") or "",
                    width=int(r.get("width") or 0),
                    height=int(r.get("height") or 0),
                    title=r.get("title") or "",
                    tags=[t["name"] for t in r.get("tags") or [] if t.get("name")][:10],
                    license=label,
                    license_url=r.get("license_url") or "",
                    author=r.get("creator") or "",
                    author_url=r.get("creator_url") or "",
                    attribution=r.get("attribution") or f"{r.get('title', '')} ({label})",
                    attribution_required=code not in _NO_ATTRIBUTION,
                )
            )
            if len(out) >= limit:
                break
        return out

    def search_audio(self, query: str, category: str = "music", *, limit: int = 12) -> list[MediaAsset]:
        """Music or sound effects (`category`: "music" | "sound_effect") that may be used commercially and edited."""
        params = {"q": query, "page_size": max(1, min(limit * 2, 20)), "license_type": "commercial,modification"}  # anonymous use allows 20 per page
        if category == "music":
            params["category"] = "music"
        # sound effects are mostly not tagged with a category (they come from Freesound): take short, non-music results
        data = get_json(self.client, AUDIO_URL, params=params)
        out: list[MediaAsset] = []
        for r in data.get("results", []):
            url = r.get("url") or ""
            if not url.lower().startswith(("http://", "https://")):  # many audio links are streams without a file extension: the download is checked by content instead
                continue
            if category != "music" and (r.get("category") == "music" or (r.get("duration") or 0) > 30000):
                continue
            code = (r.get("license") or "").lower()
            label = license_label(code, r.get("license_version") or "")
            ms = r.get("duration")
            out.append(
                MediaAsset(
                    id=f"openverse:{r['id']}", source="openverse", kind="audio", url=url,
                    thumb_url=r.get("thumbnail") or "", page_url=r.get("foreign_landing_url") or "",
                    duration=(float(ms) / 1000.0) if ms else None, title=r.get("title") or "",
                    tags=[t["name"] for t in r.get("tags") or [] if t.get("name")][:10],
                    license=label, license_url=r.get("license_url") or "", author=r.get("creator") or "",
                    author_url=r.get("creator_url") or "",
                    attribution=r.get("attribution") or f"{r.get('title', '')} ({label})",
                    attribution_required=code not in _NO_ATTRIBUTION,
                )
            )
            if len(out) >= limit:
                break
        return out
