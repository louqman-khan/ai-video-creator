# Crop, size, turn, frame shapes (task 4.10)

## Model
- Frame shape: `Timeline.aspect` = 16:9 | 9:16 | 1:1 | 4:5 (final 1920x1080, 1080x1920, 1080x1080, 1080x1350; preview 960x540, 540x960, 540x540, 560x700).
  `PUT /timeline` takes an optional `aspect`; the project's own `aspect` follows and a stale export is invalidated.
- Per picture clip: `transform` = `x`, `y` (fractions of the frame, of the piece's centre), `scale` (1 = as wide as the frame), `rotation` (degrees,
  clockwise), `crop` (left, top, right, bottom as fractions of the frame-sized picture), `opacity`; and `fit`.
- `fit`: `fill` = scale to cover the frame and cut the overflow (default); `fit` = whole picture, bars transparent (what lies underneath shows,
  black on the lowest track); `blur` = whole picture over a copy of itself that covers the frame, enlarged 15 % and blurred (sigma 3 % of the width).

## Order of operations (identical in `_layer_chain` in render.py and `drawLayer` in preview/engine.ts)
1. the picture in a frame-sized image (fill / fit / blur; a still with Ken Burns is always fill)
2. effects (brightness, contrast, saturation, blur)
3. crop (the rectangle stays where it was: the piece's centre is offset by `(l - r)/2 * W * scale`)
4. resize by `scale` (pixel density is kept: the cropped piece is not stretched)
5. rotate about the piece's centre
6. opacity / fades / transition (alpha, shift, zoom), then overlay at `x`, `y`

## Editor
Toolbar: **Frame** and **Pictures** (fill / fit / blur for all pictures). Inspector: Size, Turn, Crop left/top/right/bottom, Fit to frame,
Crop on the preview, Reset. On the live preview the selected picture has handles (`CanvasHandles.tsx`, maths in `frameGeometry.ts`):
drag the picture = move, a corner = resize (uniform, by distance from the centre), the round handle = turn (snaps within 3 degrees of a quarter turn),
and in crop mode the four edges. A crop edge stops where 10 % of the picture is left and never moves the opposite edge.
While dragging, the live preview shows the draft; releasing is one undo step.

## Checking parity
`frontend/e2e/reframe.mjs` (real Chrome, a COPY of a project with prepared media): live canvas vs rendered preview at 160 px, against a baseline.
