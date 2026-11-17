# Talking avatars (task 5.2)

## What exists
Editor > **Talking avatar**: pick a character, a corner and a size, **Add avatar to the video**. The avatar speaks the project's narration and appears on the
timeline as a new video track ("Avatar") with one clip: fitted, scaled, tucked into the corner, **green screen key already on**. Move, resize, trim, add a transition
or delete it like any clip. Several avatars can be added; each gets its own track. Generated avatars are not listed in the credits.

## Renderers (`AVATAR_RENDERER`)
| | |
|---|---|
| `simple` (default) | Three cartoon characters drawn in code (Pillow). **The mouth follows the loudness of the voice** (closed / small / open / wide, held at least two frames), the eyes blink on a regular random-looking schedule, the head rises a little with loud syllables. CPU only, no model files, about 1 s for 7 s of speech. This is open/close timing, **not** matching of speech sounds. |
| `remote` | A GPU service over HTTP: `AVATAR_URL`, optional `AVATAR_TOKEN`. For real lip-sync of a photo/face with MuseTalk, LatentSync, Wav2Lip or a paid API. **Not verified with a real GPU model** (none available here). |
| `none` | off |

### Protocol of the `remote` renderer
`GET /avatars` -> `[{"id","name"}]` · `GET /avatars/{id}/thumb` -> PNG · `POST /render` (form field `avatar`, file `audio`) -> mp4 bytes, as long as the audio, ideally on the key colour `#00ff00`.
`Authorization: Bearer <token>` when a token is configured. `backend/tools/avatar_service.py` is a reference server (it serves the cartoon renderer, so the whole chain can be tried on any computer):
`AVATAR_SERVICE_TOKEN=secret python backend/tools/avatar_service.py --port 9000`, then `AVATAR_RENDERER=remote AVATAR_URL=http://127.0.0.1:9000 AVATAR_TOKEN=secret`.
To get real lip-sync: run a GPU model behind the same three endpoints on a rented GPU or Colab (replace `render()` in the service) and point `AVATAR_URL` at it.

## Placement
The avatar clip uses `fit: "fit"` (the square picture is shown whole), `scale` = its side as a fraction of the frame's short side and a 3 % margin from the corner; the
key makes the green background and the fit bars transparent. The simple renderer draws at 512x512.

## Measured
Unit and API tests, plus real Chrome (`frontend/e2e/avatar.mjs`): the avatar pictures load, the clip appears by itself after the job, keyed + fitted + in the chosen corner, live
preview vs render SSIM 0.92, no key green left, no black bars (a bug the first run found: ffmpeg's `chromakey` replaces the alpha of the fit bars, so bars are now padded with the key colour), console clean.
The timeline is not refetched while a job runs (it returned a 409 that showed up as a console error).
