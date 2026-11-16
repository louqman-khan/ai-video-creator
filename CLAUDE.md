# Project: AI Video Creator (working name)

> **Agent: read `docs/ROADMAP.md` at the start of every session and follow its workflow.** It lists every task in order, what "done" means, and what you're waiting on from the human. When the human says "continue", pick up the next task from the roadmap, verify it, check it off, commit, and keep going.

An AI-powered video creation and editing platform. The user uploads an audio file or types a script (Urdu or English). The tool automatically finds relevant visuals, syncs them to the audio, adds captions, cleans the audio and builds the video. A professional timeline editor then lets the user refine and export it.

Main differentiator: first-class **Urdu** support (Urdu speech recognition, Urdu captions in **Jameel Noori Nastaleeq**, Urdu narration).

---

## Key decisions (already agreed — do not re-debate)

1. **Frontend: React + TypeScript + Vite.** Not Vue, not Next.js (the editor is a logged-in app, so SEO/SSR is not needed). React was chosen for its video-editing ecosystem (Remotion, timeline, canvas and drag-and-drop libraries).
2. **Backend: Python + FastAPI.** All AI/media processing lives in Python.
3. **Media engine: FFmpeg** for assembling, rendering, converting and burning in captions.
4. **Laptop/desktop first.** Start as a web app opened in a laptop browser. Later, wrap it as a desktop app with **Tauri**, so heavy processing can run on the user's own machine. No mobile editing (maybe mobile preview much later).
5. **Zero-cost start.** Use only free and open-source tools and free API tiers. Add paid services/GPUs only when the product grows.
6. **Legal media only.** Never download clips from regular YouTube videos or images from Google Search, because those are copyrighted. Use free-to-reuse sources:
   - Pixabay API (primary source for videos and images)
   - Openverse and Wikimedia Commons APIs (images, no key needed)
   - Pexels API — optional; new key issuance is currently paused, so the pipeline must work without it
   - Wikimedia Commons / public-domain archives
   - Creative Commons (CC-BY) content, with attribution stored
   - User uploads
   - Open-source AI image generation (later, when a GPU is available)
   Store each asset's source, license and attribution in metadata.
7. **Pluggable providers (most important architecture rule).** Every AI/media capability sits behind its own interface, so we can swap free implementations for paid ones (or a rented GPU) through config, without rewrites:
   - `Transcriber` (default: faster-whisper / WhisperX)
   - `ScenePlanner` / LLM (default: local model via Ollama, or a free API tier like Gemini/Groq)
   - `MediaSearch` (default: Pexels + Pixabay)
   - `MediaRanker` (default: CLIP-style image–text similarity)
   - `AudioCleaner` (default: DeepFilterNet / RNNoise + FFmpeg loudnorm)
   - `TTS` (later; default: Meta MMS-TTS for Urdu, Piper/Kokoro for English)
   - `AvatarRenderer` (later; default: LatentSync / MuseTalk)

---

## Recommended stack

| Area | Choice |
|---|---|
| Frontend | React, TypeScript, Vite |
| State | Zustand |
| Timeline / preview | Canvas (react-konva or custom WebGL), dnd-kit for drag-and-drop |
| Video preview/render in browser | Remotion (check its license: free for individuals/very small companies only), otherwise render server-side with FFmpeg |
| Backend | Python 3.11+, FastAPI |
| Speech recognition | faster-whisper / WhisperX with word-level timestamps |
| Captions | ASS subtitles rendered by libass via FFmpeg; Urdu needs correct RTL + Nastaleeq shaping (HarfBuzz) |
| Urdu font | Noto Nastaliq Urdu as the default (free for commercial use); Jameel Noori Nastaleeq as a user option (its license is unclear) |
| Audio cleanup | DeepFilterNet, voice activity detection for silence removal, EBU R128 loudness normalization |
| Desktop (later) | Tauri |
| Free hosting (later) | Vercel/Netlify (frontend), Oracle Cloud free VM (backend), Cloudflare R2 (storage) |

---

## Feature list (full vision)

1. **Automatic content research:** from the transcript/script, generate a search query per scene (translating Urdu into English queries), fetch candidates from free sources, rank them by relevance, and pick the best ones.
2. **Automatic sync:** word-level timestamps → scenes → each visual's duration matches its scene's audio.
3. **Captions:** Urdu + English, auto-generated, editable; customizable font, size, color and position. Urdu recognition is imperfect, so a good caption-correction screen is essential.
4. **Audio:** noise removal, silence/gap removal, enhancement; cut/trim/split/merge.
5. **Pro editor:** multi-track timeline; cut/trim/split/merge; rearranging; transitions/effects; background music and sound effects; crop/resize/aspect ratios; chroma key (green screen); multiple formats/resolutions.
6. **AI avatar:** selectable avatars and voices, lip-synced, Urdu + English.

---

## Roadmap (build step by step)

- **Step 1 — Core pipeline as a command-line tool (no UI, CPU only, ~3–4 weeks).**
  Audio file in → faster-whisper transcript with word timestamps → LLM splits it into scenes + search queries → fetch from Pexels/Pixabay → FFmpeg assembles visuals timed to the audio + burns captions → MP4 out.
- **Step 2 — Urdu + audio quality (~3–4 weeks).** Nastaleeq captions with correct RTL rendering, noise removal, silence removal, loudness normalization; benchmark Urdu transcription accuracy on real samples.
- **Step 3 — Basic web app (~2 months).** Upload audio/script, scene list with chosen visuals, swap visuals, edit captions and caption style, preview, export.
- **Step 4 — Timeline editor (~3 months).** Multi-track timeline, editing operations, transitions, music, crop/resize, chroma key. Ship features incrementally.
- **Step 5 — Voice + avatars (once a GPU is available).** TTS for typed scripts, open-source lip-sync avatars (prototype on Google Colab/Kaggle first).

**When to get a GPU:** when processing becomes too slow, when starting avatar/AI-image work, or when there are regular/paying users. Order: rent per hour (RunPod/Vast.ai) → buy a used RTX 3060 12GB / RTX 3090 24GB → cloud GPU servers once there's real traffic.

---

## Suggested repo layout

```
/backend          FastAPI app + pipeline
  /app/providers  one folder per provider interface (transcriber, media_search, ...)
  /app/pipeline   orchestration: transcribe → plan scenes → fetch → rank → assemble
  /cli            command-line entry point (Step 1)
/frontend         React + TS + Vite (Step 3+)
/assets/fonts     Jameel Noori Nastaleeq etc.
/samples          test audio (Urdu + English)
```

## Working conventions

- Secrets (Pexels/Pixabay/LLM API keys) go in `.env`, never committed. Provide `.env.example`.
- Keep the pipeline runnable from the CLI even after the web app exists. This makes it easier to test and debug.
- Test with both Urdu and English sample audio.
- Prefer small, working increments over large unfinished features.

## Current status

Tracked in `docs/ROADMAP.md` (task checkboxes + progress log). Don't duplicate status here.
