# Windows

**Status: written to work on Windows, never run on Windows.** Everything was built and tested on macOS (Intel). This page is the list of what was done for Windows, what is untested, and how to check.

## Set-up on a Windows PC
1. Python 3.12: `py -3.12 -m venv .venv` then `.venv\Scripts\activate` and `pip install -e backend[dev]` (add `piper-tts` for English speech).
2. ffmpeg: `avc fetch-ffmpeg` (downloads a static build into `tools\bin`) or `winget install Gyan.FFmpeg`.
3. Web editor: `cd frontend && npm install && npm run build`.
4. Run: `avc app` (one process, opens the browser), or build the desktop app: `cd desktop && npm install && npx tauri build` (needs Rust, the MSVC build tools and the WebView2 runtime, which Windows 11 has).
5. Optional models: `avc fetch-models --clip` (picture ranking), the Urdu/English voices as in `docs/tts.md`.

## Done for Windows (in code, tested here only as far as macOS can test it)
- ffmpeg lookup works with `ffmpeg.exe`; `avc fetch-ffmpeg` downloads/unpacks a Windows build (the archive handling is unit-tested with fake archives; the real download address answers HTTP 200).
- Hardware export: any working H.264 hardware encoder is used (VideoToolbox on macOS, **NVENC / Quick Sync / AMF on Windows**), detected by really encoding a few frames; without one the option is simply not offered.
- Files: replacing a file that a browser is still playing fails on Windows, so renders are written to `*.part.mp4` and swapped in with retries (`app/fsutil.py`); the timeline/project files use the same helper.
- Text: output of ffmpeg and friends is always decoded as UTF-8 (Windows would use the legacy code page and garble Urdu in messages).
- The desktop shell: no console window, process-tree stop, `.venv\Scripts\avc.exe`, process check by `OpenProcess`.
- `.github/workflows/ci.yml` runs the backend tests on Ubuntu, Windows and macOS, the frontend tests, and `cargo test` of the shell on all three.

## Not verified / known risks
- **Nothing ran on Windows.** Expect some first failures; the CI log will name them. Likely places: tests that assume ffmpeg features of the macOS build (libass fonts, `arnndn`), the font folder for libass, long paths, antivirus holding files open.
- Windows ffmpeg builds differ (e.g. noise removal needs `arnndn`; the BtbN build has it, a minimal one may not).
- Proxies/uploads under `work\` live next to the project: keep the project folder out of OneDrive-synced folders (sync clients hold files open).
- The frontend test scripts in `frontend/e2e/*.mjs` point at macOS Chrome (`/Applications/...`); change the path for Windows.
- Not signed: Windows SmartScreen will warn about an unsigned installer.

## How to verify
Push the repository to GitHub and open the *Actions* tab: three columns (Linux, Windows, macOS). Or on a Windows PC run `python -m pytest backend\tests -q` and `cd desktop\src-tauri && cargo test`, then start `avc app` and click through a project.
