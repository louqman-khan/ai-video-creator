# Transitions, picture fades and effects (task 4.9)

## What exists
- `transition_in` on a picture clip: `crossfade`, `dip` (through black), `slide` (new picture pushes in from the right),
  `zoom` (new picture fades in while settling from 125 % to 100 %). Length 1 frame .. the clip's length.
- `fade_in` / `fade_out` on picture clips (frames): the picture becomes transparent, so what lies underneath (or black) shows.
- Effects (`effects[]`, value -100..100, blur 0..100): `brightness`, `contrast`, `saturation`, `blur`; `kenburns` as before.

## How a transition works
A transition into clip B happens over B's first `d` frames. The clip A before it on the same track ends exactly where B
starts, so A is carried on underneath ("ghost", id `A~out`, only inside the renderer / live preview, never saved) for `d`
frames: a still stays, a video keeps playing (a looping video loops, a video that has run out holds its last frame).
Appearance of a layer `F` frames after its own start (`p = clamp(F / d)`):

| | alpha | shift | size |
|---|---|---|---|
| crossfade, B | `p` | | |
| dip, B / ghost A | `clamp(2p-1)` / `clamp(1-2p)` | | |
| slide, B | 1 | `(1-p)` frame widths | |
| zoom, B | `p` | | `1 + 0.5 (1-p)` |
| fade in / out (any picture) | `clamp(F/in)`, `clamp((dur-F)/out)` | | |

Opacity = `transform.opacity` x all of these. The maths exists twice and must stay identical:
`_timing` / `_fx_args` in `backend/app/timeline/render.py` and `appearance` / `cssFilter` in `frontend/src/preview/`.

## Implementation notes (ffmpeg)
- moving alpha: `color=2x2` -> `geq=lum='255*opacity*expr(N)'` -> `scale` -> `alphamerge` (the `fade` filter cannot start before the segment does).
- slide: `overlay` x expression with `n-1` (`n` starts at 1 in `overlay`), plus the clip's frames-before-segment offset.
- zoom: `scale` with `eval=frame`.
- colour: brightness multiplies RGB by `1 + 0.8 b/100`, contrast scales around 128 by `1 + c/100` (`lutrgb`), saturation `eq`, blur `gblur`
  (sigma `0.00015 * v * width`): equal to the CSS filters of the live preview.
- segment cache keys include the timing expressions, the frames-before-the-segment offset and the effects.

## Checking parity
`frontend/e2e/transitions.mjs` (real Chrome, a COPY of a project with prepared media): live canvas vs rendered preview, compared at
160 px wide against a no-effect baseline, best of +-1 frame. Do not use full-resolution SSIM on busy 29.97 fps footage: two
encodes of the same frame only score about 0.82.
