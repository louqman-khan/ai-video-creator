# Editor guide

Open a finished project. Above the timeline is the preview (**Live** shows your edits instantly; **Rendered** is the exact low-resolution render).

## The timeline
Tracks (top to bottom): captions, video (higher tracks cover lower ones), audio. Click the ruler to move the playhead; zoom with `+` `-` `0` or Ctrl/Cmd + wheel.

| Do this | Result |
|---|---|
| Drag a clip / its edges | move (also to another track of the same kind) / trim; snaps to neighbours and the playhead |
| `S`, `Delete`, `Shift+Delete` | split at the playhead, remove and leave a gap, remove and close the gap |
| `Ctrl/Cmd+D`, `Ctrl/Cmd+Z`, `Ctrl/Cmd+Shift+Z` | duplicate, undo, redo |
| `[` `]`, `Alt+arrows`, `Esc` | select previous / next clip, nudge it, clear the selection |
| Track label buttons | mute, lock, duck (music under narration), remove an empty track |
| **+ Video track / + Audio track** | more layers (picture-in-picture, music) |
| **Frame**, **Pictures** | 16:9, 9:16, 1:1, 4:5; fill / fit with bars / fit over a blurred copy |

Edits save by themselves and the preview re-renders in the background. If another window changed the project you choose to keep or discard your edits.

## Selected clip (inspector)
Pictures: opacity, size, position presets, turn, crop, fit, fades, **transition** into the clip, **green screen** (with an eyedropper), brightness / contrast /
saturation / blur. Audio: volume, fades. With the Live preview showing you can also drag the picture, its corners and the round handle on the preview itself.

## Media
**Add media...**: files already in the project, stock search (videos, photos, music, sound effects; free-to-reuse sources only, credits are collected
automatically) or your own files (you confirm you have the right to use them). Formats: mp4, mov, mkv, webm (H.264, HEVC, ProRes, VP9), mp3, wav, m4a, flac, ogg, png, jpg, webp; HDR is tone-mapped.

## Export
Format, size (720p / 1080p / 4K), encoder (best quality or the fast hardware one) and a time estimate. `CREDITS.txt` lists the media that needs a credit.
Free disk space from the projects page (*Disk space*) or with `avc clean`.
