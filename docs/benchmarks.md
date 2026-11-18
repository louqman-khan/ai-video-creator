# Speech accuracy benchmarks (task 2.8)

Tool: `backend/tools/benchmark_wer.py AUDIO REFERENCE.txt MODEL LANG [GLOSSARY_FILE] [TAG]` (audio must be 16 kHz mono WAV) and
`backend/tools/llm_correct_eval.py HYPOTHESIS.txt REFERENCE.txt LANG [GLOSSARY_FILE]`.
WER = word edit distance / reference words after normalising both texts (case, punctuation, diacritics, bracketed source references, bare numbers).
Machine: Intel Mac, CPU only, int8.

## Urdu - `samples/urdu.wav` (595 s, 1430 reference words, one speaker, religious lecture)

| Setup | WER | Time |
|---|---|---|
| `small` | 38.5 % | 560 s |
| `small` + Gemini clean-up | 21.6 % | + ~1 min |
| `small` + Gemini clean-up + 10-term glossary | 20.4 % | |
| `medium` | 27.4 % | 1385 s (2.3x real time) |
| `medium` + Gemini clean-up | 22.2 % | |
| `medium` + 10-term glossary in Whisper's prompt | 28.1 % (no gain; 27.4 % without) | 1996 s |

Reading it:
- The LLM clean-up helps far more than the bigger model: after it, `small` and `medium` are about equal (21.6 % vs 22.2 %). `medium` alone is 11 points better than `small` alone but costs 2.5x the time and 1.5 GB.
- The reference `urdu.txt` is not an exact transcript (the speaker says "number two / three" and other words the text lacks; some spellings differ). Folding spelling variants changes the scores by under one point, so most of the remaining ~20 % is probably real errors plus that mismatch. An exact reference would show the true figure.
- Gemini may know this famous text, so the clean-up gain may be smaller on unfamiliar content. Not yet tested on other material.
- A glossary given to Whisper itself (`WHISPER_PROMPT`) did not help on this file (28.1 % vs 27.4 %, within noise). Given to the Gemini clean-up it helped a little (21.6 -> 20.4 %).
- The word that matters most here (طلقاء) is still often wrong after clean-up.

## English - `samples/english.wav` (406 s, 1005 reference words, one speaker, clear speech)
| Setup | WER | Time |
|---|---|---|
| `small` | 1.3 % (13 word errors) | 181 s (0.45x real time) |

Caveat: `samples/english.txt` started as a `medium` draft that the owner was asked to proofread; if it was not changed, this number measures how closely `small` agrees with `medium` (still a good sign for clear English, but not proof of 100 %).

## What this means for the product
No setting reaches 100 %. The reliable routes to exact text are (1) the user's script aligned to the audio (`--script`) and (2) the caption editor, which marks cues
the recogniser was unsure about or the LLM changed ("please check"). Default model stays `small` (fast); `medium` is selectable in Setup.
