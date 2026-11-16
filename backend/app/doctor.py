"""Environment checks behind `avc doctor`. Pure functions so they can be unit-tested."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import ROOT, Settings
from app.media import ffmpeg

# host label -> URL that answers without an API key (any HTTP response means "reachable")
NETWORK_TARGETS = {
    "Pixabay": "https://pixabay.com/",
    "Openverse": "https://api.openverse.org/v1/",
    "Wikimedia Commons": "https://commons.wikimedia.org/w/api.php",
    "Gemini": "https://generativelanguage.googleapis.com/",
}


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str = ""


def _font_present(fonts_dir: Path, needle: str) -> bool:
    return fonts_dir.is_dir() and any(needle in f.name.lower() for f in fonts_dir.iterdir())


def check_network(timeout: float = 8.0) -> list[Check]:
    out = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for label, url in NETWORK_TARGETS.items():
            try:
                client.get(url)
                out.append(Check(f"network: {label}", "ok"))
            except httpx.HTTPError as e:
                out.append(Check(f"network: {label}", "warn", f"unreachable ({type(e).__name__})"))
    return out


def run_checks(s: Settings, network: bool = True) -> list[Check]:
    c: list[Check] = []
    v = sys.version_info
    c.append(Check("python >= 3.11", "ok" if v >= (3, 11) else "fail", f"{v.major}.{v.minor}.{v.micro}"))

    have_ff = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    c.append(Check("ffmpeg + ffprobe", "ok" if have_ff else "fail", "" if have_ff else "brew install ffmpeg"))
    if have_ff:
        has_ass = ffmpeg.has_filter("subtitles")
        c.append(Check("ffmpeg libass (captions)", "ok" if has_ass else "fail",
                       "" if has_ass else "ffmpeg lacks the 'subtitles' filter"))

    c.append(Check(".env file", "ok" if (ROOT / ".env").exists() else "warn", str(ROOT / ".env")))
    c.append(Check("PIXABAY_API_KEY", "ok" if s.pixabay_api_key else "warn",
                   "" if s.pixabay_api_key else "only Openverse/Wikimedia (images) without it"))
    c.append(Check("GEMINI_API_KEY", "ok" if s.gemini_api_key else "warn",
                   "" if s.gemini_api_key else "needed for Urdu; English can use SCENE_PLANNER=heuristic"))
    c.append(Check("PEXELS_API_KEY (optional)", "ok" if s.pexels_api_key else "ok",
                   "set" if s.pexels_api_key else "not set: Pexels is skipped"))

    model = Path(s.models_dir) / s.rnnoise_model
    c.append(Check("RNNoise denoise model", "ok" if model.is_file() else "warn",
                   "" if model.is_file() else "run `avc fetch-models`; until then noise removal uses afftdn"))

    fonts = Path(s.fonts_dir)
    c.append(Check("font: Noto Nastaliq Urdu (default)",
                   "ok" if _font_present(fonts, "nastaliq") else "warn", f"put the .ttf in {fonts}"))
    c.append(Check("font: Jameel Noori Nastaleeq (optional)",
                   "ok" if _font_present(fonts, "jameel") else "ok",
                   "found" if _font_present(fonts, "jameel") else "not installed (optional)"))

    if network:
        c.extend(check_network())
    return c
