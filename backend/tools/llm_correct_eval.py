#!/usr/bin/env python3
"""Does the LLM clean-up help? python tools/llm_correct_eval.py HYPOTHESIS.txt REFERENCE.txt LANG [GLOSSARY_FILE]  (needs GEMINI_API_KEY in .env)"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_wer import normalise, wer  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.pipeline.correct import GeminiCorrector  # noqa: E402

hyp = Path(sys.argv[1]).read_text("utf-8")
ref = normalise(Path(sys.argv[2]).read_text("utf-8"))
gloss = Path(sys.argv[4]).read_text("utf-8") if len(sys.argv) > 4 else ""
s = get_settings()
fixed, stats = GeminiCorrector(s.gemini_api_key, s.gemini_model, gloss).correct(hyp, sys.argv[3])
Path("/tmp/hyp_corrected.txt").write_text(fixed, "utf-8")
print(json.dumps({"before_wer": round(wer(ref, normalise(hyp))[0], 4), "after_wer": round(wer(ref, normalise(fixed))[0], 4), **stats}))
