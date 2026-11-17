"""Cartoon avatars drawn with Pillow whose mouth follows the loudness of the narration. CPU only, a few seconds for a minute of speech."""

from __future__ import annotations

from app import fsutil

import io
import random
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.media import ffmpeg
from app.providers.avatar_renderer import KEY_COLOUR, AvatarInfo, AvatarUnavailable

SIZE = 512
SS = 2  # draw at twice the size and shrink: smooth edges
FPS = 30


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    skin: str
    hair: str
    shirt: str
    style: str  # "short" | "long" | "bald" | "robot"
    accent: str = "#ffffff"


CHARACTERS = {c.id: c for c in (
    Character("sara", "Sara", "#e9b98f", "#3a2a22", "#2f6fb3", "long"),
    Character("ali", "Ali", "#c98e63", "#1d1a19", "#2e8b57", "short"),
    Character("nomi", "Nomi (robot)", "#aeb9c9", "#5b6577", "#c2492f", "robot", "#ffd34d"),
)}


def _hex(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def draw(ch: Character, mouth: int, blink: bool, bob: int, background: str = KEY_COLOUR) -> Image.Image:
    """One frame. mouth: 0 closed .. 3 wide open; bob: head offset in pixels (0..4)."""
    s = SIZE * SS
    img = Image.new("RGB", (s, s), _hex(background))
    d = ImageDraw.Draw(img)
    u = s / 512
    cx, base = s / 2, s - 40 * u
    skin, hair, shirt = _hex(ch.skin), _hex(ch.hair), _hex(ch.shirt)
    # shoulders and neck
    d.rounded_rectangle([cx - 190 * u, base - 130 * u, cx + 190 * u, s + 80 * u], radius=90 * u, fill=shirt)
    d.rectangle([cx - 38 * u, base - 190 * u, cx + 38 * u, base - 110 * u], fill=tuple(int(v * 0.9) for v in skin))
    top = 60 * u + bob * u
    head = [cx - 120 * u, top + 40 * u, cx + 120 * u, top + 330 * u]
    if ch.style == "long":
        d.rounded_rectangle([cx - 150 * u, top + 10 * u, cx + 150 * u, top + 400 * u], radius=120 * u, fill=hair)
    if ch.style != "robot":
        d.ellipse(head, fill=skin)
        if ch.style in ("long", "short"):
            d.pieslice([cx - 132 * u, top + 15 * u, cx + 132 * u, top + 250 * u], 180, 360, fill=hair)
    else:  # a rounded square head with an antenna
        d.rounded_rectangle(head, radius=60 * u, fill=skin)
        d.line([cx, top + 40 * u, cx, top - 10 * u], fill=hair, width=int(8 * u))
        d.ellipse([cx - 14 * u, top - 34 * u, cx + 14 * u, top - 6 * u], fill=_hex(ch.accent))
    ey = top + 160 * u
    for sx in (-1, 1):
        ex = cx + sx * 52 * u
        if blink:
            d.line([ex - 22 * u, ey, ex + 22 * u, ey], fill=(40, 30, 30), width=int(7 * u))
        else:
            d.ellipse([ex - 22 * u, ey - 22 * u, ex + 22 * u, ey + 22 * u], fill=(255, 255, 255))
            d.ellipse([ex - 11 * u, ey - 11 * u, ex + 11 * u, ey + 11 * u], fill=(30, 25, 30))
        d.line([ex - 28 * u, ey - 42 * u, ex + 28 * u, ey - 48 * u], fill=hair if ch.style != "robot" else (60, 70, 85), width=int(8 * u))
    d.polygon([(cx, ey + 10 * u), (cx - 12 * u, ey + 60 * u), (cx + 12 * u, ey + 60 * u)], fill=tuple(int(v * 0.85) for v in skin))
    my = top + 262 * u
    lip = (150, 55, 60)
    if mouth == 0:
        d.arc([cx - 40 * u, my - 22 * u, cx + 40 * u, my + 18 * u], 20, 160, fill=lip, width=int(7 * u))
    else:
        h = (10, 24, 40, 56)[mouth] * u
        w = (0, 40, 46, 38)[mouth] * u
        d.ellipse([cx - w, my - h / 2, cx + w, my + h / 2], fill=(90, 25, 35), outline=lip, width=int(6 * u))
        if mouth >= 2:
            d.rectangle([cx - w * 0.6, my - h / 2 + 4 * u, cx + w * 0.6, my - h / 2 + 12 * u], fill=(250, 250, 250))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def loudness(audio: Path, fps: int = FPS) -> np.ndarray:
    """Loudness 0..1 for every video frame of `audio` (smoothed, quiet noise ignored)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    if p.returncode != 0:
        raise AvatarUnavailable("The narration could not be read as audio.")
    x = np.frombuffer(p.stdout, dtype="<f4")
    if x.size == 0:
        return np.zeros(1)
    per = 16000 // fps
    n = max(1, x.size // per)
    rms = np.sqrt(np.mean(x[: n * per].reshape(n, per) ** 2, axis=1))
    ref = max(float(np.percentile(rms, 95)), 1e-4)
    env = np.clip(rms / ref, 0, 1.3)
    env[env < 0.12] = 0.0  # breathing and background noise do not move the mouth
    k = np.array([0.25, 0.5, 0.25])
    return np.convolve(np.pad(env, 1, mode="edge"), k, mode="valid")


def mouth_levels(env: np.ndarray) -> list[int]:
    """Envelope -> mouth shape per frame; a shape is held for at least two frames so the mouth does not flutter."""
    raw = [0 if v < 0.12 else 1 if v < 0.35 else 2 if v < 0.7 else 3 for v in env]
    out: list[int] = []
    for i, m in enumerate(raw):
        if out and i >= 1 and out[-1] != m and i >= 2 and out[-2] != out[-1]:
            m = out[-1]  # the previous change is too recent
        out.append(m)
    return out


def blink_frames(n: int, seed: int = 7) -> set[int]:
    rng = random.Random(seed)
    frames: set[int] = set()
    t = rng.randint(45, 90)
    while t < n:
        frames.update(range(t, min(n, t + 4)))
        t += rng.randint(75, 150)
    return frames


class SimpleAvatars:
    def avatars(self) -> list[AvatarInfo]:
        return [AvatarInfo(c.id, c.name) for c in CHARACTERS.values()]

    def _character(self, avatar_id: str) -> Character:
        if avatar_id not in CHARACTERS:
            raise AvatarUnavailable(f"There is no avatar called '{avatar_id}'.")
        return CHARACTERS[avatar_id]

    def thumbnail(self, avatar_id: str) -> bytes:
        buf = io.BytesIO()
        draw(self._character(avatar_id), 1, False, 0, background="#e8ecf3").resize((192, 192), Image.LANCZOS).save(buf, "PNG")
        return buf.getvalue()

    def render(self, avatar_id: str, audio: Path, out: Path, progress: Callable[[float], None] | None = None) -> Path:
        ch = self._character(avatar_id)
        env = loudness(audio)
        levels = mouth_levels(env)
        blinks = blink_frames(len(levels))
        cache: dict[tuple[int, bool, int], bytes] = {}
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SIZE}x{SIZE}", "-r", str(FPS), "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(part)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert proc.stdin is not None
            for i, m in enumerate(levels):
                key = (m, i in blinks, min(4, int(env[i] * 4)) if m else 0)  # the head rises a little with the loudest syllables
                if key not in cache:
                    cache[key] = draw(ch, key[0], key[1], key[2]).tobytes()
                proc.stdin.write(cache[key])
                if progress and i % 60 == 0:
                    progress(i / len(levels))
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            if proc.wait() != 0:
                raise ffmpeg.FfmpegError(f"encoding the avatar failed: {err[-300:]}")
        except BaseException:
            proc.kill()
            part.unlink(missing_ok=True)
            raise
        fsutil.replace(part, out)
        return out
