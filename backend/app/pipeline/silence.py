"""Silence / gap removal driven by word timestamps (Whisper already ran VAD on the audio).

Every pause between words that is at least `min_gap` long is shortened to `keep_gap` (half kept
on each side, so no word is clipped). Cutting audio shifts everything after the cut, so the same
cut list is used to remap the transcript: scenes, captions and visuals are then built on the new
timeline and stay in sync by construction.
"""

from __future__ import annotations

from pathlib import Path

from app.media import ffmpeg
from app.models import Segment, Transcript, Word

Cut = tuple[float, float]  # (start, end) seconds of the ORIGINAL audio that is removed
FADE_S = 0.005  # tiny fade at each join, avoids clicks


def plan_cuts(words: list[Word], duration: float, min_gap: float = 0.8, keep_gap: float = 0.4) -> list[Cut]:
    if min_gap <= keep_gap:
        raise ValueError("min_gap must be larger than keep_gap")
    words = sorted((w for w in words if w.text.strip()), key=lambda w: w.start)
    if not words:
        return []
    half = keep_gap / 2
    cuts: list[Cut] = []
    # (end of previous word, start of next word); the start/end of the audio count as gaps too
    edges = [(0.0, words[0].start)]
    edges += [(a.end, b.start) for a, b in zip(words, words[1:])]
    edges += [(max(w.end for w in words), duration)]
    for g0, g1 in edges:
        if g1 - g0 >= min_gap:
            lo = g0 + (half if g0 > 0 else 0.0)  # keep `half` next to a word, none before the very start
            hi = g1 - (half if g1 < duration else 0.0)
            if hi - lo > 0.05:
                cuts.append((round(lo, 3), round(hi, 3)))
    return cuts


def remap_time(t: float, cuts: list[Cut]) -> float:
    removed = 0.0
    for a, b in cuts:
        if t >= b:
            removed += b - a
        elif t > a:
            removed += t - a  # inside a cut: collapse onto its start
            break
        else:
            break
    return max(0.0, t - removed)


def remap_transcript(t: Transcript, cuts: list[Cut]) -> Transcript:
    def rw(w: Word) -> Word:
        return w.model_copy(update={"start": round(remap_time(w.start, cuts), 3),
                                    "end": round(remap_time(w.end, cuts), 3)})

    segments = [
        Segment(text=s.text, start=round(remap_time(s.start, cuts), 3), end=round(remap_time(s.end, cuts), 3),
                words=[rw(w) for w in s.words])
        for s in t.segments
    ]
    return Transcript(language=t.language, duration=round(remap_time(t.duration, cuts), 3), segments=segments)


def kept_intervals(cuts: list[Cut], duration: float) -> list[Cut]:
    out, pos = [], 0.0
    for a, b in cuts:
        if a > pos:
            out.append((pos, a))
        pos = b
    if pos < duration:
        out.append((pos, duration))
    return out


def build_cut_filter(cuts: list[Cut], duration: float) -> str:
    parts, labels = [], []
    for i, (a, b) in enumerate(kept_intervals(cuts, duration)):
        d = b - a
        f = min(FADE_S, d / 2)
        parts.append(
            f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:d={f:.3f},afade=t=out:st={max(0.0, d - f):.3f}:d={f:.3f}[a{i}]"
        )
        labels.append(f"[a{i}]")
    return ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"


def cut_audio(src: Path, dst: Path, cuts: list[Cut], duration: float) -> Path:
    ffmpeg.run(["-i", str(src), "-vn", "-filter_complex", build_cut_filter(cuts, duration),
                "-map", "[out]", "-c:a", "flac", str(dst)])
    return dst
