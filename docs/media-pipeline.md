# Editor media pipeline (task 4.2)

Every asset on a timeline (stock clip, narration, upload) gets small derived files the editor can use
instantly. The original is never modified. Code: `backend/app/media/ingest.py`, `derive.py`,
`backend/app/api/media.py`.

## Derived files (per asset, in `work/cache/proxies/<key>/`)

| File | What | Why |
|---|---|---|
| `proxy.mp4` | fits in 960x540 (540x960 for portrait), never enlarged, constant 30 fps, **keyframe every 0.5 s**, rotation applied, HDR tone-mapped to SDR, no audio | fast scrubbing (decision D3: median 21 ms vs 169 ms without frequent keyframes); variable-frame-rate phone video becomes steady |
| `proxy.jpg` / `.png` | images, max 1280 px wide (PNG when it has transparency) | the compositor draws it directly |
| `proxy_audio.m4a` | AAC stereo 48 kHz | played next to the muted video proxy |
| `peaks.json` | waveform, 100 and 10 peaks per second, 0-255 | timeline waveform |
| `film.jpg` + `film.json` | one-row sprite of 160x90 thumbnails (at most ~120) | timeline filmstrip |
| `state.json` | status, file list, probe info, bytes | survives restarts; stale if the source file changes (key = path + size + mtime) |

Preparation runs in one background worker thread. It starts when a timeline is first built and whenever
`GET /media` finds something unprepared (so it heals after a restart). Failures are recorded; `POST
/media/prepare` retries them. Error text shown to the browser is generic; details stay in the server log.

## Endpoints (`/api/projects/{id}/...`)

`GET /media` (status per asset), `POST /media` (upload), `DELETE /media?asset=` (uploads only, and only if no
clip uses it), `POST /media/prepare`, `GET /media/{proxy|audio|peaks|film|film.json}?asset=`, `GET /disk`.
Assets are addressed by `?asset=<id>` and looked up by key in the timeline; an id never becomes a file path.

## Upload rules

- Must tick "I have the right to use this file" (decision D6).
- Recognised by the first bytes of the file, never by its name or extension (mp4/mov, webm/mkv, mp3, wav,
  m4a/aac, flac, ogg/opus, png, jpg, webp). Stored as `uploads/<random>.<real extension>`.
- Limits (settings): 500 MB, 30 minutes, 64 megapixels, 16384 px per side, 240 fps, 100 uploads per project.
- Cover art inside an mp3 is not treated as video.
- Adding an asset is append-only and does **not** change the timeline revision.
- Stock downloads are checked the same way (a host answering 200 with a web page is dropped).

## Security note (tested, not assumed)

On the bundled FFmpeg 9.0.2 a playlist, concat script or SDP file disguised as `.mp4/.mov/.mkv/.wav/.mp3/.jpg`
causes **no network request and no read of other files** (it simply fails to open). This is pinned by a
regression test, so a different FFmpeg build that behaves differently will be noticed. The signature check
adds clear error messages and a stable stored extension on top.

## Known limits

- HDR tone-mapping runs and produces valid SDR, but its look is **unverified**: the only test clip was SDR
  re-encoded as PQ (a Hable curve makes it about 30 % darker than the original). Needs real HDR footage;
  full-quality mapping for export is task 4.12.
- EXIF rotation of still photos is untested (video rotation is tested).
- Starlette spools a whole upload to disk before our size check runs; an announced oversize body is refused
  early, a chunked one is not. Acceptable while the server is localhost-only.
