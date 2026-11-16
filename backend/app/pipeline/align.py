"""Align a known script to ASR word timestamps.

The audio is transcribed as usual; the script's own words then replace what the recogniser
thought it heard, keeping the timing. So captions get the author's exact spelling and
punctuation (important for Urdu, where ASR is weak) while sync still comes from the audio.

Method: sequence alignment (difflib) of script words against ASR words on a normalised key.
Words that match keep the ASR time. Spans that differ (misheard words, words missing from the
audio, extra spoken words) are spread proportionally over the time the recogniser assigned to
that span, or interpolated between the neighbouring matched words.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import Segment, Transcript, Word
from app.text.urdu import normalize_text

SENTENCE_END = set(".?!۔؟…")
MIN_WORD_S = 0.08


@dataclass
class AlignStats:
    script_words: int
    asr_words: int
    exact: int  # script words that matched an ASR word exactly

    @property
    def match_ratio(self) -> float:
        return self.exact / self.script_words if self.script_words else 0.0


def _key(token: str, urdu: bool) -> str:
    t = normalize_text(token) if urdu else token
    t = unicodedata.normalize("NFKC", t).casefold()
    return "".join(ch for ch in t if not unicodedata.category(ch).startswith("P"))


def split_script(text: str, urdu: bool) -> list[list[str]]:
    """Script text -> sentences -> word tokens (punctuation stays attached to its word)."""
    sentences: list[list[str]] = []
    for block in re.split(r"\n\s*\n|\r\n\s*\r\n", text.strip()):  # blank line = hard break
        cur: list[str] = []
        for raw in block.split():
            tok = normalize_text(raw) if urdu else raw
            cur.append(tok)
            if tok[-1:] in SENTENCE_END:
                sentences.append(cur)
                cur = []
        if cur:
            sentences.append(cur)
    return [s for s in sentences if s]


def _spread(words: list[str], t0: float, t1: float) -> list[tuple[float, float]]:
    """Give each word a slice of [t0, t1] proportional to its length."""
    t1 = max(t1, t0 + MIN_WORD_S * len(words))
    weights = [max(len(w), 1) for w in words]
    total, out, t = sum(weights), [], t0
    for w in weights:
        d = (t1 - t0) * w / total
        out.append((t, t + d))
        t += d
    return out


def align_script(script: str, asr: Transcript) -> tuple[Transcript, AlignStats]:
    urdu = asr.language == "ur"
    sentences = split_script(script, urdu)
    tokens = [t for s in sentences for t in s]
    if not tokens:
        raise ValueError("The script is empty.")
    asr_words = [w for w in asr.words if w.text.strip()]
    if not asr_words:
        raise ValueError("No speech was recognised in the audio, so the script cannot be aligned.")

    s_keys = [_key(t, urdu) for t in tokens]
    a_keys = [_key(w.text, urdu) for w in asr_words]
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    exact = 0
    sm = SequenceMatcher(None, s_keys, a_keys, autojunk=False)
    pending: list[tuple[int, int]] = []  # script spans with no ASR words at all
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                w = asr_words[j1 + k]
                times[i1 + k] = (w.start, w.end)
            exact += i2 - i1
        elif i2 > i1:
            if j2 > j1:  # misheard span: spread over the time the recogniser gave it
                span = _spread(tokens[i1:i2], asr_words[j1].start, asr_words[j2 - 1].end)
                for k, tm in enumerate(span):
                    times[i1 + k] = tm
            else:
                pending.append((i1, i2))  # in the script but never heard
    # words never heard: fit them into the gap between their neighbours
    for i1, i2 in pending:
        prev_end = next((times[k][1] for k in range(i1 - 1, -1, -1) if times[k]), 0.0)  # type: ignore[index]
        next_start = next((times[k][0] for k in range(i2, len(tokens)) if times[k]), asr.duration)  # type: ignore[index]
        for k, tm in enumerate(_spread(tokens[i1:i2], prev_end, max(next_start, prev_end))):
            times[i1 + k] = tm

    # monotonic, positive-length words
    fixed: list[tuple[float, float]] = []
    last_end = 0.0
    for tm in times:
        assert tm is not None
        s = max(tm[0], last_end)
        e = max(tm[1], s + MIN_WORD_S)
        fixed.append((round(s, 3), round(e, 3)))
        last_end = e

    segments, idx = [], 0
    for sent in sentences:
        words = [Word(text=tok, start=fixed[idx + k][0], end=fixed[idx + k][1]) for k, tok in enumerate(sent)]
        idx += len(sent)
        segments.append(Segment(text=" ".join(sent), start=words[0].start, end=words[-1].end, words=words))
    duration = max(asr.duration, segments[-1].end)
    return (
        Transcript(language=asr.language, duration=duration, segments=segments),
        AlignStats(script_words=len(tokens), asr_words=len(asr_words), exact=exact),
    )
