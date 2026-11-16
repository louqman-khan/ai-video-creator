"""Split a word-timed transcript into scenes that tile the whole audio (no gaps)."""

from __future__ import annotations

from app.models import Scene, Transcript, Word

SENTENCE_END = set(".?!۔؟…")


def chunk_scenes(
    t: Transcript, min_s: float = 3.0, max_s: float = 8.0, gap_s: float = 0.5
) -> list[Scene]:
    words = [w for w in t.words if w.text.strip()]
    if not words:
        raise ValueError("Transcript has no words: nothing to build scenes from.")

    groups: list[list[Word]] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        dur = w.end - cur[0].start
        at_sentence_end = w.text.rstrip()[-1:] in SENTENCE_END
        pause = nxt.start - w.end >= gap_s
        if dur >= max_s or (dur >= min_s and (at_sentence_end or pause)):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    # a very short last scene reads badly: fold it into the previous one
    if len(groups) > 1 and groups[-1][-1].end - groups[-1][0].start < min_s / 2:
        groups[-2].extend(groups.pop())

    # boundaries sit in the middle of the pause between groups; ends are the audio ends
    total = max(t.duration, words[-1].end)
    bounds = [0.0]
    for a, b in zip(groups, groups[1:]):
        bounds.append((a[-1].end + b[0].start) / 2)
    bounds.append(total)

    return [
        Scene(
            id=i + 1,
            start=round(bounds[i], 3),
            end=round(bounds[i + 1], 3),
            text=" ".join(w.text for w in g),
        )
        for i, g in enumerate(groups)
    ]
