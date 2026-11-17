"""A GPU avatar service over HTTP (see docs/avatars.md for the protocol). Not verified against a real GPU model."""

from __future__ import annotations

from app import fsutil

from collections.abc import Callable
from pathlib import Path

import httpx

from app.http import make_client
from app.providers.avatar_renderer import AvatarInfo, AvatarUnavailable


class RemoteAvatars:
    def __init__(self, url: str, token: str = "") -> None:
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _client(self, timeout: float) -> httpx.Client:
        if not self.url.startswith(("http://", "https://")):
            raise AvatarUnavailable("AVATAR_URL is not set (see docs/avatars.md).")
        c = make_client(read_timeout=timeout)
        c.headers.update(self.headers)
        return c

    def avatars(self) -> list[AvatarInfo]:
        try:
            with self._client(10) as c:
                r = c.get(f"{self.url}/avatars")
                r.raise_for_status()
                return [AvatarInfo(str(a["id"]), str(a.get("name") or a["id"])) for a in r.json()]
        except (httpx.HTTPError, ValueError, KeyError, AvatarUnavailable):
            return []

    def thumbnail(self, avatar_id: str) -> bytes:
        try:
            with self._client(20) as c:
                r = c.get(f"{self.url}/avatars/{avatar_id}/thumb")
                r.raise_for_status()
                return r.content
        except httpx.HTTPError:
            raise AvatarUnavailable("The avatar service could not be reached.") from None

    def render(self, avatar_id: str, audio: Path, out: Path, progress: Callable[[float], None] | None = None) -> Path:
        try:
            with self._client(1800) as c, audio.open("rb") as f:
                r = c.post(f"{self.url}/render", data={"avatar": avatar_id}, files={"audio": (audio.name, f, "audio/wav")})
                r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AvatarUnavailable(f"The avatar service refused the job (HTTP {e.response.status_code}).") from None
        except httpx.HTTPError:
            raise AvatarUnavailable("The avatar service could not be reached or timed out.") from None
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part.mp4")
        part.write_bytes(r.content)
        fsutil.replace(part, out)
        return out
