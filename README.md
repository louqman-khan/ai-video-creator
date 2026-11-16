# AI Video Creator

Audio (Urdu or English) in, captioned video with matching stock visuals out.
Step 1 is a command-line pipeline; see `docs/ROADMAP.md` for status and `CLAUDE.md` for the decisions.

## Setup (macOS)

```bash
brew install ffmpeg                      # must include libass for captions
python3.12 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
cp .env.example .env                     # then fill in the keys
.venv/bin/avc doctor                     # pass/fail list of everything below
```

Keys (all free): `PIXABAY_API_KEY` (https://pixabay.com/api/docs/) and `GEMINI_API_KEY`.
`PEXELS_API_KEY` is optional and skipped when empty. Openverse and Wikimedia Commons need no key.
Without a Gemini key use `SCENE_PLANNER=heuristic` (English only).

Fonts for Urdu captions go in `assets/fonts/` (Noto Nastaliq Urdu by default; Jameel Noori
Nastaleeq optional). Font files are git-ignored.

## Usage

```bash
avc doctor                               # check the environment
avc transcribe samples/english.mp3       # transcript only -> work/runs/english/transcript.json
avc make samples/english.mp3 -o out.mp4  # full pipeline
avc make samples/urdu.mp3 --lang ur --whisper-model medium
avc make samples/english.mp3 --aspect 9:16 --no-captions
```

Each run keeps its files in `work/runs/<audio name>/`: `transcript.json`, `scenes.json`,
`assets.json` (source, license and attribution of every visual), `captions.ass` and `CREDITS.txt`.
Re-running skips finished stages; `--force` redoes everything.

## Layout

`backend/app/providers/*` one folder per swappable provider, chosen by env vars (see `.env.example`);
`backend/app/pipeline/*` the stages; `backend/cli/main.py` the `avc` command; `backend/tests/` unit tests
(`.venv/bin/python -m pytest` from `backend/`).

## Media licensing

Only free-to-reuse sources are used. Every asset keeps its license and a ready-to-print credit
line; put `CREDITS.txt` in your video description when you publish.
