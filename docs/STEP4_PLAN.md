# Step 4 plan — Timeline editor

Status: **proposal, waiting for your review.** Nothing in `docs/ROADMAP.md` has been changed yet.
Written 2026-11-16, after Step 3 (web app) was finished and verified.

---

## 1. Summary (read this first)

**Goal.** After auto-build, the user can open a real multi-track timeline and change the video the way
they would in a desktop editor: cut, trim, split, rearrange, add music and extra clips, mix volume,
add transitions and effects, crop/position, reframe to another aspect ratio, key out a green screen,
and export in several resolutions.

**The one idea that makes this tractable.** Today the *scenes list* is the data model (one visual per
scene, back to back, one narration). A timeline editor needs a general model. So Step 4 introduces a
**timeline document** (`timeline.json`) as the single source of truth. Auto-build *produces* a timeline;
the editor *edits* it; one renderer turns it into video. The Step 3 screens (scene list, caption editor)
become views over the same document instead of separate truths.

**Recommendations (details in section 4):**

| # | Decision | Recommendation |
|---|---|---|
| D1 | Source of truth | `timeline.json`, versioned, times stored as **integer frames** |
| D2 | Final render | **FFmpeg on the server**, timeline "flattened" into cacheable segments (keeps today's fast incremental re-render) |
| D3 | Live preview | **Browser compositor** over small proxy files for playback/scrubbing, **gated by a spike** with pass/fail numbers; fallback = short server-rendered chunks. Export stays the truth. |
| D4 | Timeline UI tech | **DOM + pointer events** first (not Konva), spike-checked at 300 clips. Canvas/WebGL only for the preview viewport and waveforms. *This deviates from the "recommended stack" row in CLAUDE.md, so I want your OK.* |
| D5 | Remotion (roadmap 4.8) | **Do not adopt.** License is headcount-based, and it adds a third rendering path. |
| D6 | Music/SFX source | **Openverse audio** (verified working, no key) + user uploads. Pixabay has no music API. |
| D7 | Export speed | Offer **hardware H.264 (VideoToolbox)**: measured ~6x faster than our current software setting |

**Size.** 9 phases, each ends in something you can use and test. My estimate is **13–21 weeks** of focused
work; the roadmap's "~3 months" is the optimistic end. The two things that decide where we land are the
live preview engine (D3) and render parity. Phase 0 spikes replace guesses with measurements.

**What I need from you:** section 9 (8 questions, most are yes/no).

---

## 2. Where we are (facts from the code)

- **Data:** `scenes.json` (scenes tile the narration with no gaps/overlaps), `assets.json` (one visual
  per scene), `captions.json` (edited caption cues), options in `project.json`.
- **Render:** each scene becomes a clip (cached by a fingerprint of visual + length + size), clips are
  concatenated with `-c copy`, then one encode adds the narration and burns the captions. Two profiles:
  preview 960x540 (about 3 s) and final 1080p (about 22 s for a 12 s video).
- **API/UI:** scene list with swap, caption editor with a server-rendered live preview, export panel,
  credits panel. 89 backend + 76 frontend tests, real-Chrome checks.
- **What blocks a timeline editor today:**
  1. no general clips/tracks (no overlap, no gaps, no second video or audio track)
  2. render is concat-only: no overlay, transitions, transforms, keying
  3. preview is a rendered video: fine for "swap a visual" (a few seconds), too slow for trimming
  4. media is only downloaded stock: no uploads of video/images/music
  5. captions are tied to the original audio time: cutting audio must re-flow them correctly

**Our advantage to keep:** every narration clip has **word-level timestamps**. When the user cuts
narration, captions can be rebuilt from the words that remain instead of chopping text blindly.

---

## 3. Evidence gathered for this plan (2026-11-16)

Measured on this Mac (Intel i7-4980HQ, 8 threads, 16 GB, macOS 12) with the bundled static FFmpeg 9.0.2:

| Check | Result |
|---|---|
| Filters needed for the editor | **All present:** `xfade`, `overlay`, `blend`, `chromakey`, `colorkey`, `despill`, `eq`, `gblur`, `boxblur`, `crop`, `rotate`, `zoompan`, `pad`, `fade`, `atempo`, `setpts`, `amix`, `acrossfade`, `afade`, `sidechaincompress` (ducking), `loudnorm`, `ebur128`, `showwavespic`, `astats` |
| Input decoding | `h264`, `hevc`, `prores`, `vp9`, `av1`, `mpeg4`, `mjpeg`, `png`, `webp`; audio `aac`, `mp3`, `flac`, `opus`, `alac`, `pcm` |
| HDR / VFR helpers | `zscale`, `tonemap`, `colorspace`, `vfrdet` present |
| Encoders | `libx264`, `libx265`, `libvpx-vp9`, `libsvtav1`, `prores_videotoolbox`, **`h264_videotoolbox`**, `hevc_videotoolbox` |
| 10 s of 1080p30 encode time | `libx264 medium` **9.8 s** · `libx264 veryfast` **3.9 s** · `h264_videotoolbox` **1.7 s** (file 7.1 MB at 8 Mb/s vs 4.0 MB for x264 at CRF 20) |
| Remotion license (official pages) | Free for individuals and organisations with a total headcount of **3 or fewer**; otherwise a company license (about $25/seat/month, or per-render pricing). Matches your CLAUDE.md note. [remotion.dev/license](https://remotion.dev/license) |
| Pixabay music API | The documented API has only `/api/` (images) and `/api/videos/`. The `/music/` paths that appear on the docs page look like website navigation links, not API endpoints (my reading of the page, not stated by it). **No documented music API.** [pixabay.com/api/docs](https://pixabay.com/api/docs/) |
| Openverse audio API | **Works without a key.** Test query returned 163 results, e.g. Freesound loops with `license`, `license_url`, `attribution`, `duration`, direct `.mp3` URL. Those were **CC BY 4.0**, so attribution is required. |
| Wikimedia Commons | Still unreachable from this network (DNS), so Commons audio is untestable here |

Not verified yet (done in Phase 0 / 7): how many simultaneous 960x540 video elements Chrome can decode
smoothly on this CPU; HDR tone-mapping quality; behaviour on real phone footage (variable frame rate,
rotation metadata).

---

## 4. Decisions in detail

### D1. The timeline document

One JSON file per project, validated on every write.

```
Timeline { schema: 1, rev, fps, aspect, tracks[], clips[], assets{} }
Track    { id, kind: video|audio|caption, name, muted, locked }
Clip     { id, track, kind, asset, start, duration, in,           // all in frames
           volume, fade_in, fade_out,
           transform {x, y, scale, rotation, crop},
           effects[], transition_in {type, duration},
           words[]  (narration clips only: word timestamps) }
Asset    { id, kind, path, duration, size, license, attribution, proxy, peaks }
```

- **Integer frames, not seconds.** We already had to fix frame-rounding drift once; integers remove the
  whole class of bug (and make "no gaps" and "snap" exact).
- **Migration:** existing projects get a timeline the first time the editor opens (scene visuals become
  clips on V1, narration on A1, caption cues on C1). Old projects keep working until then.
- **One truth:** from Phase 1 the scene list and caption editor read/write the timeline (thin adapters),
  so there is no "two sources disagree" state.
- **Concurrency:** `PUT /timeline` carries the revision it was based on (`If-Match`); a second tab gets
  409 instead of silently overwriting.
- **Server validates everything** (never trusts client numbers): schema, clip inside its asset, no
  overlap on a track unless a transition, sane limits (e.g. 2000 clips, 16 tracks), finite numbers only.

### D2. Rendering: flatten the timeline into cacheable segments

Cut the timeline at every instant where the set of active clips changes (clip starts/ends, transition
windows). Render each segment with its own small FFmpeg filtergraph (overlay, transforms, effects,
`xfade` inside overlaps, chroma key). Cache each segment by a fingerprint of *only the clips and
parameters active in it*, then `concat -c copy`. Audio is a separate mixdown pass (volumes, fades,
`amix`, ducking via `sidechaincompress`, `loudnorm`), which is cheap next to video. Captions are
burned from the caption track exactly as now.

Why: it keeps the property we built in 3.4–3.6 (change one thing, re-encode one segment) even with
overlays and transitions. Effects use clip-relative time, so cutting a segment in the middle of a clip
renders the same pixels as not cutting it (this gets an explicit test: whole vs split render).

**Safety:** filtergraphs are built only from validated numbers and whitelisted effect names. User
strings never enter a filter string (captions go through the ASS file path, as today).

**Encoder profile** becomes a setting: `libx264` (best quality) or `h264_videotoolbox` (about 6x faster,
larger files). Capability is probed (`avc doctor`). On a future Tauri build on Windows/Linux the same
slot takes NVENC/QSV.

### D3. Live preview in the browser (the biggest risk)

The editor needs instant feedback while dragging and trimming; our server preview (1–5 s) is too slow
for that. Plan: a canvas/WebGL compositor plays small **proxy files** (960x540, short GOP so scrubbing
is fast) and mixes audio with WebAudio. The server render remains authoritative for export and for a
"Render preview" check.

**Keeping two renderers honest.** Both implement one written spec (operation order: crop, scale, rotate,
position, opacity, blend). A parity suite renders the same test timelines in FFmpeg and in Chrome
(Playwright, same method as our E2E checks) and compares frames (SSIM threshold per feature).

**Spike gate (end of Phase 0), pass/fail on this Mac:**
- 3 video layers + 2 audio tracks play at 30 fps with <2% dropped frames
- scrub to any point shows a frame in <150 ms
- audio/video drift stays <80 ms over 60 s

**If it fails:** fall back to *chunked server preview* (render the 5 s around the playhead at 480p,
roughly 1 s per chunk) with client-only playback for a single layer. Nothing else in the plan changes.

### D4. Timeline UI technology

CLAUDE.md lists "Canvas (react-konva / WebGL) + dnd-kit" as the *recommended* stack. I recommend
**DOM + pointer events** for the timeline itself:
- accessibility and keyboard editing come for free (nudge, split, delete)
- labels, Urdu caption text and RTL render with the browser's own shaping, and are easy to test
- our scale is small (a few hundred clips), so virtualised DOM is enough
- Canvas/WebGL is still used where it earns its keep: the preview viewport (compositor, chroma-key
  shader) and audio waveforms

dnd-kit is only useful for dropping from the media bin; clip dragging needs free positioning with
snapping, which custom pointer handling does better. **Spike criterion:** 300 clips, drag at >=50 fps on
this Mac. If it misses, switch the track area to Konva (the document model is unaffected).

### D5. Remotion (roadmap task 4.8)

Recommend **no**. (1) License is headcount-based: free only up to 3 people; a product that grows or
sells would need a company license. (2) It renders through headless Chrome, heavy on this hardware, and
would be a third pipeline next to our browser preview and FFmpeg (audio, captions). (3) We already have
the FFmpeg pipeline with caching. Revisit only if React-defined motion graphics (animated titles)
become a goal. To be written up in `docs/decisions.md`, as the roadmap asks.

### D6. Music and sound effects (legal-media rule)

- **Openverse audio** (verified): same keyless API and license filtering we already use for images
  (`license_type=commercial,modification`, so no NC/ND). Includes `category`, `genres`, `duration`.
- **User uploads**, flagged "user-provided: you confirm you have the rights".
- **Not used:** Pixabay music (no API; a user can still download from the website and upload it).
- Many Openverse/Freesound results are **CC BY**, which *requires* attribution. So the credits panel and
  `CREDITS.txt` extend to audio. The panel already flags "credit required".

### D7. Export presets

720p / 1080p / 4K x {quality, fast-hardware}. Rough extrapolation from the measurement above (to be
measured in Phase 7): 1080p software `medium` runs at about real time on this Mac, so 4K would be about
4x slower (a 10-minute video, roughly 40 minutes); hardware encoding should bring that to roughly a
fifth. 4K therefore ships with an estimated-time warning, and the hardware option.

---

## 5. Phases

Each phase ends in a demo, tests and a real-Chrome check, as in Step 3. Sizes are judgment ranges.

| Phase | New roadmap tasks | You can then... | Size |
|---|---|---|---|
| **0. Foundations and spikes** | 4.0 decisions, 4.1 timeline document, 4.2 editor media pipeline | (internal) open any project as a timeline document; proxies, waveforms, thumbnails exist; D3/D4 settled with numbers | 1–2 wk |
| **1. See and navigate** | 4.3 renderer v1, 4.4 timeline UI (read-only) | see tracks, waveform, filmstrip, zoom, playhead; click to seek; export renders from the timeline identically to today | 2–3 wk |
| **2. Edit** | 4.5 editing operations | move, trim, split, merge, delete, ripple, duplicate, reorder; snapping; undo/redo; autosave; keyboard shortcuts; captions follow cuts | 2–3 wk |
| **3. Live preview** | 4.6 | smooth playback and scrubbing of edits (or chunked fallback) | 2–3 wk |
| **4. Layers and audio** | 4.7, 4.8 | more video/audio tracks, picture-in-picture, volume/fades/mute, music ducking under narration, media bin with stock search + music/SFX + uploads, credits for audio | 3–5 wk |
| **5. Transitions and effects** | 4.9 | crossfade, dip, slide, zoom; brightness/contrast/saturation/blur | 1–2 wk |
| **6. Transform and aspect** | 4.10 | crop/resize/position with on-canvas handles; change aspect with fit / fill / blurred-background reframe | 1–2 wk |
| **7. Chroma key** | 4.11 | green-screen removal: eyedropper, similarity/blend/spill, preview matches export | 1 wk |
| **8. Import, export, hardening** | 4.12, 4.13 | mp4/mov/webm/mp3/wav/m4a/png/jpg imports (phone video, HDR, rotation), 720p/1080p/4K, hardware option, disk cleanup, performance budgets, accessibility | 2–3 wk |

**Order rationale:** document first, then render from it (so nothing else is built on sand), then the
UI. Phase 1 is shippable on its own because the existing server preview can act as the player. Chroma key
sits late because it needs the compositor and a real green-screen sample.

### Phase 0 in more detail
1. **4.0 Decisions:** run both spikes (preview engine, UI at 300 clips), write `docs/decisions.md`.
2. **4.1 Timeline document:** schema v1, validator, migration from scenes/assets/captions, `GET/PUT
   /timeline` with revision check. *Done when:* an existing project round-trips to a timeline and back
   to the same scenes, and renders frame-identical (SSIM >= 0.99) to the current output.
3. **4.2 Media pipeline for the editor:** import (upload, `ffprobe` check, variable-frame-rate to
   constant, rotation applied), proxy (960x540, short GOP), waveform peaks, filmstrip thumbnails, all
   produced in the background worker; per-project disk usage shown.

### The editing rules to decide early (they affect captions and sync)
- **Delete clip** leaves a gap on that track only. **Delete range** removes the time from *all
  unlocked tracks* (ripple). Both exist, like standard editors.
- Cutting narration rebuilds caption cues from the words that remain in the narration clip.
- Automatic silence removal (task 2.6) is conceptually "ripple-delete the gaps"; the timeline will
  express it that way.
- "Rebuild from audio" (re-run auto-build) replaces the timeline, behind a confirmation.

---

## 6. Test strategy

| Layer | What |
|---|---|
| Pure editing logic | One TypeScript module of operations (split, trim, move, ripple...). **Property tests:** random operation sequences always keep invariants (no overlaps, non-negative, integer frames, total length) and `undo(op(x)) = x`. |
| Schema and migration | Fixtures from real projects (the Urdu demo); fuzz the validator (NaN, huge numbers, 100k clips, negative times, unknown fields). |
| Render | Golden frames compared with SSIM; **whole-vs-split equivalence**; cache test (edit one clip re-renders at most N segments); audio loudness checks (as in 2.7). |
| Preview parity | Same timelines rendered by FFmpeg and Chrome, frames compared per feature (tolerances documented). |
| End to end | Real Chrome via Playwright for each phase: drag, trim, keyboard, undo, export; console must be clean; no horizontal overflow at 1200 px and 500 px. |
| Performance budgets (this Mac) | Timeline drag >=50 fps at 300 clips; 10 s preview segment re-render <5 s; seek <150 ms; autosave <200 ms. |
| Security | Upload abuse (types, size, duration, fake extension), path traversal, filtergraph injection attempts, oversized documents, concurrent-tab conflicts. |

---

## 7. Risks

| Risk | Likelihood | Mitigation / early signal |
|---|---|---|
| Browser preview cannot play several layers smoothly on this CPU | Medium | Spike with numbers in Phase 0; chunked-server fallback defined up front |
| Client and FFmpeg renderers drift apart | High over time | One written spec + parity suite in CI-style runs; export is always the truth; keep the effect list small |
| Scope creep in effects/transitions | High | Fixed list per phase; no keyframe animation, titles or templates in Step 4 |
| Data loss (autosave, undo, two tabs) | Medium | Revision check, undo stack, server keeps last N revisions |
| Real-world media (phone VFR, rotation, HDR, odd codecs) | High | Normalise at import (CFR, rotation baked into proxy, tone-map); test with real files (need from you) |
| Disk growth (proxies, segment caches) | Medium | Show usage per project; delete proxies/caches on demand; eviction in Phase 8 |
| 4K export time on this laptop | High | Hardware option + time estimate warning; software 4K stays "for patient users" |
| Music licensing mistakes | Medium | Only Openverse (license filter) and uploads with a rights confirmation; attribution shown in credits |
| Schedule (13–21 weeks) | Medium | Phases are independently shippable; chroma key and 4K are the first things to drop if needed |

---

## 8. Non-goals for Step 4

Keyframe animation, text/title templates and motion graphics, multi-camera editing, colour grading
beyond brightness/contrast/saturation, plugins/LUTs, collaborative editing, mobile editing, the Tauri
desktop wrapper (later), voice and avatars (Step 5).

**Definition of done for Step 4** (the demo we run at the end): open the Urdu demo project in the
timeline; split a scene, trim and reorder; add music from Openverse and duck it under the narration;
add a crossfade; add a picture-in-picture clip; key out a green-screen clip; reframe to 9:16 with a
blurred background; export 1080p; the credits panel lists the music with its required attribution.

---

## 9. Decisions and inputs I need from you

1. **D1 timeline as the single source of truth** (Step 3 screens become views over it). OK?
2. **D4 DOM-first timeline UI** instead of Konva, with the 300-clip spike as the judge. This departs from
   the stack table in CLAUDE.md. OK?
3. **D3 browser live preview with the chunked-server fallback** if the spike fails. OK?
4. **D5 no Remotion.** Any plan that would make it attractive (e.g. animated title templates)?
5. **D6 music from Openverse + uploads**, no Pixabay music. OK with mostly CC BY results (credit required)?
6. **D7 hardware export option** (about 6x faster, larger files, macOS only for now). OK?
7. **Priorities:** if time gets tight, drop in this order: 4K, chroma key, blur-fill reframe. Agree?
8. **Test media I cannot make myself:** a real green-screen clip, a phone video (ideally rotated and
   variable frame rate), a short music file you are allowed to use. These go in "Waiting on human".

Still open from earlier steps and unrelated to this plan: Urdu/English sample recordings with exact text
(task 2.8), the Pixabay key rotation, and the Wikimedia network issue.

---

## 10. Proposed `docs/ROADMAP.md` changes (applied only after you approve)

Replace the current 4.1–4.8 with:

- 4.0 Decisions and spikes (record in `docs/decisions.md`: render approach, UI tech, Remotion)
- 4.1 Timeline document v1 (schema, validator, migration, `GET/PUT /timeline`)
- 4.2 Editor media pipeline (import checks, proxies, waveforms, thumbnails)
- 4.3 Timeline renderer v1 (flattened segments + cache; parity with today's output)
- 4.4 Timeline UI, read-only (tracks, ruler, zoom, playhead, waveform, filmstrip)
- 4.5 Editing operations (move/trim/split/merge/delete/ripple/duplicate/reorder, snapping, undo/redo, autosave, shortcuts)
- 4.6 Live preview engine (browser compositor + WebAudio, or chunked fallback)
- 4.7 Multi-track video/audio, volume, fades, mute, music ducking
- 4.8 Media bin: stock search (video/image/music/SFX), uploads, credits for audio
- 4.9 Transitions and basic effects
- 4.10 Crop/resize/position and aspect change (fit / fill / blur-fill)
- 4.11 Chroma key (FFmpeg + shader, parity-checked)
- 4.12 Import formats and export presets (720p/1080p/4K, hardware encoder)
- 4.13 Hardening (performance budgets, accessibility, disk cleanup, conflict UX, docs)

Mapping from the old list: 4.1 → 4.4, 4.2 → 4.5, 4.3 → 4.7 + 4.8, 4.4 → 4.9, 4.5 → 4.10, 4.6 → 4.11,
4.7 → 4.2 + 4.12, 4.8 → 4.0.
