"""EBU R128 loudness normalisation (two-pass `loudnorm`).

Pass 1 measures the audio, pass 2 applies the exact gain (`linear=true`), which is more precise
and sounds more natural than the single-pass dynamic mode. -14 LUFS / -1.5 dBTP is the common
target for YouTube/social video.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from app.media import ffmpeg

log = logging.getLogger("avc.loudness")


def _loudnorm(target: float, tp: float, lra: float) -> str:
    return f"loudnorm=I={target}:TP={tp}:LRA={lra}"


def parse_loudnorm_json(stderr: str) -> dict:
    """loudnorm prints one JSON object at the end of its log output."""
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m:
        raise ffmpeg.FfmpegError("could not read loudnorm measurement from ffmpeg output")
    return json.loads(m.group(0))


def measure(path: Path, target: float = -14.0, tp: float = -1.5, lra: float = 11.0) -> dict:
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", _loudnorm(target, tp, lra) + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise ffmpeg.FfmpegError(f"loudness measurement failed: {p.stderr.strip()[-200:]}")
    return parse_loudnorm_json(p.stderr)


def normalize(src: Path, dst: Path, target: float = -14.0, tp: float = -1.5, lra: float = 11.0) -> Path:
    """Returns `dst`, or `src` unchanged if the audio is silent or normalising fails."""
    try:
        m = measure(src, target, tp, lra)
        if float(m["input_i"]) < -60:  # silence / near silence: boosting would only amplify noise
            log.warning("audio is almost silent (%s LUFS): not normalising", m["input_i"])
            return src
        af = (
            f"{_loudnorm(target, tp, lra)}:measured_I={m['input_i']}:measured_LRA={m['input_lra']}"
            f":measured_TP={m['input_tp']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true"
        )
        log.info("normalising loudness %.1f -> %.1f LUFS", float(m["input_i"]), target)
        ffmpeg.run(["-i", str(src), "-vn", "-af", af, "-ar", "48000", "-c:a", "flac", str(dst)])
        return dst
    except (ffmpeg.FfmpegError, KeyError, ValueError) as e:
        log.warning("loudness normalisation failed, using un-normalised audio: %s", e)
        return src
