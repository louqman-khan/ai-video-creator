# Live preview (task 4.6)

Decision D3 in `docs/decisions.md`: the editor draws the timeline in the browser from the small proxy files, so an
edit is visible at once. The FFmpeg render stays the truth (the "Rendered preview" and the export).

## Parts
| File | Role |
|---|---|
| `preview/plan.ts` | Pure functions of the document and a frame: `layersAt`, `audioAt`, `audioGain`, `captionAt`, `kenBurnsZoom`, `sourceSeconds`. Must mirror `backend/app/timeline/render.py`. |
| `preview/engine.ts` | `LiveEngine`: canvas drawing ("cover" fit, opacity, zoom), a clock, pooled `<video>`/`<audio>` elements kept within 0.15 s of the clock, WebAudio gain per audio clip. Exposes `currentTime`, `paused`, `play()`, `pause()` and events like a video element (`Transport`), so `usePlayhead` and the timeline work unchanged. |
| `preview/LivePreview.tsx` | The canvas component; the editor page switches between it and the rendered `<video>`. |

## Rules
- Every new visual feature (transform, effect, transition, chroma key) is added to `plan.ts` + `engine.ts` AND the
  renderer in the same task, with a parity check in `frontend/e2e/live-preview.mjs`.
- Captions in the live preview are an approximation (canvas text); libass output is only in the render/export.
- Proxies need a keyframe every 0.5 s (task 4.2) or scrubbing is slow.

## Measured (real Chrome, dev Mac)
Playhead 6.00 s after 6.02 s of wall time, 30 pictures/s, 0/360 slow animation frames, audio 0.06 s from the clock,
SSIM 0.92-0.96 against the FFmpeg preview (picture area), an edit shows within 300 ms.
