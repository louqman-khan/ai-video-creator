# Decisions

Short records of decisions that are expensive to reverse. Newest first. Rationale and alternatives are in
`docs/STEP4_PLAN.md`; this file keeps the decision, the evidence and what would make us revisit it.

## 2026-11-16 — Step 4 (timeline editor), task 4.0

Approved by the project owner on 2026-11-16 after review of `docs/STEP4_PLAN.md`.

### D1. `timeline.json` is the single source of truth
Versioned (`schema`), with a revision counter for optimistic concurrency, all positions in **integer
frames**. Auto-build produces it; the editor edits it; the Step 3 scene list and caption editor become views
over it. *Revisit if:* migration from old projects proves lossy.

### D2. Final render = FFmpeg on the server, timeline flattened into cacheable segments
Cut at every point where the set of active clips changes; render each segment with its own filtergraph;
cache by a fingerprint of the clips active in it; concat with `-c copy`; separate audio mixdown pass;
captions burned from the caption track. Filtergraphs are built only from validated numbers and whitelisted
effect names. *Evidence:* every needed filter exists in the bundled FFmpeg 9.0.2 (`xfade`, `overlay`,
`chromakey`, `despill`, `eq`, `gblur`, `amix`, `sidechaincompress`, `loudnorm`, ...).

### D3. Live preview = browser compositor over proxies — **spike PASSED**
Export (D2) stays the truth; a parity suite compares the two renderers. Measured 2026-11-16 on the
development Mac (Intel i7-4980HQ, 8 threads, 16 GB, macOS 12; headless Chrome, with VS Code/OneDrive etc.
running, load average 5–8). `frontend/spikes/preview-engine/`, 3 video layers composited on a 960x540
canvas + 2 audio tracks through WebAudio:

| Pass criterion | Result |
|---|---|
| 3 video + 2 audio at 30 fps, < 2 % dropped frames | 60 fps canvas, **0 of 5,412 frames dropped** over 60 s |
| audio/video drift < 80 ms over 60 s | **max 4 ms** (median 1 ms), no corrections needed |
| scrub shows a frame in < 150 ms | proxy: **median 21 ms, p95 37 ms** |

Comparison that fixes a requirement for task 4.2: the same size with a normal long GOP scrubs at median
169 ms / p95 253 ms, and the untouched 1080p sources at 152 / 317 ms. **Proxies must use a keyframe every
0.5 s** (`-g 15` at 30 fps). The raw 1080p sources also *played* without drops (drift about 40 ms), so
proxies are about scrubbing, not about playback.

Caveats (to be measured again in task 4.6, not assumed): the spike draws static layers; the real engine
adds transforms, effects, the chroma-key shader and fast clip switching, and shares the main thread with
the timeline UI. Headless Chrome (software compositing) is, if anything, pessimistic for canvas.
**Fallback if 4.6 misses the budgets:** chunked server preview (about 5 s around the playhead at 480p).

### D4. Timeline UI = DOM + pointer events (React + zustand) — **spike PASSED**
Deviates from the "recommended stack" row in CLAUDE.md (Konva/WebGL + dnd-kit); approved. Canvas/WebGL is
used for the preview viewport and waveforms. Measured with `frontend/spikes/timeline/` (memoised clips,
snapping to every other clip's edges on each move, input at about 125 Hz), dragging one clip 600 px:

| Clips | fps | p95 frame | frames > 33 ms | long tasks |
|---|---|---|---|---|
| 100 | 60.0 | 16.8 ms | 0 of 271 | 0 |
| 300 (criterion: >= 50 fps) | 60.1 | 16.7 ms | 0 of 322 | 0 |
| 1000 | 59.9 | 16.7 ms | 0 of 375 | 0 |

Sanity-checked that the drag is real: the clip moved 602 px for a 600 px drag, the snap guide appeared and
the clip edge landed exactly on another clip's edge. Caveat: spike clips have no waveform/filmstrip; those
will be drawn only for visible clips. *Fallback:* Konva for the track area (document model unaffected).

### D5. No Remotion
Its license is headcount-based (free for individuals and organisations of 3 or fewer people, otherwise a
paid company license; see remotion.dev/license), it renders through headless Chrome, and it would be a
third pipeline next to the browser preview and FFmpeg. *Revisit if:* animated title templates written in
React become a goal.

### D6. Music and sound effects: Openverse audio + user uploads
Openverse's audio API works without a key (verified: 163 results for one query, with `license`,
`license_url`, `attribution`, `duration`, direct file URLs; the sample was Freesound CC BY 4.0). Pixabay's
documented API has only images and videos (no music endpoint). Licenses are filtered with
`license_type=commercial,modification`; CC BY results need attribution, so credits cover audio. Uploads
carry a "you have the rights" confirmation. Wikimedia Commons audio is unreachable from the development
network (DNS).

### D7. Export encoders: software x264 (quality) and VideoToolbox (fast)
Measured, 10 s of 1080p30: `libx264 medium` 9.8 s (4.0 MB), `libx264 veryfast` 3.9 s, `h264_videotoolbox`
1.7 s (7.1 MB at 8 Mb/s) — about 6x faster than the current final setting, at larger file size. Capability
is probed at startup. 4K time estimates are extrapolations (about 4x the pixels) until measured in 4.12.


### D8. Hosted version one = one machine, accounts in SQLite, files on the shared disk — **decided 2026-11-17**
Public hosting needs isolation, limits and security, not scale. One Docker host runs Caddy (HTTPS) and the app (API + editor + render workers); accounts/sessions live in SQLite (WAL; PostgreSQL by URL
later), every project is a folder owned by an account; a single global guard enforces login, ownership (404 for foreign projects), CSRF header/Origin, administrator-only routes and per-user limits. Object storage and
a worker queue are postponed until one machine is not enough: ffmpeg needs real files, so the split costs a large refactor with no benefit for the first users. Free computer voices (CC-BY-NC / unclear licence) are
disabled in hosted mode; downloads from search results are limited to public addresses. Details: `docs/hosting.md`, `docs/security.md`.
