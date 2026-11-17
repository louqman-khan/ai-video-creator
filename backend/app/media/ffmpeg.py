from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from app.config import ROOT

# A project-local ffmpeg (<repo>/tools/bin) wins over the system one, so the app works on
# machines where installing ffmpeg system-wide is impractical (e.g. old macOS + Homebrew).
_LOCAL_BIN = ROOT / "tools" / "bin"
if _LOCAL_BIN.is_dir():
    os.environ["PATH"] = f"{_LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"


class FfmpegError(RuntimeError):
    pass


def has_tools() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise FfmpegError(f"{tool} not found. Run `avc fetch-ffmpeg` (downloads a static build into tools/bin), or install ffmpeg yourself (macOS: brew install ffmpeg; Windows: winget install Gyan.FFmpeg) and make sure it is on PATH")


def run(args: list[str], cwd: Path | None = None, timeout: float | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise FfmpegError(f"ffmpeg did not finish within {timeout:.0f} s and was stopped") from None
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-8:])
        raise FfmpegError(f"ffmpeg failed ({p.returncode}):\n{tail}")


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise FfmpegError(f"ffprobe could not read {path.name}: {p.stderr.strip()[-200:]}")
    return float(json.loads(p.stdout)["format"]["duration"])


def has_filter(name: str) -> bool:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return any(line.split()[1:2] == [name] for line in p.stdout.splitlines())


# Hardware H.264 encoders by platform: Apple VideoToolbox (macOS), NVIDIA NVENC, Intel Quick Sync, AMD AMF (Windows/Linux).
HARDWARE_ENCODERS = ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf")


def _encodes(name: str) -> bool:
    """Being listed by ffmpeg is not enough (a build can list NVENC on a computer without an NVIDIA card): really encode a few frames."""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=0.2", "-c:v", name,
                            "-pix_fmt", "yuv420p", "-frames:v", "3", "-f", "null", "-"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


_hardware: dict[str, str | None] = {}


def hardware_encoder() -> str | None:
    """The first hardware H.264 encoder that works on this computer (None if there is none). The answer is remembered."""
    if "name" not in _hardware:
        _hardware["name"] = next((n for n in HARDWARE_ENCODERS if has_encoder(n) and _encodes(n)), None) if has_tools() else None
    return _hardware["name"]


def has_encoder(name: str) -> bool:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return any(line.split()[1:2] == [name] for line in p.stdout.splitlines())


def filter_escape(value: str) -> str:
    """Escape a path/value for use inside a single-quoted ffmpeg filter option."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
