#!/usr/bin/env python3
"""Word error rate of the speech recogniser on a sample: python tools/benchmark_wer.py AUDIO REFERENCE.txt MODEL [LANG] [SECONDS]

The reference is the exact text of the audio. Both texts are normalised the same way (case, punctuation, Arabic diacritics, bracketed
source references and digits-only tokens removed) before comparing words with an edit distance. Prints one JSON line."""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def normalise(text: str) -> list[str]:
    text = re.sub(r"[\(\[（].*?[\)\]）]", " ", text)                 # bracketed references like (Seerat Ibn Hisham, p. 412)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in text if not unicodedata.category(c).startswith(("M", "P", "S")))   # marks (diacritics), punctuation, symbols
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ە", "ہ").replace("ۃ", "ہ")
    return [w for w in text.split() if not w.isdigit()]


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int, int]:
    n, m = len(ref), len(hyp)
    d = list(range(m + 1))
    for i in range(1, n + 1):
        prev, d[0] = d[0], i
        for j in range(1, m + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return d[m] / max(1, n), n, m, d[m], 0


def main() -> None:
    audio, ref_path, model = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    lang = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "auto" else None
    prompt = Path(sys.argv[5]).read_text("utf-8") if len(sys.argv) > 5 else ""          # optional glossary file
    tag = sys.argv[6] if len(sys.argv) > 6 else model
    from app.providers.transcriber.faster_whisper import FasterWhisperTranscriber

    t0 = time.time()
    tr = FasterWhisperTranscriber(model, prompt).transcribe(audio, lang)
    took = time.time() - t0
    hyp_text = " ".join(s.text for s in tr.segments)
    ref, hyp = normalise(ref_path.read_text("utf-8")), normalise(hyp_text)
    w, n, m, errors, _ = wer(ref, hyp)
    Path(f"/tmp/hyp_{audio.stem}_{tag}.txt").write_text(hyp_text, "utf-8")
    print(json.dumps({"audio": audio.name, "model": model, "variant": tag, "language": tr.language, "audio_s": round(tr.duration, 1), "took_s": round(took, 1),
                      "ref_words": n, "hyp_words": m, "edit_errors": errors, "wer": round(w, 4)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
