"""Wikimedia Commons images. No API key needed."""

from __future__ import annotations

import html
import re

import httpx

from app.http import get_json, make_client
from app.models import MediaAsset, MediaKind

API_URL = "https://commons.wikimedia.org/w/api.php"
_OK_MIME = {"image/jpeg", "image/png", "image/webp"}
_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", s or ""))).strip()


class WikimediaSearch:
    name = "wikimedia"
    kinds = frozenset({"image"})

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or make_client()

    def search(
        self, query: str, kind: MediaKind, *, orientation: str = "landscape", limit: int = 10
    ) -> list[MediaAsset]:
        if kind != "image":
            return []
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6,  # File:
            "gsrlimit": max(1, min(limit * 2, 30)),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 1920,
            "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|AttributionRequired",
        }
        data = get_json(self.client, API_URL, params=params)
        pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        out: list[MediaAsset] = []
        for p in pages:
            asset = self._parse(p)
            if asset:
                out.append(asset)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _parse(p: dict) -> MediaAsset | None:
        infos = p.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        if info.get("mime") not in _OK_MIME:
            return None
        meta = info.get("extmetadata") or {}

        def m(key: str) -> str:
            return strip_html((meta.get(key) or {}).get("value", ""))

        license_name = m("LicenseShortName")
        if not license_name:  # unknown license -> we cannot prove it is reusable
            return None
        title = p.get("title", "").removeprefix("File:")
        artist = m("Artist") or m("Credit") or "Unknown author"
        page = info.get("descriptionurl", "")
        required = m("AttributionRequired").lower() != "false"
        download = info.get("thumburl") or info.get("url")
        return MediaAsset(
            id=f"wikimedia:{p['pageid']}",
            source="wikimedia",
            kind="image",
            url=download,
            thumb_url=info.get("thumburl", ""),
            page_url=page,
            width=int(info.get("thumbwidth") or info.get("width") or 0),
            height=int(info.get("thumbheight") or info.get("height") or 0),
            title=title,
            license=license_name,
            license_url=m("LicenseUrl"),
            author=artist,
            attribution=f'"{title}" by {artist}, {license_name}, via Wikimedia Commons ({page})',
            attribution_required=required,
        )
