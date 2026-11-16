# Spikes (task 4.0)

Throw-away experiments that decided Step 4 questions with numbers. Results and decisions are in
`docs/decisions.md`. Not product code; kept so the measurements can be repeated (and later reused as
parity-test scaffolding).

| Spike | Question | Run |
|---|---|---|
| `preview-engine/` | Can a browser compositor play 3 video layers + 2 audio tracks and scrub on this Mac? | `make-media.sh <dir>` (from the repo root), `python serve.py <dir> 8899`, `node measure.mjs 8899 60` |
| `timeline/` | Can a DOM + pointer-events timeline drag smoothly with hundreds of clips? | `npm run dev`, then `node spikes/timeline/measure.mjs http://127.0.0.1:5742` |

Needs `playwright-core` (a dev dependency) and an installed Google Chrome. Notes for anyone editing
`make-media.sh`: never pass shell globs or untrusted paths to ffmpeg as inputs. Every extra positional
argument after `-i` is treated as an **output file**, which once overwrote a project's cache file.
