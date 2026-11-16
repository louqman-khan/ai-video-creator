# Timeline document v1

Source: `backend/app/timeline/models.py` (models) and `validate.py` (rules). API: `GET/PUT/DELETE
/api/projects/{id}/timeline`. Design background: `docs/STEP4_PLAN.md`, decision D1 in `docs/decisions.md`.

## Shape

```jsonc
{
  "schema_version": 1,
  "rev": 3,                    // +1 on every accepted write
  "fps": 30, "aspect": "16:9",
  "tracks": [ { "id": "V1", "kind": "video|audio|caption", "name": "", "muted": false, "locked": false } ],
  "clips":  [ {
      "id": "scene-1", "track": "V1", "kind": "video|image|audio|caption",
      "asset": "pixabay:123",  // key into assets; null for captions
      "start": 0, "duration": 120, "in_point": 0,   // integer FRAMES (timeline position, length, offset into the media)
      "loop": false,           // a video shorter than the clip repeats
      "volume": 1.0, "fade_in": 0, "fade_out": 0,
      "transform": { "x": 0, "y": 0, "scale": 1, "rotation": 0, "opacity": 1, "crop": [0,0,0,0] },
      "effects": [], "transition_in": null,          // reserved: used from tasks 4.9-4.10
      "text": null,            // caption clips
      "words": [],             // narration clips: recognised words in source frames
      "meta": {}               // small plain JSON (e.g. the scene's text)
  } ],
  "assets": { "pixabay:123": { "kind": "video", "duration": 240, "license": "...", "attribution": "...", ... } },
  "caption_style": null, "meta": {}
}
```

The browser receives assets **without** `path` and `url` (those stay on the server) and may only send
`base_rev`, `tracks`, `clips` and `caption_style` back: assets, `rev` and `fps` cannot be changed by a client.

## Rules enforced on every write (422 with all problems listed)

- Times are non-negative integers; clips have `duration >= 1`; unknown fields are errors; every number is finite.
- Ids: clip/track ids are `[A-Za-z0-9_\-:.]{1,64}`; asset ids are 1-200 printable characters (providers use file names).
- Track kinds accept: video track = video/image clips, audio = audio clips, caption = caption clips.
- Every non-caption clip references an existing asset of the same kind; captions have no asset and non-empty text.
- A clip may not run past its media (`in_point + duration <= asset.duration`) unless `loop`, or it is an image (no in-point).
- No two clips on one track overlap (touching is fine). Transitions will relax this in 4.9.
- Fades and transitions are not longer than the clip; only audio clips carry words.
- Limits: 16 tracks, 2000 clips, 20 000 words per clip, 8 effects per clip, 300 characters of caption text.

## Conflicts

`PUT` must send the `rev` it started from. If another tab saved first the server answers **409** with the
current revision in the message and the `X-Current-Rev` header; nothing is overwritten.

## Relationship to the Step 3 screens

A timeline is built from a project's scenes, assets, captions and transcript the first time it is read.
While it has never been edited (`rev == 1`) it is disposable: any re-render drops it and it is rebuilt. Once it
has been edited (`rev > 1`) it is the only truth: swap-visual, caption editing and export from the old screens
answer 409 until the timeline is reset (`DELETE ...?discard_edits=true`). Task 4.3 re-points those screens.
