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


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise FfmpegError(f"{tool} not found on PATH. Install it with: brew install ffmpeg, or put static ffmpeg/ffprobe in tools/bin")


def run(args: list[str], cwd: Path | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-8:])
        raise FfmpegError(f"ffmpeg failed ({p.returncode}):\n{tail}")


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise FfmpegError(f"ffprobe could not read {path.name}: {p.stderr.strip()[-200:]}")
    return float(json.loads(p.stdout)["format"]["duration"])


def has_filter(name: str) -> bool:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in p.stdout.splitlines())


def filter_escape(value: str) -> str:
    """Escape a path/value for use inside a single-quoted ffmpeg filter option."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
