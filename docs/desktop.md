# Desktop app (Tauri) and one-process mode

## Three ways to run it
| | Command | What you get |
|---|---|---|
| Developer mode | `avc serve` (port 8742) + `npm run dev` in `frontend/` (port 5742) | hot reload |
| One process | `avc app` | the server **and** the built web editor on one port; opens your browser. Needs `npm run build` in `frontend/` once. |
| Desktop app | `desktop/` (Tauri) | a native window that starts `avc app` by itself on a free port and stops it when you close the window |

## How the desktop app works
`desktop/src-tauri/src/main.rs` opens a window with a small local loading page (`desktop/ui/loading.html`), starts the Python server (`backend.rs`), waits until `GET /api/health` answers,
then points the window at `http://127.0.0.1:<port>/`. The editor is the ordinary web app; nothing else is bundled in the window. If the server cannot start the window shows why (with the last
lines of `work/desktop.log`). Closing the window stops the server and anything it started (ffmpeg); if the app is killed instead of closed, the server notices (`AVC_PARENT_PID`) and stops within a few seconds.
The same Rust code builds for macOS, Windows and Linux (Windows: no console window, `taskkill /T` to stop the tree, `.venv\Scripts\avc.exe`).

Where it looks for things: the project folder = `AVC_HOME`, or the nearest folder above the program with `backend/pyproject.toml`; the program = `AVC_BIN`, or `<project>/.venv/bin/avc` (`.venv\Scripts\avc.exe` on Windows), or `avc` on PATH.

## Build it
```
cd frontend && npm install && npm run build          # the web editor the server shows
cd ../desktop && npm install && npx tauri build      # needs the Rust toolchain (https://rustup.rs)
```
macOS result: `desktop/src-tauri/target/release/bundle/macos/AI Video Creator.app` (verified here). Windows: an `.msi`/`.exe` installer; Linux: `.deb` (**not built or tried here**, see `docs/windows.md`).
`npx tauri dev` runs the shell without bundling.

## What it is NOT (yet)
- **Not self-contained.** It starts the Python environment of this project folder (`.venv`, models, `tools/bin`); it does not carry Python inside the app. A real installer for other people would
  have to bundle Python (for example with PyInstaller or a standalone Python build) and the models, and be code-signed (macOS notarisation, Windows signing).
- On macOS the `.dmg` step failed in a headless session (it drives Finder); the `.app` itself is fine, so `tauri.conf.json` asks for `app`, `nsis`, `msi`, `deb`.
- The window itself could not be photographed from this automated session (no screen-recording permission): what was verified is the behaviour behind it, see `docs/ROADMAP.md`.
