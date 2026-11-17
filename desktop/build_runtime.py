#!/usr/bin/env python3
"""Builds desktop/src-tauri/resources/: everything the installed app carries so the user needs no Python, Node or terminal.

    resources/runtime/     a relocatable Python (python-build-standalone) with the backend and its packages installed
    resources/frontend/    the built web app (frontend/dist)
    resources/fonts/       caption fonts
    resources/bin/         ffmpeg + ffprobe (from tools/bin, or PATH)

Run on the platform you are building for (a macOS runtime is not a Windows runtime):  python3 desktop/build_runtime.py
Needs internet (python-build-standalone from GitHub, packages from PyPI). Re-running replaces resources/."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "src-tauri" / "resources"
PY_MINOR = "3.12"
API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
TRIPLES = {
    ("darwin", "arm64"): "aarch64-apple-darwin", ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("windows", "amd64"): "x86_64-pc-windows-msvc", ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
}


def triple() -> str:
    key = (platform.system().lower(), platform.machine().lower())
    if key not in TRIPLES:
        sys.exit(f"No prebuilt Python for {key}.")
    return TRIPLES[key]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "avc-build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def download_python(dest: Path) -> None:
    want = triple()
    assets = json.loads(get(API))["assets"]
    pick = [a for a in assets if a["name"].startswith(f"cpython-{PY_MINOR}.") and a["name"].endswith(f"-{want}-install_only.tar.gz")]
    if not pick:
        sys.exit(f"No Python {PY_MINOR} build for {want} in the latest python-build-standalone release.")
    a = pick[0]
    print("downloading", a["name"])
    data = get(a["browser_download_url"])
    digest = (a.get("digest") or "").removeprefix("sha256:")
    if digest and hashlib.sha256(data).hexdigest() != digest:
        sys.exit("Checksum mismatch for the Python download. Not using it.")
    with tempfile.TemporaryDirectory() as t:
        tgz = Path(t) / "py.tar.gz"
        tgz.write_bytes(data)
        with tarfile.open(tgz) as tf:
            tf.extractall(t, filter="data")
        shutil.move(str(Path(t) / "python"), dest)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    runtime = OUT / "runtime"
    download_python(runtime)
    py = runtime / ("python.exe" if platform.system() == "Windows" else "bin/python3")
    print("installing the backend ...")
    subprocess.run([str(py), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", f"{REPO / 'backend'}[tts]"], check=True)
    dist = REPO / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        sys.exit("Build the frontend first: (cd frontend && npm run build)")
    shutil.copytree(dist, OUT / "frontend")
    shutil.copytree(REPO / "assets" / "fonts", OUT / "fonts")
    (OUT / "bin").mkdir()
    exe = ".exe" if platform.system() == "Windows" else ""
    for tool in ("ffmpeg", "ffprobe"):
        src = REPO / "tools" / "bin" / (tool + exe)
        found = src if src.is_file() else (Path(p) if (p := shutil.which(tool)) else None)
        if not found:
            sys.exit(f"{tool} not found. Run `avc fetch-ffmpeg` (Windows/Linux) or `brew install ffmpeg` (macOS) first.")
        shutil.copy2(found, OUT / "bin" / (tool + exe))
    # smoke test: the relocated runtime can import the app
    subprocess.run([str(py), "-I", "-c", "import cli.main, app.api.main; print('runtime ok')"], check=True)
    mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"done: {OUT} ({mb:.0f} MB)")


if __name__ == "__main__":
    main()
