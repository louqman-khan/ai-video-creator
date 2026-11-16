"""Urdu text normalisation for ASR output.

Whisper (trained on lots of Arabic/Persian text) often emits Arabic letter forms, Latin
punctuation and no Urdu full stop. Fixing that keeps captions typographically correct and
gives the scene splitter a sentence end to work with.
"""

from __future__ import annotations

import re
import unicodedata

from app.models import Segment, Transcript, Word

# Arabic letter forms -> the Urdu letter
_LETTER_MAP = {
    "ي": "ی",  # ي  Arabic yeh        -> ی  Farsi yeh
    "ى": "ی",  # ى  alef maksura      -> ی
    "ك": "ک",  # ك  Arabic kaf        -> ک  keheh
    "ه": "ہ",  # ه  Arabic heh        -> ہ  heh goal
    "ە": "ہ",  # ە  ae                -> ہ
}
# Arabic-Indic digits -> Extended Arabic-Indic digits (the Urdu forms)
_DIGIT_MAP = {0x0660 + i: 0x06F0 + i for i in range(10)}
# tatweel, tashkeel (short vowel marks), zero-width space, BOM
_STRIP = re.compile("[ـً-ْ﻿​]")
_PUNCT_MAP = {"?": "؟", ",": "،", ";": "؛"}
_TERMINAL = set("۔؟!.?…")

_TABLE = {**{ord(k): v for k, v in _LETTER_MAP.items()}, **_DIGIT_MAP, **{ord(k): v for k, v in _PUNCT_MAP.items()}}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _STRIP.sub("", text).translate(_TABLE)
    text = re.sub(r"\s+([۔؟،؛!])", r"\1", text)  # no space before closing punctuation
    text = re.sub(r"\s+", " ", text).strip()
    if text.endswith("."):
        text = text[:-1] + "۔"
    return text


def _end_with_stop(word: Word) -> Word:
    last = word.text.rstrip()[-1:]
    if last and last not in _TERMINAL and last not in "،؛":
        return word.model_copy(update={"text": word.text + "۔"})
    return word


def normalize_transcript(t: Transcript, pause_s: float = 0.3) -> Transcript:
    """Normalise every word and add a '۔' where a segment ends in a pause without punctuation."""
    segments: list[Segment] = []
    for i, seg in enumerate(t.segments):
        words = [w.model_copy(update={"text": normalize_text(w.text)}) for w in seg.words]
        words = [w for w in words if w.text]
        if words:
            nxt = t.segments[i + 1] if i + 1 < len(t.segments) else None
            if nxt is None or (nxt.words and nxt.words[0].start - words[-1].end >= pause_s):
                words[-1] = _end_with_stop(words[-1])
        segments.append(
            Segment(text=" ".join(w.text for w in words), start=seg.start, end=seg.end, words=words)
        )
    return t.model_copy(update={"segments": segments})
