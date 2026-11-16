"""Looking at a media file before we accept it: what is it really, and is it within our limits?

* `sniff` recognises the file by its first bytes (never by the user's file name).
* `probe` asks ffprobe and extracts what the editor needs: kind, display size (after rotation),
  frame rate and whether it is variable, rotation, HDR, audio.
* `check_limits` enforces size/length/fps/pixel caps with messages meant for the user.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Kind = Literal["video", "audio", "image"]

# (extension we store it under, broad family) by signature. Only these are accepted.
SUPPORTED_DESCRIPTION = "mp4, mov, webm, mkv, mp3, wav, m4a, aac, flac, ogg/opus, png, jpg, webp"
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
_ALPHA_PIX = re.compile(r"(rgba|bgra|argb|abgr|yuva|gbrap|ya8|ya16|pal8)")


class MediaRejected(ValueError):
    """The file cannot be used. The message is safe to show to the user."""


@dataclass(frozen=True)
class Limits:
    max_minutes: float = 30.0
    max_megapixels: int = 64
    max_fps: int = 240


class MediaInfo(BaseModel):
    kind: Kind
    container: str  # ffprobe format name
    duration: float | None  # seconds; None for images
    width: int = 0  # as displayed (rotation applied)
    height: int = 0
    fps: float | None = None
    vfr: bool = False
    rotation: int = 0  # degrees the picture must be turned to look upright
    hdr: bool = False
    alpha: bool = False
    video_codec: str = ""
    pix_fmt: str = ""
    has_audio: bool = False
    audio_channels: int = 0
    audio_rate: int = 0
    size_bytes: int = 0


def sniff(path: Path) -> tuple[str, Kind | None] | None:
    """(extension to store as, family) from the file's first bytes, or None if not a supported media file.
    Family is None for containers that can hold audio or video (decided by `probe`)."""
    try:
        with path.open("rb") as f:
            head = f.read(64)
    except OSError:
        return None
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "mkv", None  # Matroska / WebM
    if head[4:8] == b"ftyp":
        return ("mov" if head[8:12] == b"qt  " else "mp4"), None
    if head[4:8] in (b"moov", b"mdat", b"wide", b"free"):
        return "mov", None  # old QuickTime without ftyp
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav", "audio"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp", "image"
    if head[:4] == b"fLaC":
        return "flac", "audio"
    if head[:4] == b"OggS":
        return "ogg", "audio"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg", "image"
    if head[:3] == b"ID3":
        return "mp3", "audio"
    if len(head) > 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return ("aac" if (head[1] & 0xF6) == 0xF0 else "mp3"), "audio"  # ADTS AAC vs MPEG audio
    return None


def _fraction(text: str | None) -> float | None:
    try:
        a, _, b = (text or "").partition("/")
        v = float(a) / float(b or 1)
        return v if v > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: Path, family: Kind | None = None, timeout: float = 30.0) -> MediaInfo:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise MediaRejected("Reading this file took too long.") from None
    if p.returncode != 0:
        raise MediaRejected("This file could not be read as audio, video or an image.")
    try:
        data = json.loads(p.stdout)
    except ValueError:
        raise MediaRejected("This file could not be read as audio, video or an image.") from None

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    # cover art inside an mp3/m4a shows up as a video stream: it is not video
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise MediaRejected("This file has no audio or video that can be used.")

    kind: Kind = "image" if (family == "image" and video is not None) else ("video" if video else "audio")
    info = MediaInfo(kind=kind, container=str(fmt.get("format_name", "")), duration=None,
                     size_bytes=int(fmt.get("size") or 0))
    try:
        dur = float(fmt.get("duration") or (video or audio or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    if kind != "image":
        if dur <= 0:
            raise MediaRejected("This file has no readable length.")
        info.duration = dur
    if audio is not None:
        info.has_audio = True
        info.audio_channels = int(audio.get("channels") or 0)
        info.audio_rate = int(audio.get("sample_rate") or 0)
    if video is not None:
        w, h = int(video.get("width") or 0), int(video.get("height") or 0)
        rotation = 0
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(round(float(sd["rotation"])))
        if rotation == 0 and (video.get("tags") or {}).get("rotate"):
            try:
                rotation = int(video["tags"]["rotate"])
            except ValueError:
                rotation = 0
        rotation = (-rotation) % 360  # ffprobe reports the matrix angle; this is the turn to apply
        if rotation in (90, 270):
            w, h = h, w
        info.width, info.height, info.rotation = w, h, rotation
        info.video_codec = str(video.get("codec_name", ""))
        info.pix_fmt = str(video.get("pix_fmt", ""))
        info.hdr = video.get("color_transfer") in _HDR_TRANSFERS
        info.alpha = bool(_ALPHA_PIX.search(info.pix_fmt))  # palette images may carry transparency too
        if kind == "video":
            avg, real = _fraction(video.get("avg_frame_rate")), _fraction(video.get("r_frame_rate"))
            info.fps = avg or real
            # phones record variable frame rate: the container's nominal rate differs from the real average
            info.vfr = bool(avg and real and abs(avg - real) / max(avg, real) > 0.02)
    return info


def check_limits(info: MediaInfo, limits: Limits) -> None:
    if info.duration is not None and info.duration > limits.max_minutes * 60:
        raise MediaRejected(f"This file is longer than {limits.max_minutes:g} minutes.")
    if info.kind in ("video", "image"):
        if info.width <= 0 or info.height <= 0:
            raise MediaRejected("This file has no readable picture size.")
        if info.width * info.height > limits.max_megapixels * 1_000_000:
            raise MediaRejected(f"The picture is larger than {limits.max_megapixels} megapixels.")
        if max(info.width, info.height) > 16384:
            raise MediaRejected("The picture is wider or taller than 16384 pixels.")
    if info.kind == "video" and info.fps and info.fps > limits.max_fps:
        raise MediaRejected(f"The frame rate ({info.fps:.0f} fps) is higher than {limits.max_fps} fps.")


def inspect_file(path: Path, limits: Limits) -> tuple[str, MediaInfo]:
    """Everything the upload path needs: (stored extension, validated info)."""
    kind = sniff(path)
    if kind is None:
        raise MediaRejected(f"This is not a supported file. Use {SUPPORTED_DESCRIPTION}.")
    ext, family = kind
    info = probe(path, family)
    check_limits(info, limits)
    return ext, info
