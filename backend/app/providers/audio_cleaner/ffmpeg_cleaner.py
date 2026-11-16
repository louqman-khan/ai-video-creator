"""Noise removal with FFmpeg only (no PyTorch, works on any Mac/CPU).

* with the RNNoise speech model (`arnndn`, downloaded by `avc fetch-models`): neural denoise
* without it: `afftdn` spectral denoise

Both are preceded by a gentle 80 Hz high-pass (rumble, handling noise). Duration is unchanged,
so word timestamps from the original audio stay valid. Any failure returns the original audio:
cleaning must never kill a run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.media import ffmpeg

log = logging.getLogger("avc.audio")


def build_filter(model: Path | None) -> str:
    chain = ["highpass=f=80"]
    if model and model.is_file():
        chain.append(f"arnndn=m='{ffmpeg.filter_escape(str(model))}'")
    else:
        # tn=1 (adaptive noise tracking) measurably did nothing; a fixed floor works. Measured on
        # speech + white noise: pause level -32.6 -> -48.6 dB, speech level moved only 0.3 dB.
        chain.append("afftdn=nr=18:nf=-30:tn=0")
    return ",".join(chain)


class FfmpegCleaner:
    def __init__(self, model: Path | None = None) -> None:
        self.model = model

    @property
    def method(self) -> str:
        return "rnnoise" if self.model and self.model.is_file() else "afftdn"

    def clean(self, src: Path, dst: Path) -> Path:
        try:
            log.info("cleaning audio (%s)", self.method)
            ffmpeg.run(["-i", str(src), "-vn", "-af", build_filter(self.model), "-c:a", "flac", str(dst)])
            return dst
        except ffmpeg.FfmpegError as e:
            log.warning("audio cleaning failed, using the original audio: %s", e)
            return src
