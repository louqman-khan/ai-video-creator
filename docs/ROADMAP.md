# ROADMAP — AI Video Creator

This is the single source of truth for **what to build next**.
The agent works through it top to bottom, one task at a time, and keeps it up to date.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked (needs the human — see "Waiting on human")

---

## How the agent uses this file (workflow)

1. At the start of every session, read `CLAUDE.md` and this file.
2. **First session only:** compare this roadmap with the actual code. Mark tasks that are already done as `[x]`, and fix anything listed here that doesn't match reality.
3. Pick the **first `[ ]` task** in the current step (skip `[!]` tasks). Mark it `[~]`.
4. Implement it in small, working increments.
5. **Verify** it against the task's "Done when" line (run the command, check the output). Don't mark a task done without verifying it.
6. Mark it `[x]`, add a one-line note under "Progress log" (date + what changed + how it was verified), and commit with a clear message.
7. Continue to the next task **without waiting for the human**, unless:
   - the task needs something only the human can provide → mark it `[!]`, add it to "Waiting on human", and move on to the next unblocked task;
   - a decision isn't covered by `CLAUDE.md` and is expensive to reverse → ask, briefly;
   - a step is finished → stop and give a short summary of what to test.
8. Never put secrets in code, logs or commits. Keys live only in `.env`.
9. If you discover new necessary work, add it as a new task in the right step rather than doing it silently.

The human only needs to say **"continue"** (or "next task") to move forward.

---

## Waiting on human

- [ ] Urdu sample audio at `samples/urdu.mp3` (30–60 s)
- [ ] English sample audio at `samples/english.mp3` (30–60 s)
- [ ] Optional: `Jameel Noori Nastaleeq.ttf` in `assets/fonts/` (license unclear; use with `--font "Jameel Noori Nastaleeq"`). Noto Nastaliq Urdu is already installed and committed (OFL).
- [ ] Rotate the Pixabay key again: a test script printed it into a session log on 2026-11-16 (httpx INFO logging; now silenced in `app/http.py`). Gemini key was never printed.
- [ ] Pexels key — new key issuance is paused by Pexels; the pipeline must work without it

---

## Step 1 — Core pipeline as a CLI (CPU only)

- [x] 1.1 Repo skeleton: `backend/`, venv, `requirements.txt`/`pyproject`, `.env.example`, `.gitignore`, `avc` CLI entry point. *Done when:* `avc --help` works.
- [x] 1.2 `avc doctor`: checks Python version, FFmpeg, `.env` keys, fonts, and network reachability of the media APIs. *Done when:* it prints a clear pass/fail list.
- [x] 1.3 Provider interfaces + config-based selection (Transcriber, ScenePlanner/LLM, MediaSearch, MediaRanker, AudioCleaner, TTS, AvatarRenderer). *Done when:* providers are chosen from config/.env with no code edits. (TTS and AvatarRenderer are interface stubs until Step 5.)
- [x] 1.4 Transcriber: faster-whisper (CPU, `small`) with word timestamps → `transcript.json`. *Done when:* English sample → words with start/end times.
- [x] 1.5 ScenePlanner: 3–8 s scenes + English search query per scene via Gemini (or Ollama), with a sentence-split fallback that needs no LLM → `scenes.json`. (Gemini only; Ollama not built, not required.)
- [~] 1.6 MediaSearch: Pixabay (videos preferred, images as fallback), Openverse + Wikimedia Commons (images, no key), Pexels optional (skipped when no key). Cache downloads; store source/license/attribution per asset. *Built and mock-tested;* Pixabay (video search + download, image search) and Openverse checked live. Wikimedia not tested live (commons.wikimedia.org times out from this network).
- [x] 1.7 Heuristic MediaRanker (default): keyword match, orientation, resolution, duration fit.
- [x] 1.8 Assembler (FFmpeg): trim/loop clips to scene duration, slow zoom on still images, scale/crop to 1920x1080, original audio, burned-in ASS captions from word timestamps.
- [~] 1.9 `--vertical` flag → 1080x1920 (9:16) with smart crop. *Built:* `--vertical` / `--aspect 9:16` (centre crop). *Missing:* smart crop; image + video segments verified at 1080x1920.
- [x] 1.10 `avc make <audio>` runs the full pipeline with progress logs; writes `output.mp4` + `credits.txt` (attributions). *Done when:* English sample → watchable MP4. (Verified on synthetic TTS audio; re-check with a real human sample. Visual relevance is weak: heuristic ranker only, CLIP is 5.3.)
- [x] 1.11 Basic tests for timing math and scene splitting; README with setup + usage. *Built:* 24 passing tests and `README.md`; README commands checked against a real run.

## Step 2 — Urdu + audio quality

- [x] 2.1 Urdu transcription (`--lang ur`, auto-detect by default); Urdu text normalization.
- [x] 2.2 Urdu captions: correct RTL + Nastaleeq shaping through libass; Noto Nastaliq Urdu default, `--font` to choose Jameel Noori Nastaleeq. *Done when:* the Urdu sample has correctly joined, right-to-left captions.
- [x] 2.3 Urdu → English search-query translation in the ScenePlanner (keep the original Urdu text for captions).
- [x] 2.4 Caption styling options: font, size, color, outline, position, words per line (CLI flags + config file).
- [ ] 2.5 AudioCleaner: DeepFilterNet (or RNNoise fallback) noise removal; `--no-clean` to skip.
- [ ] 2.6 Silence/gap removal with VAD (`--remove-silence`, configurable min gap); keep caption/scene timings consistent after the cut.
- [ ] 2.7 Loudness normalization (EBU R128, -14 LUFS) on export.
- [ ] 2.8 Benchmark: Urdu and English WER on the samples with `small` vs `medium`; record the results in `docs/benchmarks.md`.
- [ ] 2.9 Script input: `avc make --script script.txt --audio narration.mp3` aligns a known script to the audio (forced alignment).

## Step 3 — Web app (React + TypeScript + Vite frontend, FastAPI backend)

- [ ] 3.1 FastAPI: project model (JSON on disk to start), upload endpoint, background job queue for the pipeline, progress via polling or SSE.
- [ ] 3.2 Frontend scaffold: React + TS + Vite + Zustand; routes for Projects, New Project and Editor.
- [ ] 3.3 New Project: upload audio or paste a script, choose language and aspect ratio, start the job, show progress.
- [ ] 3.4 Scene list view: each scene's text, time range and chosen visual; "swap visual" shows other candidates and runs a new search.
- [ ] 3.5 Caption editor: fix transcript text per word/line; style panel (font, size, color, position) with live preview.
- [ ] 3.6 Preview player (proxy/low-res render) + Export (1080p, 16:9 / 9:16).
- [ ] 3.7 Credits/attribution panel per project.

## Step 4 — Timeline editor

- [ ] 4.1 Canvas timeline (react-konva or WebGL) with zoom, playhead and snapping; video, image, audio and caption tracks.
- [ ] 4.2 Cut / trim / split / merge; drag to move and rearrange; undo/redo.
- [ ] 4.3 Multiple video and audio tracks; per-clip volume; background music and sound-effect library (free sources).
- [ ] 4.4 Transitions (crossfade, slide, zoom) and basic effects (brightness, contrast, blur).
- [ ] 4.5 Crop / resize / position on canvas; change project aspect ratio.
- [ ] 4.6 Chroma key (green screen) in a WebGL shader for preview, with a matching FFmpeg filter for export.
- [ ] 4.7 Import formats (mp4, mov, webm, mp3, wav, m4a, png, jpg); export resolutions (720p, 1080p, 4K).
- [ ] 4.8 Evaluate Remotion (check the license) vs FFmpeg server render; decide and record the decision in `docs/decisions.md`.

## Step 5 — Voice + avatars (requires a GPU)

- [ ] 5.1 TTS provider: MMS-TTS (Urdu), Piper/Kokoro (English); typed script → narration → full pipeline.
- [ ] 5.2 Avatar provider: LatentSync or MuseTalk prototype (Colab/Kaggle first); avatar picker; overlay on the timeline.
- [ ] 5.3 CLIP MediaRanker (visual relevance), switchable through config.
- [ ] 5.4 Optional paid providers behind the same interfaces (e.g., HeyGen, ElevenLabs) — disabled by default.

## Later

- [ ] Tauri desktop app (run processing locally on the user's machine)
- [ ] User accounts, cloud storage (Cloudflare R2), deployment
- [ ] AI-generated images/clips provider

---

## Progress log

<!-- Agent: add one line per completed task, newest first. Format: YYYY-MM-DD — task id — what changed — how verified -->

- 2026-11-16 — 2.4 — `CaptionStyle` (font, size %, colour, outline colour/width, position, margin, bold, words per line, max chars) from TOML (`--style`) + CLI flags, flags win, unknown keys/bad colours rejected; words-per-line is a hard limit, orphan words rebalanced — 38 tests pass; ran `avc make` with yellow/top/3-words style: ASS style line and rendered frame match (`stands above a`, top, yellow, thick outline); typo'd key and `--color yellow` both give clear errors
- 2026-11-16 — 2.3 — Urdu→English queries already done by the Gemini planner; captions keep the original Urdu — verified on the Urdu clip: `scenes.json` query_en = "snow covered mountains pakistan", frames show Urdu captions

- 2026-11-16 — 2.2 — Urdu captions in Noto Nastaliq Urdu (OFL, `assets/fonts/` + license) by default, `--font`/`CAPTION_FONT` override, Urdu size 11% of height, captions never merge across ASR segments, no one-word orphan cues — rendered the Urdu clip with libass: frames show joined right-to-left Nastaleeq; 31 tests pass

- 2026-11-16 — 2.1 — `app/text/urdu.py`: Arabic→Urdu letters (ي ك ه), Arabic-Indic→Urdu digits, ? , ; . → ؟ ، ؛ ۔, strips tatweel/tashkeel, adds ۔ after a segment that ends in a pause; raw text kept in `transcript.raw.json` — 5 new unit tests (29 pass); real Urdu clip: language auto-detected, last sentence now ends with ۔, raw vs normalized files differ only there

- 2026-11-16 — 1.10/1.11 — `avc make` ran end to end on a 12.9 s synthetic English clip (Gemini TTS): Whisper → 3 scenes via Gemini → 3 Pixabay videos → captions → MP4 (H.264 1080p + AAC, 12.933 s = audio, no extra tmcd track) + `CREDITS.txt` with license per clip; full run 1 min 24 s, re-render from cache 24 s. Fixes found on the way: LLM timeout 120 s + friendly `PlannerError` + heuristic fallback for English; timecode/metadata stripped from output
- 2026-11-16 — 1.4 — transcriber returns 31 words with start/end for the English clip, text exactly right; reads the 16 kHz WAV directly because PyAV 19 breaks faster-whisper's own decoder (`metadata_errors` TypeError) — `avc transcribe` run; unit test for the WAV loader. Urdu smoke test: language auto-detected, ~90% correct with `small` (sample for 2.8, not a benchmark)
- 2026-11-16 — 1.8 — assembler verified with a real render: Pixabay clips, 14 s tone audio, burned English + Urdu captions; output 1920x1080 30 fps H.264/AAC, duration 14.000 s = audio; still image zoom 3.3 s = 99 frames at 1920x1080 and 1080x1920. Static FFmpeg 9.0.2 (libass + HarfBuzz) installed in `tools/bin` (git-ignored, SHA-256 checked) because Homebrew would have compiled 14 dependencies on macOS 12; the app prepends `tools/bin` to PATH
- 2026-11-16 — security — `app/http.py` now silences httpx/httpcore request logging (it printed full URLs incl. the Pixabay key); regression test added
- 2026-11-16 — 1.5 — Gemini planner verified live; default model changed to `gemini-3.5-flash` (`gemini-2.5-flash` returned 404 on generateContent) — English and Urdu scenes returned sensible English queries, keywords and video/image preference; timings come from word timestamps
- 2026-11-16 — 1.3 — TTS + AvatarRenderer interface stubs (`none` provider); all 7 providers selectable via env — test sets `SCENE_PLANNER`/`WHISPER_MODEL` env vars and checks the chosen classes, unknown name gives a clear error; `pytest` 21 passed
- 2026-11-16 — 1.2 — `avc doctor` rewritten (`app/doctor.py`): Python version, FFmpeg + libass, `.env`, keys, fonts, network reachability — ran it live: PASS/WARN/FAIL list printed, exit 1 because FFmpeg is missing, Wikimedia Commons unreachable from this network
- 2026-11-16 — 1.7 — ranker now scores keyword overlap (query/keywords vs tags/title) — new unit test, `pytest` passes
- 2026-11-16 — 1.1 — repo skeleton (`backend/` package, `.venv`, `pyproject.toml`, `.env.example`, `.gitignore`, `avc` entry point) — `avc --help` lists make/transcribe/doctor; `pytest` 18 passed
- 2026-11-16 — audit — compared roadmap with code; 1.2–1.11 are partly built and marked `[~]` with what is missing; roadmap moved from `ROADMAP.md` to `docs/ROADMAP.md` to match CLAUDE.md
