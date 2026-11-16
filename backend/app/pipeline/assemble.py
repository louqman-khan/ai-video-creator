"""FFmpeg assembly: normalise each scene's visual to an exact frame count, concat,
then one final encode that adds the narration audio and burns captions."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.media import ffmpeg
from app.models import Scene, ScenePick

log = logging.getLogger("avc.assemble")

@dataclass(frozen=True)
class RenderProfile:
    """Speed/quality trade-off. `preview` makes the edit loop fast; `final` is what you publish."""

    name: str
    seg_preset: str
    seg_crf: int
    final_preset: str
    final_crf: int
    audio_bitrate: str


FINAL = RenderProfile("final", "veryfast", 20, "medium", 20, "192k")
PREVIEW = RenderProfile("preview", "ultrafast", 28, "ultrafast", 30, "96k")


def _enc(p: RenderProfile) -> list[str]:
    # -map_metadata -1 / -write_tmcd 0: drop the source clips' metadata and timecode track
    return ["-c:v", "libx264", "-preset", p.seg_preset, "-crf", str(p.seg_crf), "-pix_fmt", "yuv420p", "-an",
            "-map_metadata", "-1", "-write_tmcd", "0"]


def scene_frames(scenes: list[Scene], fps: int) -> list[int]:
    """Frames per scene from cumulative rounding, so total length never drifts."""
    marks = [round(s.start * fps) for s in scenes] + [round(scenes[-1].end * fps)]
    return [max(1, b - a) for a, b in zip(marks, marks[1:])]


def _segment_args(pick: ScenePick, frames: int, w: int, h: int, fps: int, dst: Path, profile: RenderProfile = FINAL) -> list[str]:
    _ENC = _enc(profile)
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if pick.asset is None or not pick.local_path:
        return ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}", "-frames:v", str(frames), *_ENC, str(dst)]
    if pick.asset.kind == "video":
        return [
            "-stream_loop", "-1", "-i", pick.local_path, "-frames:v", str(frames),
            "-vf", f"{cover},fps={fps}", *_ENC, str(dst),
        ]  # fmt: skip
    # still image: slow Ken Burns zoom, computed on a 2x canvas to avoid jitter
    zoom = (
        f"scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
        f"zoompan=z='1+0.10*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps},setsar=1"
    )
    return ["-loop", "1", "-framerate", str(fps), "-i", pick.local_path, "-frames:v", str(frames),
            "-vf", zoom, *_ENC, str(dst)]  # fmt: skip


def segment_key(pick: ScenePick, frames: int, w: int, h: int, fps: int, profile: RenderProfile = FINAL) -> str:
    """Fingerprint of everything that shapes one scene's clip; same key = the file is reusable."""
    source = ""
    if pick.asset and pick.local_path:
        p = Path(pick.local_path)
        source = f"{pick.asset.id}|{pick.asset.kind}|{p.stat().st_size if p.exists() else 0}"
    return hashlib.sha1(f"{source}|{frames}|{w}x{h}@{fps}|{profile.name}|v1".encode()).hexdigest()[:16]


def build_segments(
    scenes: list[Scene], picks: list[ScenePick], out_dir: Path, w: int, h: int, fps: int,
    profile: RenderProfile = FINAL,
) -> list[Path]:
    """One clip per scene. Clips whose inputs did not change are reused (a visual swap
    re-encodes one scene instead of all of them)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    try:
        manifest: dict[str, str] = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, ValueError):
        manifest = {}
    by_scene = {p.scene_id: p for p in picks}
    paths: list[Path] = []
    for scene, frames in zip(scenes, scene_frames(scenes, fps)):
        dst = out_dir / f"seg_{scene.id:03d}.mp4"
        pick = by_scene.get(scene.id) or ScenePick(scene_id=scene.id)
        key = segment_key(pick, frames, w, h, fps, profile)
        if dst.exists() and manifest.get(dst.name) == key:
            paths.append(dst)
            continue
        manifest.pop(dst.name, None)  # never trust a half-written or outdated file
        try:
            ffmpeg.run(_segment_args(pick, frames, w, h, fps, dst, profile))
        except ffmpeg.FfmpegError as e:
            log.warning("scene %d: could not use %s (%s); black placeholder", scene.id, pick.local_path, e)
            ffmpeg.run(_segment_args(ScenePick(scene_id=scene.id), frames, w, h, fps, dst, profile))
            key = "placeholder"  # not a valid key for the real pick: it is retried next time
        manifest[dst.name] = key
        manifest_path.write_text(json.dumps(manifest), "utf-8")
        paths.append(dst)
    keep = {p.name for p in paths}
    for old in out_dir.glob("seg_*.mp4"):  # scenes that no longer exist
        if old.name not in keep:
            old.unlink(missing_ok=True)
            manifest.pop(old.name, None)
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    return paths


def concat_and_finish(
    segments: list[Path],
    audio: Path,
    captions: Path | None,
    out: Path,
    work: Path,
    fonts_dir: Path,
    audio_duration: float,
    profile: RenderProfile = FINAL,
    joined_name: str = "concat.mp4",  # the caption-free video; the caption preview reads it
) -> None:
    listing = work / f"{joined_name}.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments), "utf-8")
    joined = work / joined_name
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])

    args = ["-i", str(joined), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"]
    if captions:
        if not ffmpeg.has_filter("subtitles"):
            raise ffmpeg.FfmpegError(
                "This ffmpeg has no 'subtitles' filter (libass missing). "
                "Reinstall with libass support or run with --no-captions."
            )
        vf = f"subtitles='{ffmpeg.filter_escape(captions.name)}'"
        if fonts_dir.is_dir():
            vf += f":fontsdir='{ffmpeg.filter_escape(str(fonts_dir.resolve()))}'"
        args += ["-vf", vf]
    args += [
        "-c:v", "libx264", "-preset", profile.final_preset, "-crf", str(profile.final_crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", profile.audio_bitrate, "-t", f"{audio_duration:.3f}",
        "-map_metadata", "-1", "-write_tmcd", "0",
        "-movflags", "+faststart", str(out.resolve()),
    ]  # fmt: skip
    ffmpeg.run(args, cwd=captions.parent if captions else None)
