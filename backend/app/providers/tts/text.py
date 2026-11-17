"""Splitting a script into pieces a voice model speaks well, and joining the audio back with natural pauses."""

from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

# sentence ends in English, Urdu (۔ ؟) and Arabic-script punctuation, plus line breaks
_SPLIT = re.compile(r"(?<=[.!?۔؟؛])\s+|\n+")


def sentences(text: str, max_chars: int = 220) -> list[str]:
    """Sentences, with any that are too long cut at commas/spaces (VITS voices get worse and slower on very long inputs)."""
    out: list[str] = []
    for part in _SPLIT.split(text.strip()):
        part = part.strip()
        while len(part) > max_chars:
            cut = max(part.rfind(c, 0, max_chars) for c in (",", "،", ";", " "))
            cut = cut if cut > max_chars // 3 else max_chars
            out.append(part[:cut].strip())
            part = part[cut:].strip(" ,،;")
        if part:
            out.append(part)
    return out


def write_wav(path: Path, pieces: list[np.ndarray], sample_rate: int, pause_s: float = 0.35) -> Path:
    """Concatenate float audio pieces with a pause between them and write a 16-bit mono WAV."""
    gap = np.zeros(int(sample_rate * pause_s), dtype=np.float32)
    parts: list[np.ndarray] = []
    for i, p in enumerate(pieces):
        if i:
            parts.append(gap)
        parts.append(np.asarray(p, dtype=np.float32).reshape(-1))
    audio = np.concatenate(parts) if parts else np.zeros(sample_rate // 10, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio / max(1.0, peak)  # never clip; loudness is set later by the pipeline's normaliser
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return path
