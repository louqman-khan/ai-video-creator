# Import formats and export presets (task 4.12)

## Import
Accepted by content (not by name): mp4/mov/mkv/webm video with H.264, HEVC, ProRes, VP9, AV1 where ffmpeg can decode; mp3, wav, m4a/aac, flac, ogg audio;
png, jpg, webp images. Every file is probed (limits on length, size, fps, pixels), prepared into a 960x540 proxy with a keyframe every 0.5 s, a waveform
and a filmstrip. Rotation metadata is applied, variable frame rate becomes 30 fps, **HDR (PQ/HLG) is tone-mapped to SDR** (`derive.TONEMAP`) in the proxy
*and* in the export, so the live preview and the render agree.

## Export
| | |
|---|---|
| Format | 16:9, 9:16, 1:1, 4:5 (default: the editor's frame) |
| Size (`preset`) | 720p, 1080p, 4k = the short side of the picture is 720 / 1080 / 2160 pixels (`sizes.render_size`) |
| Encoder | `software` = x264 (best quality for the size, slower); `hardware` = VideoToolbox (several times faster, larger files; only offered when the computer has it) |

`POST /api/projects/{id}/export {aspect, preset, encoder}` -> 202; `GET .../export/estimate?aspect&preset&encoder` -> `{seconds, learned, width, height}`.
The estimate = fixed overhead + cost x video seconds x megapixels; the cost starts from measured defaults and is replaced by a running average of the
exports this computer has done (`pipeline/export_speed.py`, stored in `work/cache/export_speed.json`).

Measured on the development Mac (Intel i7-4980HQ) for a 12 s project: 720p software 12 s, 1080p software 19 s, 1080p hardware 8 s, 4K hardware 20 s, 4K software 70 s.
