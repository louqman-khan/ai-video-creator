"""Files the editor derives from every asset (task 4.2). Originals are never modified.

* proxy video   960x540 box, constant 30 fps, a keyframe every 0.5 s (decision D3: this is what makes
                scrubbing fast: median 21 ms vs 169 ms without it), rotation applied, HDR tone-mapped
* proxy image   max 1280 px wide (PNG when it has transparency)
* proxy audio   AAC stereo 48 kHz, played next to the muted video proxy
* peaks.json    waveform: 100 and 10 peaks per second, 0-255
* film.jpg      filmstrip sprite for the timeline (160x90 thumbnails in one row) + film.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.media import ffmpeg
from app.media.ingest import MediaInfo

log = logging.getLogger("avc.derive")

VERSION = 1
FPS = 30
GOP = 15  # a keyframe every 0.5 s at 30 fps
THUMB_W, THUMB_H = 160, 90
MAX_THUMBS = 120
PEAK_RATE = 100  # peaks per second (finest level)

# HDR -> SDR (HLG/PQ to bt709): used for the 8-bit proxy and, identically, by the renderer for exports.
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv")


def asset_key(path: Path) -> str:
    """Stable id of a file's content-ish identity: same file untouched = same derived files."""
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def film_layout(duration: float) -> tuple[float, int]:
    """(seconds between thumbnails, number of thumbnails): never more than MAX_THUMBS+1."""
    interval = max(0.5, duration / MAX_THUMBS)
    return interval, int(duration // interval) + 1


def _timeout(info: MediaInfo, factor: float = 4.0) -> float:
    return 120 + factor * (info.duration or 1)


def make_video_proxy(src: Path, info: MediaInfo, dst: Path) -> None:
    box_w, box_h = (960, 540) if info.width >= info.height else (540, 960)
    # fit inside the box, never enlarge: the box is capped at the picture's own (rotated) size
    chain = [f"scale=w='min(iw,{box_w})':h='min(ih,{box_h})':force_original_aspect_ratio=decrease:force_divisible_by=2"]
    if info.hdr:
        chain.append(TONEMAP)
    chain += [f"fps={FPS}", "format=yuv420p"]  # constant frame rate: variable-rate phone video becomes steady
    ffmpeg.run(
        ["-i", str(src), "-map", "0:v:0", "-an", "-vf", ",".join(chain),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", str(GOP), "-keyint_min", str(GOP),
         "-sc_threshold", "0", "-movflags", "+faststart", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", str(dst)],
        timeout=_timeout(info),
    )  # ffmpeg applies the rotation flag itself while decoding, so the proxy is upright


def make_audio_proxy(src: Path, info: MediaInfo, dst: Path) -> None:
    ffmpeg.run(["-i", str(src), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "128k",
                "-map_metadata", "-1", str(dst)], timeout=_timeout(info, 2.0))


def make_image_proxy(src: Path, info: MediaInfo, dst: Path) -> None:
    quality = [] if info.alpha else ["-q:v", "3"]
    ffmpeg.run(["-i", str(src), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", *quality, str(dst)], timeout=120)


def make_peaks(src: Path, info: MediaInfo, dst: Path) -> None:
    """Waveform peaks from 8 kHz mono PCM: 80 samples per peak = 100 peaks per second."""
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True, timeout=_timeout(info, 2.0),
    )
    if p.returncode != 0:
        raise ffmpeg.FfmpegError("could not decode the audio for the waveform")
    samples = np.frombuffer(p.stdout[: len(p.stdout) // 2 * 2], dtype="<i2")
    per = 8000 // PEAK_RATE
    n = len(samples) // per * per
    fine = (np.abs(samples[:n].astype(np.int32)).reshape(-1, per).max(axis=1) if n else np.zeros(0, dtype=np.int32))
    fine = np.minimum(255, (fine * 255 + 16383) // 32767).astype(int)
    pad = (-len(fine)) % 10
    coarse = np.concatenate([fine, np.zeros(pad, dtype=int)]).reshape(-1, 10).max(axis=1) if len(fine) else fine
    dst.write_text(json.dumps({"version": 1, "duration": info.duration, "rates": {"100": fine.tolist(), "10": coarse.tolist()}},
                              separators=(",", ":")), "utf-8")


def make_film(src: Path, info: MediaInfo, dst: Path, meta: Path) -> None:
    interval, count = film_layout(info.duration or 0.5)
    vf = (f"fps=1/{interval:.4f},scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease,"
          f"pad={THUMB_W}:{THUMB_H}:(ow-iw)/2:(oh-ih)/2,tile={count}x1")
    ffmpeg.run(["-i", str(src), "-map", "0:v:0", "-an", "-vf", vf, "-frames:v", "1", "-q:v", "5", str(dst)], timeout=_timeout(info, 3.0))
    meta.write_text(json.dumps({"interval": interval, "count": count, "thumb_width": THUMB_W, "thumb_height": THUMB_H}), "utf-8")


def derive_all(src: Path, info: MediaInfo, out: Path, on_step: Callable[[str], None] | None = None) -> dict[str, str]:
    """Create every derived file the asset needs in `out`; returns {role: file name}."""
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def step(name: str, fn, *args):
        if on_step:
            on_step(name)
        fn(*args)

    if info.kind == "video":
        step("proxy", make_video_proxy, src, info, out / "proxy.mp4"); files["proxy"] = "proxy.mp4"
        step("filmstrip", make_film, src, info, out / "film.jpg", out / "film.json"); files.update(film="film.jpg", film_meta="film.json")
    elif info.kind == "image":
        name = "proxy.png" if info.alpha else "proxy.jpg"
        step("proxy", make_image_proxy, src, info, out / name); files["proxy"] = name
    if info.has_audio:
        step("audio", make_audio_proxy, src, info, out / "proxy_audio.m4a"); files["audio"] = "proxy_audio.m4a"
        step("waveform", make_peaks, src, info, out / "peaks.json"); files["peaks"] = "peaks.json"
    (out / "info.json").write_text(info.model_dump_json(), "utf-8")
    return files
