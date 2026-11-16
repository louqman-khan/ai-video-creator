"""FFmpeg assembly: normalise each scene's visual to an exact frame count, concat,
then one final encode that adds the narration audio and burns captions."""

from __future__ import annotations

import logging
from pathlib import Path

from app.media import ffmpeg
from app.models import Scene, ScenePick

log = logging.getLogger("avc.assemble")

_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]


def scene_frames(scenes: list[Scene], fps: int) -> list[int]:
    """Frames per scene from cumulative rounding, so total length never drifts."""
    marks = [round(s.start * fps) for s in scenes] + [round(scenes[-1].end * fps)]
    return [max(1, b - a) for a, b in zip(marks, marks[1:])]


def _segment_args(pick: ScenePick, frames: int, w: int, h: int, fps: int, dst: Path) -> list[str]:
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


def build_segments(
    scenes: list[Scene], picks: list[ScenePick], out_dir: Path, w: int, h: int, fps: int
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_scene = {p.scene_id: p for p in picks}
    paths: list[Path] = []
    for scene, frames in zip(scenes, scene_frames(scenes, fps)):
        dst = out_dir / f"seg_{scene.id:03d}.mp4"
        pick = by_scene.get(scene.id) or ScenePick(scene_id=scene.id)
        try:
            ffmpeg.run(_segment_args(pick, frames, w, h, fps, dst))
        except ffmpeg.FfmpegError as e:
            log.warning("scene %d: could not use %s (%s); black placeholder", scene.id, pick.local_path, e)
            ffmpeg.run(_segment_args(ScenePick(scene_id=scene.id), frames, w, h, fps, dst))
        paths.append(dst)
    return paths


def concat_and_finish(
    segments: list[Path],
    audio: Path,
    captions: Path | None,
    out: Path,
    work: Path,
    fonts_dir: Path,
    audio_duration: float,
) -> None:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments), "utf-8")
    joined = work / "concat.mp4"
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
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{audio_duration:.3f}",
        "-movflags", "+faststart", str(out.resolve()),
    ]  # fmt: skip
    ffmpeg.run(args, cwd=captions.parent if captions else None)
