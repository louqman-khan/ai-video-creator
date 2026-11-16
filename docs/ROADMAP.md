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

- [ ] Urdu sample audio at `samples/urdu.mp3` (30–60 s) **and its exact text** at `samples/urdu.txt` (needed for task 2.8: WER needs a reference)
- [ ] English sample audio at `samples/english.mp3` (30–60 s) **and its exact text** at `samples/english.txt` (task 2.8)
- [ ] Optional: `Jameel Noori Nastaleeq.ttf` in `assets/fonts/` (license unclear; use with `--font "Jameel Noori Nastaleeq"`). Noto Nastaliq Urdu is already installed and committed (OFL).
- [ ] Step 4 test media (needed from 4.2 / 4.11 on): a real green-screen clip, a phone video (ideally rotated and variable frame rate), and a short music file you are allowed to use. Put them in `samples/`.
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

- [x] 1.12 (found 2026-11-16) Gemini planning latency: one `avc make` spent 3 min 43 s in the planning step (others took seconds). Log per-request timing and retries, find the cause (thinking model? 120 s timeout + retries? 503s), and consider a faster model or a lower thinking budget. Also add a visible "still waiting for Gemini" log line.

## Step 2 — Urdu + audio quality

- [x] 2.1 Urdu transcription (`--lang ur`, auto-detect by default); Urdu text normalization.
- [x] 2.2 Urdu captions: correct RTL + Nastaleeq shaping through libass; Noto Nastaliq Urdu default, `--font` to choose Jameel Noori Nastaleeq. *Done when:* the Urdu sample has correctly joined, right-to-left captions.
- [x] 2.3 Urdu → English search-query translation in the ScenePlanner (keep the original Urdu text for captions).
- [x] 2.4 Caption styling options: font, size, color, outline, position, words per line (CLI flags + config file).
- [x] 2.5 AudioCleaner: DeepFilterNet (or RNNoise fallback) noise removal; `--no-clean` to skip. (RNNoise via FFmpeg `arnndn`; DeepFilterNet not used: needs PyTorch, risky on Intel macOS 12. Can be added later behind the same `AudioCleaner` interface.)
- [x] 2.6 Silence/gap removal with VAD (`--remove-silence`, configurable min gap); keep caption/scene timings consistent after the cut.
- [x] 2.7 Loudness normalization (EBU R128, -14 LUFS) on export. (Lands within ~0.6 LU of the target on peaky speech because of the -1.5 dBTP ceiling; true peak stays below it.)
- [!] 2.8 Benchmark: Urdu and English WER on the samples with `small` vs `medium`; record the results in `docs/benchmarks.md`.
- [x] 2.9 Script input: `avc make narration.mp3 --script script.txt` aligns a known script to the audio (forced alignment). (Audio stays the positional argument. Also `avc transcribe --script` to preview. Alignment is sequence matching against Whisper word times, no PyTorch/WhisperX.)

## Step 3 — Web app (React + TypeScript + Vite frontend, FastAPI backend)

- [x] 3.1 FastAPI: project model (JSON on disk to start), upload endpoint, background job queue for the pipeline, progress via polling or SSE.
- [x] 3.2 Frontend scaffold: React + TS + Vite + Zustand; routes for Projects, New Project and Editor.
- [x] 3.3 New Project: upload audio (+ optional script for exact captions), choose language and aspect ratio, start the job, show progress. (Script-only projects need TTS: Step 5.)
- [x] 3.4 Scene list view: each scene's text, time range and chosen visual; "swap visual" shows other candidates and runs a new search.
- [x] 3.5 Caption editor: fix transcript text per word/line; style panel (font, size, color, position) with live preview.
- [x] 3.6 Preview player (proxy/low-res render) + Export (1080p, 16:9 / 9:16).
- [x] 3.7 Credits/attribution panel per project.

## Step 4 — Timeline editor

Approved plan: `docs/STEP4_PLAN.md` (decisions D1–D7, phases, tests, risks). Order matters: document → renderer → UI → editing → live preview → layers/audio → transitions → transform → chroma key → import/export.

- [~] 4.0 Decisions and spikes. Run the two spikes (browser preview engine; DOM timeline at 300 clips) and record all decisions in `docs/decisions.md` (render approach, UI tech, Remotion, music sources, export encoders). *Done when:* both spikes have pass/fail numbers on this Mac, and the fallback is chosen if one fails.
- [ ] 4.1 Timeline document v1: schema (integer frames), validator, migration from scenes/assets/captions, `GET/PUT /timeline` with a revision check. *Done when:* an existing project round-trips to a timeline and back to the same scenes, and renders SSIM >= 0.99 against today's output.
- [ ] 4.2 Editor media pipeline: import checks (`ffprobe`, size/duration caps), variable-frame-rate to constant, rotation baked in, 960x540 short-GOP proxies, waveform peaks, filmstrip thumbnails, in the background worker; per-project disk usage.
- [ ] 4.3 Timeline renderer v1: flatten the timeline into cacheable segments + audio mixdown + caption burn; encoder profile (x264 / VideoToolbox). *Done when:* editing one clip re-renders only its segments, and "whole vs split" renders match.
- [ ] 4.4 Timeline UI, read-only: tracks, ruler, zoom, playhead, waveform, filmstrip, click to seek, synced with the player.
- [ ] 4.5 Editing operations: move, trim, split, merge, delete (lift) and ripple-delete (range), duplicate, reorder; snapping; undo/redo; autosave with revision check; keyboard shortcuts; captions re-flow from the remaining words. *Done when:* property tests keep all invariants for random operation sequences.
- [ ] 4.6 Live preview engine: browser compositor over proxies + WebAudio (or the chunked server fallback if the 4.0 spike failed); parity suite against FFmpeg.
- [ ] 4.7 Multiple video and audio tracks: picture-in-picture, per-clip volume, fades, mute, music ducking under narration.
- [ ] 4.8 Media bin: stock search (video, image, music and SFX from Openverse audio), uploads with a rights confirmation, credits and `CREDITS.txt` extended to audio.
- [ ] 4.9 Transitions (crossfade, dip, slide, zoom) and basic effects (brightness, contrast, saturation, blur).
- [ ] 4.10 Crop / resize / position with on-canvas handles; change the project aspect ratio (fit / fill / blurred-background reframe).
- [ ] 4.11 Chroma key: FFmpeg `chromakey` + `despill` for export, WebGL shader for preview, eyedropper UI; parity-checked.
- [ ] 4.12 Import formats (mp4, mov, webm, mp3, wav, m4a, png, jpg incl. HEVC/ProRes/VP9, HDR tone-mapping) and export presets (720p, 1080p, 4K; quality vs hardware encoder) with time estimates.
- [ ] 4.13 Hardening: performance budgets (drag >= 50 fps at 300 clips, seek < 150 ms), accessibility/keyboard, disk cleanup, conflict UX, docs.

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

- 2026-11-16 — plan — Step 4 plan approved (`docs/STEP4_PLAN.md`: timeline document as single truth, FFmpeg server render with cacheable segments, browser live preview behind a spike, DOM-first timeline UI, no Remotion, Openverse audio + uploads, hardware export option); roadmap Step 4 replaced by tasks 4.0–4.13 (old 4.1→4.4, 4.2→4.5, 4.3→4.7+4.8, 4.4→4.9, 4.5→4.10, 4.6→4.11, 4.7→4.2+4.12, 4.8→4.0)

- 2026-11-16 — 3.7 — credits panel (**Step 3 complete**). Backend `GET /attributions`: unique visuals with license, author, source and the scenes that use them (credit-required ones first; no download URLs). Frontend `CreditsPanel`: one entry per visual (scenes, creator, source link, license link, "Credit required" badge), a notice saying how many visuals legally need a credit (CC BY etc.) or that none do, copy-to-clipboard of the exact `CREDITS.txt` text (selectable text box if the browser blocks the clipboard), download link, http(s)-only links, reloads after every re-render — 89 backend tests (2 new) and 76 vitest tests (9 new) pass, tsc + build clean; real Chrome on the Urdu project: 3 Pixabay entries with working source/license links, notice shown, clipboard text identical to CREDITS.txt, console clean

- 2026-11-16 — 3.6 — preview + export. Pipeline: `RenderProfile` (`preview`: 960x540 / 540x960, ultrafast, CRF 28-30, 96k audio; `final`: 1080p, as before), `Pipeline.run(quality=...)`, separate clip dirs and caption files per quality; the CLI still renders final. API: new/edited projects render only the preview (`preview.mp4`); `POST /export {aspect}` renders the full-quality 1080p video in 16:9 or 9:16 (`output.mp4`), `GET /export` downloads it; any edit deletes a stale export (`export_ready` false); a failed export leaves the project usable with an error banner; `/video` serves the preview (old projects: their `output.mp4`); caption preview now draws onto the 960 px preview base. Fixed a real bug found in the browser: the same `/video` URL served a different file after each render and Chrome showed an old copy from its HTTP cache → `Cache-Control: no-cache` on video responses + versioned player URL (`?v=`) + the player is no longer remounted on every progress update. Frontend: `ExportPanel` (format 16:9 / 9:16 with a centre-crop warning, export, download, credits link), player labelled as preview — measured on the Urdu project: preview render 2.8 s from scratch / 0.8 s cached vs 22.1 s full quality (3.4 MB vs 14.5 MB, ~8x faster); in Chrome a caption edit re-rendered in 4.6 s (second edit 1.6 s, was 15-47 s); vertical export 22.9 s → downloaded 1080x1920, 11.97 s, Unicode file name ok; editing made the export stale (download link gone, notice shown); legacy project still plays; console clean. 87 backend tests (6 new) and 67 vitest tests (11 new) pass, tsc + build clean

- 2026-11-16 — 3.5 — caption editor. Backend `app/api/captions.py`: `GET /captions` (cues, edited?, language, style), `PUT` (edited text by cue id and/or style → one re-render; stale cue lists get 409; text is NFC-normalised, control characters stripped, ASS override tags neutralised), `DELETE` (reset text edits), `POST /captions/preview` (a real frame rendered by FFmpeg/libass onto `concat.mp4`, the caption-free video, with the requested style and text: WYSIWYG incl. Urdu shaping). Refactor: `captions.py` = `build_cues` + `cues_to_ass`; the runner uses `captions.json` (user cues) when present and writes `transcript.final.json`; edited cues are discarded when the timeline changes (silence/script options). Font names are validated (no ASS injection). Frontend `CaptionEditor`: preview that follows the selected caption (debounced, outdated requests cancelled), style panel (font, size, position, colours, outline, bold, words per line — locked once text is edited), per-caption textareas (RTL-aware) with edited markers, Apply / Undo / Reset — 81 backend tests (5 new caption API tests) and 56 vitest tests (15 new) pass, tsc + build clean; real Chrome E2E on the Urdu project: 6 captions listed, live preview 0.7 s per change (colour, position, Urdu text), apply → re-rendered in 15.2 s, edit persisted (words-per-line locked, Reset offered), final video frame shows the yellow top-aligned Urdu caption and the ASS style line matches, reset → original text back in 16.7 s with the style kept, console clean, no horizontal overflow at 1200 and 500 px. Not built: changing caption timing, splitting/merging captions

- 2026-11-16 — 3.4 — scene list + swap visual. Backend `app/api/scenes.py`: `GET /scenes` (no download URLs/paths exposed), `GET /scenes/{id}/thumb` (local JPEG from the cached media), `GET /scenes/{id}/candidates?query=` (search + rank, stored per scene), `POST /scenes/{id}/swap` (takes only an asset id the server offered, never a URL → no SSRF; background job: download, update `assets.json`, re-render; on failure the old video stays and the error is shown). Per-scene clip cache (`segments/manifest.json`, fingerprint of visual + length + size): a swap re-encodes one clip. Frontend `SceneList`: thumbnail, time range, text (RTL-aware), search query, source link (http/https only) + license + author when required, swap panel with editable search and a grid of candidates — 76 backend tests (6 new API tests incl. SSRF-style ids, swap-while-processing, failed download keeps video) and 41 vitest tests pass; real Chrome E2E against real Pixabay/Openverse: 3 scenes shown with true thumbnails, 16 candidates (all thumbnails load, 200 from cdn.pixabay.com), swapped scene 2 then scene 3: only that scene changed, no error banners, console clean. Timing: swap ≈ 23 s via API (5 s download + 17.6 s render; one 47 s outlier with a big download and Chrome running). Profile: clips 5.4 s uncached / 1.5 s for one changed / 0 s cached, final encode with captions 13.7 s → a low-res preview (3.6) is the real fix for latency

- 2026-11-16 — 3.3 — New Project form (`NewProjectPage`): file picker, optional name, language (auto/English/Urdu), 16:9 or 9:16, optional script box (RTL-aware), audio/caption options, real upload progress (XHR) with cancel; client-side checks use the limits the server reports in `/api/health` (single source of truth); `useProject` no longer retries 4xx (a missing project was re-polled forever) — 30 vitest tests, `tsc` clean, build ok; real browser E2E (Chrome via playwright-core, both real servers): wrong file refused in the page, Urdu clip + script + options uploaded, live status Listening → Recognised 31 words → Planning → Finding visuals 1/3..3/3 → Rendering → Ready in ~95 s, `<video>` loaded 1920x1080 / 11.97 s with the Nastaleeq caption visible, API log shows only 200/202/206; favicon added; not-found page requests the project twice (StrictMode) then stops. Backend: `/api/health` now returns `limits`

- 2026-11-16 — 3.2 — `frontend/`: React 19 + TypeScript (strict) + Vite + Zustand + React Router; typed API client (readable FastAPI errors, "is avc serve running?" message), projects store, `useProject` polling hook, Projects / New Project (placeholder) / Editor pages (progress, error, player, download, credits), light/dark CSS, RTL-safe names (`dir=auto`). Dev ports 5742 (UI, strict) and 8742 (API): 5173/8000 were already used by other dev servers on this Mac, and `localhost` resolved to IPv6 and hit a different app — verified: `tsc` clean, 13 vitest tests pass, `npm run build` ok, both servers running: UI page, API through the Vite proxy, SPA deep link, error text, CORS allowed for the UI origin and refused for a foreign one; headless Chrome screenshots of the real Projects and Editor pages (video loads and plays through the proxy)

- 2026-11-16 — 3.1 — `app/api/` (FastAPI): `POST /api/projects` (multipart upload + options), `GET /api/projects[/id]` (status, stage, progress 0..1, message, error), `/video`, `/credits`, `DELETE`; projects as JSON on disk under `work/projects/<uuid>/`; one background worker thread; `avc serve`; pipeline `progress` hook. Safety: upload streamed with size cap, `ffprobe` check + max length, only the extension allowlist, user filename never used as a path, 32-hex ids (no path traversal), secrets redacted from errors, interrupted jobs marked failed on restart, localhost-only bind + CORS for the Vite dev server — 6 API tests with fake providers (happy path, bad files, limits, bad ids, redaction, delete-while-running, restart recovery), 69 tests pass; real server + curl: Urdu clip → transcribe → plan → fetch 1/2, 2/2 → render → done in 56 s, 9.7 MB 1080p MP4 downloaded, scan found neither API key in responses, project folder or server log. Not built yet: auth (not needed while localhost-only), SSE (polling is enough), multi-worker queue

- 2026-11-16 — 1.12 — cause: `gemini-3.5-flash` itself is slow/variable (43–145 s for ~220 output tokens, also with thinking off), not our code. Fix: `GEMINI_MODEL` is now a comma-separated fail-over list (default `gemini-flash-lite-latest,gemini-3-flash-preview,gemini-3.5-flash`), 45 s timeout, one attempt per model, log line per request with model + seconds — compared 6 models (Urdu queries equally good on the fast ones); live: planning 1.5 s and 2.4 s (was up to 225 s), whole run 40–51 s; 5 new fail-over tests with mocked HTTP (503, timeout, garbage answer, all failing; no key in the error), 63 pass

- 2026-11-16 — 2.9 — `app/pipeline/align.py` + `--script`: script words replace the recognised ones (script spelling/punctuation, sentences become caption segments) with timing from the ASR words; misheard spans spread over their time slot, unheard words interpolated, extra spoken words dropped; warns when <50% match; script hash is a timeline option (changing it re-plans scenes) — 8 new tests (58 pass); Urdu clip: ASR had سیاہ / ان وادیوں merged / دھکے, aligned output has the correct ڈھکے, سیاح ان وادیوں, کے لیے with the same timings (27/33 exact matches), wrong English script on Urdu audio: 0/15 → warning; full `avc make --script` rendered frame shows the corrected caption

- 2026-11-16 — 2.7 — `app/media/loudness.py`: two-pass `loudnorm` (measure, then linear gain), default -14 LUFS / -1.5 dBTP, `--lufs`, `--no-normalize`; silent audio is left alone; last audio step, so it measures what ends up in the video — measured the finished MP4s: no normalisation -18.10 LUFS → default -14.61 LUFS (peak -1.45 dBTP), `--lufs -18` → -18.43 LUFS; 2 new tests incl. a real ffmpeg run (50 pass). Cache invalidation made per-option: only silence removal re-plans scenes/media (changing the loudness target had re-run Gemini planning)

- 2026-11-16 — 2.6 — `--remove-silence` / `--min-gap` (default 0.8 s → shortened to 0.4 s, half kept each side): cuts from word-timestamp gaps, audio cut with atrim+concat (5 ms fades), transcript remapped with the same cut list so scenes/captions/visuals share the new timeline; run folder now records its options (`run_config.json`) and discards derived files when they change (also fixes a stale `audio_clean.flac` being reused after `--no-clean`) — 7 new tests (48 pass); real run on speech with 1.5/2.5/3 s pauses: 19.92 s → 12.73 s (7.2 s removed in 3 gaps); fresh Whisper transcription of the cut audio vs the remapped transcript: 31/31 words, mean start diff 0.02 s, max 0.16 s

- 2026-11-16 — 2.5 — `FfmpegCleaner` (80 Hz high-pass + RNNoise `arnndn`, or `afftdn` if the model is missing; FLAC intermediate; failure → original audio), default on, `--no-clean` to skip, `avc fetch-models`, doctor check; ASR keeps hearing the original, the final mix uses the cleaned audio — measured on speech + white noise + 50 Hz hum, full `avc make`: pause level -32.8 → -53.2 dB (original clean -53.1), speech -17.0 → -17.8 dB, duration unchanged; `afftdn` fallback -32.6 → -48.6 dB after tuning (`tn=1` did nothing); 41 tests pass. Model not committed (author's "not subject to copyright" claim is unusual: check before shipping)

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
