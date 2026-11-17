# Timeline UI (task 4.4, read-only)

Code: `frontend/src/timeline/` (`layout.ts` pure maths, `hooks.ts`, `Timeline.tsx`, `Waveform.tsx`, `Filmstrip.tsx`).
Shown in the project editor under the preview player. Editing arrives in 4.5.

## What it shows

Tracks in editor order: captions on top, then pictures (top layer first), then audio. Each clip is a block on its
track: pictures show a filmstrip (video) or their proxy (stills), audio shows its waveform (drawn with the clip's
volume), captions show their text (right-to-left aware). Clips on a muted track are dimmed and tagged. A looping
video shows a ⟳. Clicking a clip selects it and shows what it is (type, start, length, source position, volume,
media, license and the author when a credit is required).

Everything comes from files prepared in task 4.2 (`/media/film`, `/media/peaks`, `/media/proxy`); while they are
being prepared a "Preparing previews (n left)" chip shows and the clips fill in as they become ready.

## Controls

| Action | How |
|---|---|
| Move the playhead | click or drag on the ruler; click an empty part of a track; click a clip |
| Step a frame / a second | `←` `→` / `Shift` + `←` `→` (with the timeline focused) |
| Start / end | `Home` / `End` |
| Play / pause | button, or `Space` |
| Zoom | `+` `-` `0` (fit), the slider, the buttons, or `Ctrl`/`⌘` + wheel (around the pointer); **Fit** shows everything |
| Scroll | plain wheel / trackpad, scrollbar |

The playhead *is* the preview video's current time: playing or scrubbing the video moves it, and moving it seeks
the video. Without a player it keeps its own position. The timecode is `minutes:seconds:frames`.

## How it stays fast (rules to keep)

Measured in Chrome on the dev Mac with a synthetic **610-clip, 6-track, 6-minute** timeline and the project's real media:
scrolling and scrubbing 0-6 frames over 33 ms in 350, playing the video 4 of 351 frames over 33 ms (p95 16.8 ms).

1. **The playhead is not React state of the timeline.** It lives in a small external store (`usePlayhead`); only the
   timecode and the playhead line subscribe to it. Putting it in the body's state made *every clip* re-render on every
   video frame: 82 of 189 frames were slow before this was fixed.
2. **Only what is on screen exists.** Clips outside the view (plus a margin) are not rendered; waveform canvases cover
   only the visible part of a clip (at most 4096 px), filmstrip tiles only the visible slots; clips narrower than 8 px are
   plain blocks without label or media.
3. **Waveform resolution follows the zoom** (100 or 10 peaks per second), and `peakColumns` takes the maximum under
   each pixel column, so nothing flickers when zooming.
4. **Callbacks passed to clips are stable** so memoised clips are skipped when unrelated state changes.
5. Zooming keeps the time under the pointer fixed (`zoomScrollLeft`).

## Accessibility

The track area is a focusable region with a label explaining the keys; clips have names with their timing; the
timecode is `role="timer"` (not a live region: an `<output>` would make screen readers announce every frame).

## Editing (task 4.5)

Code: `ops.ts` (pure operations), `session.ts` (history + autosave), `Timeline.tsx` (gestures, toolbar, keys).

| Do this | Result |
|---|---|
| Drag a clip | moves it (also to another track of the same kind); stops at its neighbours; snaps within 8 px to clip edges, the playhead and 0 |
| Drag a clip's left/right edge | trims it; never past the media, a neighbour or 0; a trimmed audio clip keeps only its own words |
| `S` | split the selected clip (or every unlocked clip under the playhead) at the playhead; captions split their words in proportion |
| `Delete` / `Shift`+`Delete` | remove and leave a gap / remove and close the time on every unlocked track (captions keep the words still spoken) |
| `Ctrl`/`⌘`+`D` | duplicate into the next free space |
| `Ctrl`/`⌘`+`Z`, `+Shift+Z` (or `Y`) | undo / redo |
| Track label buttons | mute / lock (a locked track refuses every edit, with the reason shown) |

Rules to keep: operations never mutate and never return a half-done document (a refusal returns the same object);
dragging is previewed by running the real operation on every pointer move, so what is shown is what will be saved;
one gesture = one undo step; the session saves after 0.8 s of quiet, then asks the server for a new preview; a 409
stops saving (local edits stay) until the user chooses to reload.

## Several tracks, picture-in-picture, ducking (task 4.7)

- `+ Video track` / `+ Audio track` (video tracks stack above existing ones; up to 6 each). `×` on a track label removes
  it when it is empty (the last track of a kind and the caption track stay).
- Select a picture clip: **Opacity**, **Size** and position presets (full frame, four corners at 35 %). Put it on a
  higher video track than the picture it sits over. Select an audio clip: **Volume**, **Fade in/out**.
- The speaker button on an audio track's label (`⤓`) marks it as *ducked*: its volume drops about 12 dB while the other
  audio tracks speak (music under narration). The export uses a side-chain compressor; the live preview approximates it.
