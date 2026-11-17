"""Render profiles and the final FFmpeg pass: join the pre-rendered segments without re-encoding, then one
encode that adds the audio and burns the captions. The segments themselves come from the timeline
renderer (`app.timeline.render`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.media import ffmpeg

@dataclass(frozen=True)
class RenderProfile:
    """Speed/quality trade-off. `preview` makes the edit loop fast; `final` is what you publish."""

    name: str
    seg_preset: str
    seg_crf: int
    final_preset: str
    final_crf: int
    audio_bitrate: str
    encoder: str = "libx264"  # or h264_videotoolbox (hardware: ~6x faster on the dev Mac, larger files)
    bitrate: str = ""  # used by hardware encoders, which have no CRF


FINAL = RenderProfile("final", "veryfast", 20, "medium", 20, "192k")
PREVIEW = RenderProfile("preview", "ultrafast", 28, "ultrafast", 30, "96k")
FINAL_FAST = RenderProfile("final-fast", "veryfast", 20, "medium", 20, "192k", encoder="h264_videotoolbox", bitrate="12M")
PROFILES = {p.name: p for p in (FINAL, PREVIEW, FINAL_FAST)}


def export_profile(encoder: str, width: int, height: int) -> RenderProfile:
    """The profile of an export: "software" (x264, best quality per size, slower) or "hardware" (VideoToolbox, several times
    faster, bigger files; the bitrate grows with the picture size)."""
    if encoder == "hardware":
        from app.media import ffmpeg

        mbps = max(4, round(12 * (width * height / (1920 * 1080)) ** 0.8))  # 720p ~ 7M, 1080p 12M, 4K ~ 36M
        return RenderProfile("final-fast", "veryfast", 20, "medium", 20, "192k", encoder=ffmpeg.hardware_encoder() or "h264_videotoolbox", bitrate=f"{mbps}M")
    return FINAL


def video_codec_args(p: RenderProfile, final: bool) -> list[str]:
    if p.encoder == "libx264":
        return ["-c:v", "libx264", "-preset", p.final_preset if final else p.seg_preset, "-crf", str(p.final_crf if final else p.seg_crf)]
    return ["-c:v", p.encoder, "-b:v", p.bitrate]


def _enc(p: RenderProfile) -> list[str]:
    # -map_metadata -1 / -write_tmcd 0: drop the source clips' metadata and timecode track
    return [*video_codec_args(p, final=False), "-pix_fmt", "yuv420p", "-an", "-map_metadata", "-1", "-write_tmcd", "0"]


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
        *video_codec_args(profile, final=True), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", profile.audio_bitrate, "-t", f"{audio_duration:.3f}",
        "-map_metadata", "-1", "-write_tmcd", "0",
        "-movflags", "+faststart", str(out.resolve()),
    ]  # fmt: skip
    ffmpeg.run(args, cwd=captions.parent if captions else None)
