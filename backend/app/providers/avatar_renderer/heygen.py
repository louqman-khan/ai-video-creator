"""HeyGen talking avatars: a PAID cloud service (a video costs credits), only used when AVATAR_RENDERER=heygen and HEYGEN_API_KEY is set.

Written from HeyGen's public API description (list avatars, upload an audio asset, generate a video with that audio over a solid green
background, poll the status, download). It has been exercised with mocked HTTP only, never with a live account, so expect to adjust field
names if HeyGen changed them."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from app.http import make_client
from app.providers.avatar_renderer import KEY_COLOUR, AvatarInfo, AvatarUnavailable

API = "https://api.heygen.com"
UPLOAD = "https://upload.heygen.com/v1/asset"
MAX_AVATARS = 24
POLL_S = 5.0
TIMEOUT_S = 20 * 60


class HeygenAvatars:
    paid = True

    def __init__(self, api_key: str, poll_s: float = POLL_S, timeout_s: float = TIMEOUT_S) -> None:
        self.key, self.poll_s, self.timeout_s = api_key, poll_s, timeout_s
        self._listed: tuple[float, list[dict]] | None = None

    def _client(self, timeout: float = 30.0) -> httpx.Client:
        if not self.key:
            raise AvatarUnavailable("HEYGEN_API_KEY is not set (see docs/paid-providers.md).")
        c = make_client(read_timeout=timeout)
        c.headers.update({"X-Api-Key": self.key})
        return c

    def _list(self) -> list[dict]:
        if self._listed and time.time() - self._listed[0] < 600:
            return self._listed[1]
        with self._client() as c:
            r = c.get(f"{API}/v2/avatars")
            r.raise_for_status()
            items = [a for a in (r.json().get("data") or {}).get("avatars", []) if a.get("avatar_id")][:MAX_AVATARS]
        self._listed = (time.time(), items)
        return items

    def avatars(self) -> list[AvatarInfo]:
        try:
            return [AvatarInfo(str(a["avatar_id"]), str(a.get("avatar_name") or a["avatar_id"])) for a in self._list()]
        except (httpx.HTTPError, ValueError, AvatarUnavailable):
            return []

    def thumbnail(self, avatar_id: str) -> bytes:
        item = next((a for a in self._list() if a["avatar_id"] == avatar_id), None) if self.key else None
        url = (item or {}).get("preview_image_url")
        if not url:
            raise AvatarUnavailable("This avatar has no preview picture.")
        try:
            with make_client(read_timeout=20.0) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.content
        except httpx.HTTPError:
            raise AvatarUnavailable("The avatar's preview picture could not be loaded.") from None

    def render(self, avatar_id: str, audio: Path, out: Path, progress: Callable[[float], None] | None = None) -> Path:
        if not self.key:
            raise AvatarUnavailable("HEYGEN_API_KEY is not set (see docs/paid-providers.md).")
        mp3 = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-vn", "-ac", "1", "-ar", "44100", "-b:a", "128k", "-f", "mp3", "-"], capture_output=True)
        if mp3.returncode != 0 or not mp3.stdout:
            raise AvatarUnavailable("The narration could not be read as audio.")
        try:
            with self._client(120.0) as c:
                up = c.post(UPLOAD, content=mp3.stdout, headers={"Content-Type": "audio/mpeg"})
                up.raise_for_status()
                asset_id = (up.json().get("data") or {}).get("id")
                if not asset_id:
                    raise AvatarUnavailable("HeyGen did not accept the audio upload.")
                gen = c.post(f"{API}/v2/video/generate", json={
                    "video_inputs": [{"character": {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"},
                                      "voice": {"type": "audio", "audio_asset_id": asset_id},
                                      "background": {"type": "color", "value": KEY_COLOUR}}],
                    "dimension": {"width": 720, "height": 720}})
                gen.raise_for_status()
                video_id = (gen.json().get("data") or {}).get("video_id")
                if not video_id:
                    raise AvatarUnavailable("HeyGen did not start the video.")
                deadline = time.time() + self.timeout_s
                while True:
                    st = c.get(f"{API}/v1/video_status.get", params={"video_id": video_id})
                    st.raise_for_status()
                    data = st.json().get("data") or {}
                    if data.get("status") == "completed" and data.get("video_url"):
                        url = data["video_url"]
                        break
                    if data.get("status") == "failed":
                        raise AvatarUnavailable("HeyGen could not make the video.")
                    if time.time() > deadline:
                        raise AvatarUnavailable("HeyGen took too long (over 20 minutes).")
                    if progress:
                        progress(0.5)
                    time.sleep(self.poll_s)
            with make_client(read_timeout=300.0) as d:  # the finished video sits on a signed address: no key is sent there
                v = d.get(url)
                v.raise_for_status()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            raise AvatarUnavailable("HeyGen refused the key (HTTP %d)." % code if code in (401, 403) else f"HeyGen answered with an error (HTTP {code}).") from None
        except httpx.HTTPError:
            raise AvatarUnavailable("HeyGen could not be reached.") from None
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part.mp4")
        part.write_bytes(v.content)
        part.replace(out)
        return out
