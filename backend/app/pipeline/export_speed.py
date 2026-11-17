"""How long an export takes: a rough estimate that learns from the exports this machine has really done.

Unit: seconds of work per second of video per megapixel of picture ("cost"). The defaults come from measurements on the
development Mac (software x264: 16.8 s for 12 s of 1080p; hardware about 5x quicker); every finished export replaces
the number for its encoder with a running average, so the estimate gets better on any machine."""

from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.sizes import render_size

DEFAULTS = {"software": 0.75, "hardware": 0.15}
OVERHEAD_S = {"software": 4.0, "hardware": 3.0}  # audio mix, loudness, concat, captions: roughly independent of the size


def _file(work_dir: str) -> Path:
    return Path(work_dir) / "cache" / "export_speed.json"


def _load(work_dir: str) -> dict:
    try:
        data = json.loads(_file(work_dir).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def megapixels(aspect: str, preset: str) -> float:
    w, h = render_size(aspect, "final", preset)
    return w * h / 1e6


def estimate(work_dir: str, encoder: str, preset: str, aspect: str, video_seconds: float) -> dict:
    learned = _load(work_dir).get(encoder)
    cost = float(learned) if isinstance(learned, (int, float)) and learned > 0 else DEFAULTS[encoder]
    seconds = OVERHEAD_S[encoder] + cost * video_seconds * megapixels(aspect, preset)
    return {"seconds": max(1, round(seconds)), "learned": isinstance(learned, (int, float)), "video_seconds": round(video_seconds, 1)}


def record(work_dir: str, encoder: str, preset: str, aspect: str, video_seconds: float, elapsed: float) -> None:
    """Remember what a finished export cost (ignore silly numbers: a very short video says nothing)."""
    if video_seconds < 3 or elapsed <= 0:
        return
    cost = max(0.0, elapsed - OVERHEAD_S[encoder]) / (video_seconds * megapixels(aspect, preset))
    if cost <= 0:
        return
    data = _load(work_dir)
    old = data.get(encoder)
    data[encoder] = round(cost if not isinstance(old, (int, float)) else 0.5 * old + 0.5 * cost, 4)
    try:
        f = _file(work_dir)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), "utf-8")
    except OSError:
        pass
