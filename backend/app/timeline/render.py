"""Timeline renderer v1 (task 4.3, decision D2).

The timeline is cut at every frame where the set of visible clips changes. Each segment is rendered on
its own with a small FFmpeg filtergraph and cached under a key made of *only what is visible in it*, so
changing one clip re-renders only the segments it touches. Segments are joined without re-encoding,
audio is a separate mixdown, and captions are burned in the final pass.

Features the renderer cannot do yet are refused loudly (`RenderUnsupported`), never silently ignored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from collections.abc import Callable
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.media import ffmpeg, loudness
from app.pipeline import assemble
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.captions import Cue, cues_to_ass
from app.pipeline.sizes import base_video_name, render_size
from app.timeline.models import Clip, Timeline

log = logging.getLogger("avc.render")
RENDER_VERSION = "r1"  # bump when the pictures a segment produces change: invalidates every cached segment
Progress = Callable[[str, float, str], None]


class RenderUnsupported(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Not supported yet: " + "; ".join(problems[:6]) + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""))
        self.problems = problems


# ------------------------------------------------------------------ what we can render

def unsupported_features(tl: Timeline) -> list[str]:
    problems: list[str] = []
    for c in tl.clips:
        if c.kind == "caption":
            continue
        t = c.transform
        if c.kind in ("video", "image"):
            if c.transition_in:
                problems.append(f"clip '{c.id}': transitions")
            if c.fade_in or c.fade_out:
                problems.append(f"clip '{c.id}': fades on pictures")
            if t.rotation or any(t.crop):
                problems.append(f"clip '{c.id}': crop and rotation")
            for e in c.effects:
                if e.type != "kenburns":
                    problems.append(f"clip '{c.id}': the '{e.type}' effect")
                elif c.kind != "image":
                    problems.append(f"clip '{c.id}': zoom on video")
        elif c.effects or c.transition_in:
            problems.append(f"clip '{c.id}': effects or transitions on audio")
    return problems


# ------------------------------------------------------------------ planning

@dataclass(frozen=True)
class Segment:
    start: int  # frames
    end: int
    layers: tuple[Clip, ...]  # visible clips, bottom to top

    @property
    def frames(self) -> int:
        return self.end - self.start


def _track_order(tl: Timeline) -> dict[str, int]:
    return {t.id: i for i, t in enumerate(tl.tracks)}


def plan_segments(tl: Timeline) -> list[Segment]:
    """Cut the picture timeline wherever the set of visible clips changes. Gaps become empty segments (black)."""
    order = _track_order(tl)
    hidden = {t.id for t in tl.tracks if t.muted}  # a muted video track is hidden
    clips = [c for c in tl.clips if c.kind in ("video", "image") and c.track not in hidden]
    total = tl.duration
    bounds = sorted({0, total, *(c.start for c in clips), *(c.start + c.duration for c in clips)})
    segs: list[Segment] = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        layers = tuple(sorted((c for c in clips if c.start <= a < c.start + c.duration), key=lambda c: order[c.track]))
        if segs and segs[-1].layers == layers:
            segs[-1] = Segment(segs[-1].start, b, layers)  # same picture continues
        else:
            segs.append(Segment(a, b, layers))
    return segs


def _identity(tl: Timeline, c: Clip) -> list:
    a = tl.assets[c.asset]  # type: ignore[index]
    p = Path(a.path)
    st = p.stat()
    return [a.id, a.path, st.st_size, st.st_mtime_ns, a.kind]


def _layer_spec(tl: Timeline, seg: Segment, c: Clip) -> dict:
    """Everything about one visible clip that decides the pixels of this segment (and nothing else)."""
    a = tl.assets[c.asset]  # type: ignore[index]
    into = seg.start - c.start  # frames of this clip that came before the segment
    offset = c.in_point + into
    if c.kind == "video" and c.loop and a.duration:
        offset %= a.duration
    kb = next((e.value for e in c.effects if e.type == "kenburns"), None)
    return {
        "asset": _identity(tl, c), "kind": c.kind, "offset": offset if c.kind == "video" else 0, "loop": c.loop,
        "opacity": c.transform.opacity, "place": [c.transform.x, c.transform.y, c.transform.scale],
        "kb": None if kb is None else [kb, into, c.duration],  # the zoom runs over the whole clip, not the segment
    }


def segment_key(tl: Timeline, seg: Segment, w: int, h: int, profile: assemble.RenderProfile) -> str:
    spec = {"v": RENDER_VERSION, "frames": seg.frames, "size": [w, h], "fps": tl.fps,
            "profile": [profile.name, profile.encoder, profile.seg_preset, profile.seg_crf, profile.bitrate],
            "layers": [_layer_spec(tl, seg, c) for c in seg.layers]}
    return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:20]


# ------------------------------------------------------------------ one segment

def _even(v: float) -> int:
    return max(2, 2 * round(v / 2))


def _placed(c: Clip) -> bool:
    """True when the layer does not simply cover the whole frame (so something must lie underneath it)."""
    t = c.transform
    return t.opacity < 1 or t.scale < 1 or bool(t.x or t.y)


def _overlay(c: Clip, w: int, h: int) -> str:
    t = c.transform
    return f"overlay=x='(main_w-overlay_w)/2+{t.x * w:.2f}':y='(main_h-overlay_h)/2+{t.y * h:.2f}':format=auto:shortest=0"


def _layer_chain(tl: Timeline, seg: Segment, c: Clip, idx: int, w: int, h: int) -> str:
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    spec = _layer_spec(tl, seg, c)
    if c.kind == "video":
        chain = f"[{idx}:v]{cover},fps={tl.fps}"
    elif spec["kb"] is None:
        chain = f"[{idx}:v]{cover},fps={tl.fps}"
    else:
        pct, into, total = spec["kb"]
        # the zoom is a function of the clip-relative frame: `on` counts from the start of the segment
        chain = (f"[{idx}:v]scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
                 f"zoompan=z='1+{pct / 100:.6f}*(on+{into})/{total}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={tl.fps},setsar=1")
    if c.transform.scale != 1:  # picture-in-picture / zoom: the covered picture is resized, `_overlay` positions it
        chain += f",scale={_even(w * c.transform.scale)}:{_even(h * c.transform.scale)}"
    if c.transform.opacity < 1:
        chain += f",format=yuva420p,colorchannelmixer=aa={c.transform.opacity:.4f}"
    return chain + f"[l{idx}]"


def _segment_args(tl: Timeline, seg: Segment, w: int, h: int, profile: assemble.RenderProfile, dst: Path) -> list[str]:
    enc = assemble._enc(profile)  # noqa: SLF001
    if not seg.layers:
        return ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={tl.fps}", "-frames:v", str(seg.frames), *enc, str(dst)]
    args: list[str] = []
    chains: list[str] = []
    for i, c in enumerate(seg.layers):
        a = tl.assets[c.asset]  # type: ignore[index]
        if c.kind == "video":
            if c.loop:
                args += ["-stream_loop", "-1"]
            off = _layer_spec(tl, seg, c)["offset"]
            args += ["-ss", f"{off / tl.fps:.6f}", "-i", a.path]
        else:
            args += ["-loop", "1", "-framerate", str(tl.fps), "-i", a.path]
        chains.append(_layer_chain(tl, seg, c, i, w, h))
    base = "[l0]"
    if _placed(seg.layers[0]) or seg.layers[0].transform.scale > 1:  # a see-through/smaller/moved bottom layer needs a black frame under it
        args += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={tl.fps}"]
        chains.append(f"[{len(seg.layers)}:v]null[black]")
        chains.append(f"[black][l0]{_overlay(seg.layers[0], w, h)}[o0]")
        base = "[o0]"
    for i in range(1, len(seg.layers)):
        chains.append(f"{base}[l{i}]{_overlay(seg.layers[i], w, h)}[o{i}]")
        base = f"[o{i}]"
    return [*args, "-filter_complex", ";".join(chains), "-map", base, "-frames:v", str(seg.frames), *enc, str(dst)]


@lru_cache(maxsize=512)
def _image_decodes(path: str, size: int, mtime_ns: int) -> bool:  # size/mtime only key the cache
    """`-loop 1` on an undecodable picture makes ffmpeg hang without any output, so look at it once, without looping."""
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1", "-f", "null", "-"], capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return p.returncode == 0


def _usable(tl: Timeline, seg: Segment) -> bool:
    for c in seg.layers:
        if c.kind == "image":
            st = Path(tl.assets[c.asset].path).stat()  # type: ignore[index]
            if not _image_decodes(tl.assets[c.asset].path, st.st_size, st.st_mtime_ns):  # type: ignore[index]
                return False
    return True


def render_segment(tl: Timeline, seg: Segment, w: int, h: int, profile: assemble.RenderProfile, out_dir: Path) -> Path:
    key = segment_key(tl, seg, w, h, profile)
    dst = out_dir / f"seg_{key}.mp4"
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    part = out_dir / f"seg_{key}.part.mp4"  # never reuse a half-written file
    timeout = 120 + 30 * seg.frames / tl.fps
    try:
        if not _usable(tl, seg):
            raise ffmpeg.FfmpegError("a picture in this segment cannot be decoded")
        ffmpeg.run(_segment_args(tl, seg, w, h, profile, part), timeout=timeout)
    except ffmpeg.FfmpegError as e:
        if not seg.layers:
            raise
        log.warning("segment %d-%d could not be rendered (%s): black placeholder", seg.start, seg.end, e)
        ffmpeg.run(_segment_args(tl, Segment(seg.start, seg.end, ()), w, h, profile, part), timeout=timeout)
    os.replace(part, dst)
    return dst


def render_video(tl: Timeline, w: int, h: int, profile: assemble.RenderProfile, out_dir: Path, progress: Progress | None = None,
                 p0: float = 0.78, p1: float = 0.93) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.part.mp4"):
        stale.unlink(missing_ok=True)
    segs = plan_segments(tl)
    paths: list[Path] = []
    for i, seg in enumerate(segs):
        if progress:
            progress("render", p0 + (p1 - p0) * i / max(1, len(segs)), f"Rendering {i + 1}/{len(segs)}")
        paths.append(render_segment(tl, seg, w, h, profile, out_dir))
    keep = set(paths)
    for old in out_dir.glob("seg_*.mp4"):  # segments nothing refers to any more
        if old not in keep:
            old.unlink(missing_ok=True)
    return paths


# ------------------------------------------------------------------ audio

def _audio_clips(tl: Timeline) -> list[Clip]:
    hidden = {t.id for t in tl.tracks if t.muted}
    return [c for c in tl.clips if c.kind == "audio" and c.track not in hidden]


DUCK = "sidechaincompress=threshold=0.02:ratio=8:attack=40:release=600:makeup=1"  # music drops ~12 dB while the narration speaks


def mix_audio(tl: Timeline, work: Path) -> Path:
    """One lossless file with every audio clip placed, trimmed, faded and mixed. Cached by content."""
    out_dir = work / "audio_mix"
    out_dir.mkdir(exist_ok=True)
    total_s = tl.duration / tl.fps
    clips = sorted(_audio_clips(tl), key=lambda c: (c.start, c.id))
    spec = {"v": RENDER_VERSION, "fps": tl.fps, "total": tl.duration,
            "duck": sorted(t.id for t in tl.tracks if t.duck and not t.muted),
            "clips": [[_identity(tl, c), c.start, c.duration, c.in_point, c.volume, c.fade_in, c.fade_out, c.track] for c in clips]}
    dst = out_dir / f"mix_{hashlib.sha1(json.dumps(spec).encode()).hexdigest()[:20]}.flac"
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    part = dst.with_suffix(".part.flac")
    if not clips:  # a silent track: players expect audio
        ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total_s:.4f}", "-c:a", "flac", str(part)], timeout=120)
    else:
        args, chains = [], []
        for i, c in enumerate(clips):
            a = tl.assets[c.asset]  # type: ignore[index]
            args += ["-ss", f"{c.in_point / tl.fps:.6f}", "-t", f"{c.duration / tl.fps:.6f}", "-i", a.path]
            dur = c.duration / tl.fps
            chain = f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
            if c.volume != 1:
                chain += f",volume={c.volume:.4f}"
            if c.fade_in:
                chain += f",afade=t=in:st=0:d={c.fade_in / tl.fps:.4f}"
            if c.fade_out:
                chain += f",afade=t=out:st={max(0.0, dur - c.fade_out / tl.fps):.4f}:d={c.fade_out / tl.fps:.4f}"
            delay = round(c.start / tl.fps * 1000)
            chains.append(chain + (f",adelay=delays={delay}:all=1" if delay else "") + f"[a{i}]")
        ducked_tracks = {t.id for t in tl.tracks if t.duck}
        quiet = [i for i, c in enumerate(clips) if c.track in ducked_tracks]
        loud = [i for i in range(len(clips)) if i not in quiet]
        tail = f",apad=whole_dur={total_s:.4f},atrim=end={total_s:.4f}"

        def group(idx: list[int], name: str) -> None:
            mix = "".join(f"[a{i}]" for i in idx)
            chains.append((f"{mix}amix=inputs={len(idx)}:duration=longest:normalize=0" if len(idx) > 1 else f"{mix}anull") + tail + f"[{name}]")

        if quiet and loud:
            group(loud, "loud")
            group(quiet, "quiet")
            chains.append("[loud]asplit=2[loud1][loud2]")
            chains.append(f"[quiet][loud1]{DUCK}[ducked]")
            chains.append("[loud2][ducked]amix=inputs=2:duration=longest:normalize=0[out]")
        else:
            group(list(range(len(clips))), "out")
        ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-c:a", "flac", str(part)], timeout=120 + 4 * total_s)
    os.replace(part, dst)
    for old in out_dir.glob("mix*.flac"):  # keep only the current mix
        if old != dst and not old.name.startswith(f"mixn_{dst.stem[4:]}"):
            old.unlink(missing_ok=True)
    return dst


# ------------------------------------------------------------------ captions

def captions_ass(tl: Timeline, w: int, h: int) -> str:
    hidden = {t.id for t in tl.tracks if t.muted}
    caps = sorted((c for c in tl.clips if c.kind == "caption" and c.track not in hidden), key=lambda c: c.start)
    cues = [Cue(start=c.start / tl.fps, end=(c.start + c.duration) / tl.fps, text=c.text or "") for c in caps]
    style = CaptionStyle.model_validate(tl.caption_style) if tl.caption_style else None
    return cues_to_ass(cues, str(tl.meta.get("language", "en")), w, h, style)


# ------------------------------------------------------------------ everything

def render_timeline(
    tl: Timeline, work: Path, settings: Settings, *, quality: str, out: Path, aspect: str | None = None,
    captions: bool = True, normalize: bool = True, lufs: float = -14.0, profile: assemble.RenderProfile | None = None,
    progress: Progress | None = None,
) -> Path:
    problems = unsupported_features(tl)
    if problems:
        raise RenderUnsupported(problems)
    if tl.duration < 1:
        raise ValueError("The timeline is empty.")
    preview = quality == "preview"
    profile = profile or (assemble.PREVIEW if preview else assemble.FINAL)
    if profile.encoder != "libx264" and not ffmpeg.has_encoder(profile.encoder):
        log.warning("encoder %s is not available here: using the software encoder", profile.encoder)
        profile = assemble.PREVIEW if preview else assemble.FINAL
    w, h = render_size(aspect or tl.aspect, quality)

    segments = render_video(tl, w, h, profile, work / ("tl_segments_preview" if preview else "tl_segments"), progress)

    audio = mix_audio(tl, work)
    if normalize:
        norm = audio.with_name(f"mixn_{audio.stem[4:]}_{lufs:g}.flac")
        audio = norm if norm.is_file() else loudness.normalize(audio, norm, lufs)

    ass = None
    if captions:
        ass = work / ("captions_preview.ass" if preview else "captions.ass")
        ass.write_text(captions_ass(tl, w, h), "utf-8")
    if progress:
        progress("render", 0.94, "Encoding")
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble.concat_and_finish(segments, audio, ass, out, work, Path(settings.fonts_dir), tl.duration / tl.fps, profile,
                               base_video_name(quality))
    return out
