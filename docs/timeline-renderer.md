# Timeline renderer v1 (task 4.3)

Code: `backend/app/timeline/render.py`. Design background: decision D2 in `docs/decisions.md`.
One renderer serves the CLI (`avc make`), the web app and the editor: `Pipeline.run` builds (or loads) the
project's timeline and renders it, and a project whose timeline has been edited skips the analysis stages and
renders the saved timeline directly.

## How a render works

1. **Plan.** The picture timeline is cut at every frame where the set of visible clips changes (clip starts
   and ends on any video track). Gaps become empty segments (black). Muted video tracks are hidden.
2. **Segments.** Each segment gets its own FFmpeg filtergraph: every visible clip is cover-fitted to the
   frame, layers are stacked bottom to top with `overlay` (honouring `transform.opacity`), then encoded.
   Looping videos wrap around their own length; Ken Burns stills zoom over the *whole clip* (the segment only
   knows how far in it starts), so cutting a clip into segments does not change its pixels.
3. **Cache.** A segment is saved as `tl_segments[_preview]/seg_<key>.mp4`. The key hashes only what is visible in
   that segment: each clip's media file (path, size, modified time), offset, loop, opacity, zoom phase, plus the
   frame count, size, fps, encoder profile and the renderer version. Changing one clip therefore re-renders only
   the segments it touches; clip ids are labels and never change a key. Unreferenced segment files are removed.
   Writes go to `*.part.mp4` and are renamed, so an interrupted render never leaves a reusable half file.
4. **Join + captions.** Segments are concatenated without re-encoding into `concat[_preview].mp4` (the
   caption-free video that the caption preview draws on), then one encode adds the audio and burns the captions.
5. **Audio.** A separate lossless mixdown (`audio_mix/mix_<key>.flac`, 48 kHz stereo): every unmuted audio clip is
   trimmed, `volume`-scaled, faded, delayed to its position and mixed (`amix`, no automatic gain); the result is
   padded/cut to the timeline length. With no audio clips the video still gets a silent track. Then loudness
   normalisation (two-pass, `-14 LUFS` by default) when enabled. Video clips' own sound is not used.
6. **Captions.** Burned from the caption clips with the timeline's `caption_style` (frames to times, so cue edges
   are quantised to the frame grid).

## Encoder profiles

`FINAL` (x264, best quality), `PREVIEW` (960x540, fast) and `FINAL_FAST` (`h264_videotoolbox`, about 6x faster
on the development Mac, larger files). If the encoder is missing the renderer falls back to software with a
warning. The profile exists in code; choosing it from the API/UI is task 4.12.

## What it refuses (loudly)

`RenderUnsupported` lists anything it cannot do yet, instead of silently ignoring it: transitions, fades on
pictures, crop/position/scale/rotation, effects other than Ken Burns on stills (zoom on video included).
For a preview job this keeps the last good preview and shows "Not supported yet: ..." as a message on the project.
These arrive in tasks 4.7 to 4.10.

## Safety nets

- A still image that cannot be decoded is detected before use (`ffmpeg -loop 1` on a broken picture hangs
  forever with no output) and that segment becomes black.
- Any segment that fails to render becomes black with a warning; the render continues.
- All numbers in filtergraphs come from validated timeline fields, never from user strings.

## Measured (real project, development Mac)

- Parity with the previous renderer on the Urdu demo project, same caption style: **SSIM 0.9996 (final) and
  0.9983 (preview)**; every caption-free picture segment is identical (SSIM 1.0000). The only differences are
  caption cue edges moved to the frame grid.
- Edit loop through the API: preview after editing one clip **1.7 s** (2 of 3 segments reused); 1080p export
  16.8 s after one edit vs 20.7 s from cold, the remainder being the full final encode that burns captions
  (what the hardware encoder will shrink).
- Cutting a clip into segments does not change its pixels (test: identical wherever no overlay is involved; an
  opacity-0 overlay is visually the same but not bit-exact because of colour-format conversion).

## Known limits

- Output audio is now stereo (it used to keep the source's channel layout).
- Compositing several visible layers is tested for colour and opacity only; picture-in-picture arrives in 4.7.
