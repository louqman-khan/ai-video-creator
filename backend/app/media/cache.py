from __future__ import annotations

from app import fsutil

import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx

from app.http import HttpError, make_client, safe_url
from app.media.ingest import sniff
from app.models import MediaAsset


def _ext(asset: MediaAsset) -> str:
    suffix = Path(urlparse(asset.url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix
    return {"video": ".mp4", "audio": ".mp3"}.get(asset.kind, ".jpg")


class MediaCache:
    def __init__(self, folder: Path, client: httpx.Client | None = None) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.client = client or make_client()

    def path_for(self, asset: MediaAsset) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", asset.id)
        return self.folder / f"{safe}{_ext(asset)}"

    def get(self, asset: MediaAsset) -> Path:
        dst = self.path_for(asset)
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        if asset.url.startswith("file:"):  # user-provided local media
            shutil.copyfile(url2pathname(unquote(urlparse(asset.url).path)), dst)
            return self._accept(dst)
        part = dst.with_suffix(dst.suffix + ".part")
        try:
            with self.client.stream("GET", asset.url) as r:
                if r.is_error:
                    raise HttpError(f"HTTP {r.status_code} downloading {safe_url(asset.url)}")
                with part.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            fsutil.replace(part, dst)
        finally:
            part.unlink(missing_ok=True)
        return self._accept(dst)

    @staticmethod
    def _accept(path: Path) -> Path:
        """A host can answer 200 with a web page or anything else: keep only real media files."""
        if sniff(path) is None:
            path.unlink(missing_ok=True)
            raise ValueError("the downloaded file is not a supported image, video or audio file")
        return path
