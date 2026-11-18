import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.media.fetch_ffmpeg import FetchError, build_for, extract


def test_the_right_build_is_chosen_per_system_and_others_are_explained():
    assert build_for("Windows", "AMD64").endswith("win64-gpl.zip")
    assert build_for("Linux", "x86_64").endswith("linux64-gpl.tar.xz")
    assert build_for("Darwin", "x86_64") == "macos-amd64" and build_for("Darwin", "arm64") == "macos-arm64"
    with pytest.raises(FetchError, match="no automatic download"):
        build_for("FreeBSD", "x86_64")


def test_a_windows_zip_is_unpacked_into_a_flat_folder(tmp_path):
    z = tmp_path / "w.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe", b"MZ-ffmpeg")
        f.writestr("ffmpeg-master-latest-win64-gpl/bin/ffprobe.exe", b"MZ-ffprobe")
        f.writestr("ffmpeg-master-latest-win64-gpl/bin/ffplay.exe", b"MZ-ffplay")
        f.writestr("ffmpeg-master-latest-win64-gpl/doc/readme.txt", b"x")
    out = extract(z, tmp_path / "bin")
    assert sorted(p.name for p in out) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (tmp_path / "bin" / "ffmpeg.exe").read_bytes() == b"MZ-ffmpeg" and not (tmp_path / "bin" / "ffplay.exe").exists()


def test_a_linux_tarball_is_unpacked_and_made_executable(tmp_path):
    t = tmp_path / "l.tar.xz"
    src = tmp_path / "src"
    (src / "ffmpeg-x" / "bin").mkdir(parents=True)
    for n in ("ffmpeg", "ffprobe"):
        (src / "ffmpeg-x" / "bin" / n).write_bytes(b"ELF")
    with tarfile.open(t, "w:xz") as f:
        f.add(src / "ffmpeg-x", arcname="ffmpeg-x")
    out = extract(t, tmp_path / "bin")
    assert sorted(p.name for p in out) == ["ffmpeg", "ffprobe"]
    if os.name != "nt":                                              # Windows has no executable bit
        assert (tmp_path / "bin" / "ffmpeg").stat().st_mode & 0o100


def test_an_archive_without_the_tools_is_refused(tmp_path):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("readme.txt", b"nothing")
    with pytest.raises(FetchError):
        extract(z, tmp_path / "bin")
