# Hardening (task 4.13)

## Budgets and how they are checked
| Budget | Measured (Intel i7-4980HQ, real Chrome, 309-clip timeline, live preview running) |
|---|---|
| dragging a clip: >= 50 fps | 58-59 fps, p95 frame 16.8 ms |
| seek: picture within 150 ms | median 1-2 ms, p95 69-94 ms, max 134 ms (proxies have a keyframe every 0.5 s) |
| accessibility | axe-core: 0 violations (editor, projects, new project; light and dark) |

Run `node frontend/e2e/hardening.mjs <project-id>` (edits the project: use a COPY with prepared media; it builds the 309-clip timeline itself) and
`node frontend/e2e/a11y-pages.mjs <ui-url> [project-id]`. Stop all renders before replacing a project folder under a running server.

## Keyboard
Everything in the timeline works without a mouse: `Tab` to the track area, `[` / `]` select the previous / next clip (it is announced and the playhead jumps to
its start), `Alt` + `<-` / `->` move the clip by a frame (`Shift`: a second), `S` split, `Delete` / `Shift+Delete` remove, `Ctrl/Cmd+Z` undo, `Esc` clears the selection.
Every control in the inspector, bin and export panel is a native form control with a label.

## Conflicts
Saving sends the revision it was based on. If another window changed the timeline the app stops saving and offers **Keep my edits** (your version
becomes the newest) or **Discard my edits and reload**. Nothing is lost silently either way.

## Disk
`avc clean [--days 7] [--segments] [--dry-run]`, the *Disk space* panel on the projects page, `GET /api/storage`, `POST /api/storage/clean`.
Removes only what can be made again: stock media nothing references (older than `--days`), editing proxies of files no project uses, old render caches
(`--segments`), search results older than `--days`, abandoned `.part` files. Never: uploads, exports, timelines, credits, anything younger than an hour,
anything outside the work folder.
