# Chroma key (task 4.11)

`Clip.key` = `{color: "#rrggbb", similarity 0..0.5, blend 0..0.5, despill: bool}` on picture clips (null = off).

## Maths (identical in render.py `_key_args` and preview/chromakey.ts / the shader)
- chroma of a colour: BT.709 limited range `U = 128 + 224 (B - Y) / 1.8556`, `V = 128 + 224 (R - Y) / 1.5748`
- distance `d = hypot(U - Uk, V - Vk) / 793` (ffmpeg's `chromakey` scale, fitted on test colours)
- opacity = `clamp((d - similarity) / blend)`; with `blend = 0` it is `d > similarity`
- despill (green screen): `G = min(G, (R + B) / 2)`; blue screen: `B = min(B, (R + G) / 2)` (ffmpeg `despill` defaults); other colours are not despilled

## Edge clean-up (shrink, feather)
`shrink` (0..8 px) erodes the cut-out's transparency by that many pixels (removes a coloured fringe); `feather` (0..12 px, Gaussian sigma) softens the edge. Both act on the transparency only (ffmpeg `erosion` with thresholds 0 on the colour planes, `gblur planes=8`) after despill. Defaults 0 = unchanged. Pixels are those of a 1920-wide frame and are scaled to the actual frame, so a preview and a full-size export look the same. The live canvas preview does the same steps on the pixels (`refineAlpha` in `preview/chromakey.ts`).

## Where it sits in a layer's steps
picture in the frame (fill / fit / blur) -> **key** -> effects -> crop -> resize -> rotate -> opacity, fades, transitions -> overlay.
The key's transparency survives the later steps; with a fade or transition it is multiplied with the moving opacity.

## Editor
Inspector > Green screen: tick the box, pick the colour (colour field, Green / Blue, or **Pick from the preview** and click the background),
tune **Match** (how far from the colour still counts as background) and **Soft edge**, keep **Remove colour spill** on for green/blue screens.
The eyedropper only exists while the live preview is showing; it reads the clip's own picture, so it also works on a clip that is already keyed.

## Checking parity
`frontend/e2e/chroma.mjs` (real Chrome, a COPY of a project with prepared media; makes its own green-screen clip).
