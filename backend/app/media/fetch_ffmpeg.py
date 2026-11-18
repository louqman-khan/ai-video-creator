"""`avc fetch-ffmpeg`: download a static ffmpeg + ffprobe into `<repo>/tools/bin` (where the app looks first).

Windows and Linux: the BtbN "gpl" builds from GitHub (include libass, harfbuzz, x264/x265, VP9, noise removal and the NVIDIA/Intel/AMD hardware encoders).
macOS (Intel and Apple chips): the static GPL builds from martin-riedl.de (one zip per program)."""

from __future__ import annotations

import platform
import shutil
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from app.config import ROOT
from app.http import make_client

BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
BUILDS = {
    ("windows", "amd64"): "ffmpeg-master-latest-win64-gpl.zip",
    ("linux", "x86_64"): "ffmpeg-master-latest-linux64-gpl.tar.xz",
    ("linux", "amd64"): "ffmpeg-master-latest-linux64-gpl.tar.xz",
}


# macOS: martin-riedl.de publishes static GPL builds (with libass) for both chip families, one zip per program.
MAC_BASE = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"
MAC_ARCH = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}


class FetchError(RuntimeError):
    pass


def build_for(system: str | None = None, machine: str | None = None) -> str:
    key = ((system or platform.system()).lower(), (machine or platform.machine()).lower())
    if key[0] == "darwin" and key[1] in MAC_ARCH:
        return "macos-" + MAC_ARCH[key[1]]
    if key not in BUILDS:
        raise FetchError(
            "There is no automatic download for this system. Install ffmpeg and ffprobe yourself "
            f"and put them on PATH or into {ROOT / 'tools' / 'bin'}.")
    return BUILDS[key]


def extract(archive: Path, dest: Path) -> list[Path]:
    """Copy `ffmpeg` and `ffprobe` (any folder inside the archive) into `dest`."""
    wanted = {"ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"}
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = Path(info.filename).name
                if name in wanted and "/bin/" in info.filename.replace("\\", "/"):
                    target = dest / name
                    with z.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out.append(target)
    else:
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                name = Path(member.name).name
                if member.isfile() and name in wanted and "/bin/" in member.name:
                    f = t.extractfile(member)
                    if f:
                        target = dest / name
                        with target.open("wb") as dst:
                            shutil.copyfileobj(f, dst)
                        out.append(target)
    for p in out:
        p.chmod(0o755)
    if {p.stem for p in out} != {"ffmpeg", "ffprobe"}:
        raise FetchError("The download did not contain ffmpeg and ffprobe.")
    return out


def _fetch_macos(arch: str, dest: Path, progress: Callable[[str], None]) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp, make_client(read_timeout=120.0) as c:
        for tool in ("ffmpeg", "ffprobe"):
            progress(f"Downloading {tool} for macOS ({arch}) ...")
            archive = Path(tmp) / f"{tool}.zip"
            with c.stream("GET", MAC_BASE.format(arch=arch, tool=tool)) as r:
                if r.is_error:
                    raise FetchError(f"Download failed: HTTP {r.status_code}")
                with archive.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            with zipfile.ZipFile(archive) as z:
                member = next((i for i in z.infolist() if Path(i.filename).name == tool and not i.is_dir()), None)
                if member is None:
                    raise FetchError(f"The download did not contain {tool}.")
                target = dest / tool
                with z.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            target.chmod(0o755)
            out.append(target)
    return out


def fetch(dest: Path | None = None, progress: Callable[[str], None] = lambda s: None) -> list[Path]:
    name = build_for()
    dest = dest or ROOT / "tools" / "bin"
    if name.startswith("macos-"):
        return _fetch_macos(name.split("-", 1)[1], dest, progress)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / name
        progress(f"Downloading {name} (about 150-200 MB) ...")
        with make_client(read_timeout=120.0) as c, c.stream("GET", BASE + name) as r:
            if r.is_error:
                raise FetchError(f"Download failed: HTTP {r.status_code}")
            with archive.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        progress("Unpacking ...")
        return extract(archive, dest)


if __name__ == "__main__":  # pragma: no cover
    sys.exit("use `avc fetch-ffmpeg`")
