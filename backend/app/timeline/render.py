"""Timeline renderer v1 (task 4.3, decision D2).

The timeline is cut at every frame where the set of visible clips changes. Each segment is rendered on
its own with a small FFmpeg filtergraph and cached under a key made of *only what is visible in it*, so
changing one clip re-renders only the segments it touches. Segments are joined without re-encoding,
audio is a separate mixdown, and captions are burned in the final pass.

Features the renderer cannot do yet are refused loudly (`RenderUnsupported`), never silently ignored.
"""

from __future__ import annotations

from app import fsutil

import hashlib
import math
import json
import logging
import os
import subprocess
from collections.abc import Callable
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.media import derive, ffmpeg, loudness
from app.media.ingest import _HDR_TRANSFERS
from app.pipeline import assemble
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.captions import Cue, cues_to_ass
from app.pipeline.sizes import base_video_name, render_size
from app.timeline.models import Clip, Timeline

log = logging.getLogger("avc.render")
RENDER_VERSION = "r7"
BLUR_ZOOM = 1.15  # the blurred copy behind a "fit" picture is enlarged a little so its blurred edges stay out of the frame
BLUR_SIGMA = 0.03  # blur strength of that copy, in frame widths  # bump when the pictures a segment produces change: invalidates every cached segment
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
            for e in c.effects:
                if e.type == "kenburns" and c.kind != "image":
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


def ghosts(tl: Timeline, clips: list[Clip]) -> list[Clip]:
    """A transition needs the outgoing picture for as long as it lasts. The clip before it ends exactly where the
    incoming one starts, so its last moments are carried on ("ghost") underneath, for the length of the transition:
    still pictures stay, a video goes on playing (a looping one loops, otherwise its last frame is held)."""
    out: list[Clip] = []
    by_end = {(c.track, c.start + c.duration): c for c in clips if not c.meta.get("ghost")}
    for b in clips:
        t = b.transition_in
        a = by_end.get((b.track, b.start))
        if t is None or a is None or a.id == b.id:
            continue
        d = min(t.duration, b.duration)
        asset = tl.assets.get(a.asset or "")
        length = asset.duration if asset is not None else None
        pos = a.in_point + a.duration
        hold = False
        if a.kind == "video" and length:
            if a.loop:
                pos %= length
            elif pos >= length:
                pos, hold = length - 1, True
        out.append(a.model_copy(update={"id": f"{a.id}~out", "start": b.start, "duration": d, "in_point": pos if a.kind == "video" else 0,
                                        "fade_in": 0, "fade_out": 0, "transition_in": None,
                                        "meta": {"ghost": True, "hold": hold, "trans": [t.type, t.duration]}}))
    return out


def _track_order(tl: Timeline) -> dict[str, int]:
    return {t.id: i for i, t in enumerate(tl.tracks)}


def plan_segments(tl: Timeline) -> list[Segment]:
    """Cut the picture timeline wherever the set of visible clips changes. Gaps become empty segments (black)."""
    order = _track_order(tl)
    hidden = {t.id for t in tl.tracks if t.muted}  # a muted video track is hidden
    clips = [c for c in tl.clips if c.kind in ("video", "image") and c.track not in hidden]
    clips += ghosts(tl, clips)
    total = tl.duration
    bounds = sorted({0, total, *(c.start for c in clips), *(c.start + c.duration for c in clips)})
    segs: list[Segment] = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        layers = tuple(sorted((c for c in clips if c.start <= a < c.start + c.duration),
                              key=lambda c: (order[c.track], 0 if c.meta.get("ghost") else 1)))  # a ghost lies under the clip it hands over to
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


@dataclass(frozen=True)
class Timing:
    """The parts of a picture's look that change while the clip plays, as ffmpeg expressions of `{F}` = frames
    since the clip started (`clip(x,0,1)` clamps). `alpha` multiplies the opacity, `dx` is a horizontal shift in
    frame widths, `zoom` a size factor."""

    alpha: str | None = None
    dx: str | None = None
    zoom: str | None = None


def _timing(c: Clip) -> Timing:
    """Fades, the transition into this clip, and (for a ghost) the transition it hands over to. The same maths is in
    frontend/src/preview/plan.ts (`appearance`): change both together."""
    parts: list[str] = []
    dx = zoom = None
    t = c.transition_in
    if t is not None:
        p = f"clip({{F}}/{t.duration},0,1)"
        if t.type == "crossfade":
            parts.append(p)
        elif t.type == "dip":
            parts.append(f"clip(2*{p}-1,0,1)")
        elif t.type == "slide":
            dx = f"(1-{p})"
        elif t.type == "zoom":
            parts.append(p)
            zoom = f"(1+0.5*(1-{p}))"
    ghost = c.meta.get("trans")
    if ghost and ghost[0] == "dip":
        parts.append(f"clip(1-2*clip({{F}}/{ghost[1]},0,1),0,1)")
    if c.fade_in:
        parts.append(f"clip({{F}}/{c.fade_in},0,1)")
    if c.fade_out:
        parts.append(f"clip(({c.duration}-{{F}})/{c.fade_out},0,1)")
    return Timing("*".join(parts) or None, dx, zoom)


def _key_args(c: Clip) -> list[str]:
    """Chroma key as ffmpeg filters. The live preview does the same maths (preview/chromakey.ts): the colour distance is measured on the
    chroma (BT.709, limited range) and scaled like ffmpeg's `chromakey`; despill limits the key's own channel by the mean of the other two."""
    k = c.key
    if k is None:
        return []
    out = ["format=yuva420p", f"chromakey=color=0x{k.color[1:].lower()}:similarity={k.similarity:.4f}:blend={k.blend:.4f}"]
    r, g, b = (int(k.color[i:i + 2], 16) for i in (1, 3, 5))
    if k.despill and max(r, g, b) in (g, b) and (g >= r or b >= r):
        out.append(f"despill=type={'green' if g >= b else 'blue'}")
    return out


def _fx_args(c: Clip, w: int) -> list[str]:
    """Colour and blur effects as ffmpeg filters, written to give the same result as the CSS filters the live preview
    uses: brightness b (-100..100) multiplies every channel by 1 + 0.8 b/100, contrast c scales around mid grey by
    1 + c/100, saturation s by 1 + s/100, blur v is a Gaussian of 0.00015 * v * frame-width pixels."""
    v = {e.type: e.value for e in c.effects}
    out: list[str] = []
    rgb = []
    if v.get("brightness"):
        m = max(0.0, 1 + 0.8 * v["brightness"] / 100)
        rgb.append("lutrgb=r='clip(val*{m},0,255)':g='clip(val*{m},0,255)':b='clip(val*{m},0,255)'".format(m=f"{m:.4f}"))
    if v.get("contrast"):
        k = max(0.0, 1 + v["contrast"] / 100)
        rgb.append("lutrgb=r='clip((val-128)*{k}+128,0,255)':g='clip((val-128)*{k}+128,0,255)':b='clip((val-128)*{k}+128,0,255)'".format(k=f"{k:.4f}"))
    if rgb:
        out += (["format=rgba", *rgb, "format=yuva420p"] if c.key else ["format=rgb24", *rgb, "format=yuv420p"])  # keep the key's transparency
    if v.get("saturation"):
        out.append(f"eq=saturation={max(0.0, 1 + v['saturation'] / 100):.4f}")
    if v.get("blur", 0) > 0:
        out.append(f"gblur=sigma={v['blur'] * 0.00015 * w:.3f}")
    return out


def _layer_spec(tl: Timeline, seg: Segment, c: Clip) -> dict:
    """Everything about one visible clip that decides the pixels of this segment (and nothing else)."""
    a = tl.assets[c.asset]  # type: ignore[index]
    into = seg.start - c.start  # frames of this clip that came before the segment
    offset = c.in_point + into
    if c.kind == "video" and c.loop and a.duration:
        offset %= a.duration
    kb = next((e.value for e in c.effects if e.type == "kenburns"), None)
    spec = {
        "key": c.key.model_dump() if c.key else None,
        "asset": _identity(tl, c), "kind": c.kind, "offset": offset if c.kind == "video" else 0, "loop": c.loop,
        "opacity": c.transform.opacity, "place": [c.transform.x, c.transform.y, c.transform.scale],
        "shape": [c.transform.rotation, list(c.transform.crop), c.fit, list(c.focus) if c.focus else None],
        "kb": None if kb is None else [kb, into, c.duration],  # the zoom runs over the whole clip, not the segment
    }
    timing = _timing(c)
    if timing.alpha or timing.dx or timing.zoom or c.meta.get("hold"):  # time-varying look: where in the clip this segment starts matters
        spec["timing"] = [timing.alpha, timing.dx, timing.zoom, into, c.meta.get("hold", False)]
    fx = _fx_args(c, 1920)
    if fx:
        spec["fx"] = fx
    return spec


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
    timing = _timing(c)
    return (c.key is not None or t.opacity < 1 or t.scale < 1 or bool(t.x or t.y or t.rotation or any(t.crop)) or c.fit == "fit"
            or bool(timing.alpha or timing.dx or timing.zoom))


@dataclass(frozen=True)
class Geometry:
    """Sizes of a layer after each step (pixels): the cropped part, the resized part, and the part after rotation."""

    cx: int
    cy: int
    cw: int
    ch: int  # the crop rectangle inside the frame-sized picture
    sw: int
    sh: int  # after the picture-in-picture size
    ow: int
    oh: int  # after rotation (the bounding box)
    shift_x: float
    shift_y: float  # how far the cropped piece's centre is from the picture's centre, in pixels


def _geometry(c: Clip, w: int, h: int) -> Geometry:
    t = c.transform
    left, top, right, bottom = t.crop
    cx, cy = int(w * left), int(h * top)
    cw, ch = max(2, int(w * (1 - left - right))), max(2, int(h * (1 - top - bottom)))
    sw, sh = (_even(cw * t.scale), _even(ch * t.scale)) if (t.scale != 1 or any(t.crop)) else (w, h)
    if t.rotation:
        a = math.radians(t.rotation)
        ow, oh = _even(abs(sw * math.cos(a)) + abs(sh * math.sin(a))), _even(abs(sw * math.sin(a)) + abs(sh * math.cos(a)))
    else:
        ow, oh = sw, sh
    return Geometry(cx, cy, cw, ch, sw, sh, ow, oh, (left - right) / 2 * w * t.scale, (top - bottom) / 2 * h * t.scale)


def _frames_expr(expr: str, var: str, into: int) -> str:
    return expr.replace("{F}", f"({var}+{into})")


def _overlay(seg: Segment, c: Clip, w: int, h: int) -> str:
    t = c.transform
    into = seg.start - c.start
    dx = _timing(c).dx
    shift = f"+main_w*{_frames_expr(dx, 'n-1', into)}" if dx else ""  # in `overlay` the first frame has n=1 (measured)
    g = _geometry(c, w, h)
    return (f"overlay=x='(main_w-overlay_w)/2+{t.x * w + g.shift_x:.2f}{shift}':y='(main_h-overlay_h)/2+{t.y * h + g.shift_y:.2f}':"
            f"format=auto:shortest=0")


@lru_cache(maxsize=256)
def _is_hdr(path: str, size: int, mtime_ns: int) -> bool:  # size/mtime only key the cache
    """HDR (PQ or HLG) pictures must be tone-mapped to SDR like the proxies are, or they look flat and grey."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer", "-of", "csv=p=0", path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout.strip() in _HDR_TRANSFERS


def _tonemap(tl: Timeline, c: Clip) -> str:
    a = tl.assets.get(c.asset or "")
    if c.kind != "video" or a is None:
        return ""
    st = Path(a.path).stat()
    return derive.TONEMAP + ",format=yuv420p," if _is_hdr(a.path, st.st_size, st.st_mtime_ns) else ""


def _focus_window(c: Clip, w: int, h: int) -> str:
    """Where the frame-sized window is cut from a picture that was scaled to cover the frame: centred on the clip's focus point (kept inside the picture)."""
    if not c.focus:
        return ""
    fx, fy = c.focus
    return f":x='min(max(iw*{fx:.4f}-{w}/2,0),iw-{w})':y='min(max(ih*{fy:.4f}-{h}/2,0),ih-{h})'"


def _layer_chain(tl: Timeline, seg: Segment, c: Clip, idx: int, w: int, h: int) -> list[str]:
    """Filter-graph pieces for one layer, ending in the label `[l<idx>]`. Order: show the picture in the frame
    (fill / fit / blurred background / Ken Burns), effects, crop, resize, rotate, opacity and fades, transition zoom."""
    spec = _layer_spec(tl, seg, c)
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}{_focus_window(c, w, h)},setsar=1"
    into = seg.start - c.start
    hold = ",tpad=stop_mode=clone:stop_duration=600" if c.meta.get("hold") else ""  # a ghost whose video has run out keeps its last frame
    pieces: list[str] = []
    tm = _tonemap(tl, c)
    if c.kind == "image" and spec["kb"] is not None:
        pct, into_kb, total = spec["kb"]
        # the zoom is a function of the clip-relative frame: `on` counts from the start of the segment
        chain = (f"[{idx}:v]scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
                 f"zoompan=z='1+{pct / 100:.6f}*(on+{into_kb})/{total}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={tl.fps},setsar=1")
    elif c.fit == "fit":
        chain = (f"[{idx}:v]{tm}scale={w}:{h}:force_original_aspect_ratio=decrease,fps={tl.fps}{hold},format=yuva420p,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={'0x' + c.key.color[1:] + '@1' if c.key else 'black@0'},setsar=1")  # with a green screen the bars are keyed away too (chromakey would otherwise make them opaque)
    elif c.fit == "blur":
        pieces += [f"[{idx}:v]{tm}fps={tl.fps}{hold},split[a{idx}][b{idx}]",
                   f"[a{idx}]scale={int(w * BLUR_ZOOM)}:{int(h * BLUR_ZOOM)}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma={w * BLUR_SIGMA:.2f}[bg{idx}]",
                   f"[b{idx}]scale={w}:{h}:force_original_aspect_ratio=decrease[fg{idx}]"]
        chain = f"[bg{idx}][fg{idx}]overlay=x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2,setsar=1"
    else:
        chain = f"[{idx}:v]{tm}{cover},fps={tl.fps}{hold}"
    for f in [*_key_args(c), *_fx_args(c, w)]:
        chain += "," + f
    g = _geometry(c, w, h)
    t = c.transform
    if any(t.crop):
        chain += f",crop={g.cw}:{g.ch}:{g.cx}:{g.cy}"
    if (g.sw, g.sh) != (g.cw, g.ch) or any(t.crop):
        chain += f",scale={g.sw}:{g.sh}"
    if t.rotation:
        chain += f",format=yuva420p,rotate=a={math.radians(t.rotation):.6f}:ow={g.ow}:oh={g.oh}:c=black@0,setsar=1"
    timing = _timing(c)
    zoom = (f",scale=w='{_even(g.ow)}*{_frames_expr(timing.zoom, 'n', into)}':h='{_even(g.oh)}*{_frames_expr(timing.zoom, 'n', into)}':eval=frame"
            if timing.zoom else "")
    if timing.alpha:
        # a moving opacity: a tiny animated grey picture (its brightness is the opacity of that frame), enlarged and used as the alpha channel
        mask = f"color=c=white:s=2x2:r={tl.fps},format=gray,geq=lum='255*{t.opacity:.4f}*{_frames_expr(timing.alpha, 'N', into)}',scale={g.ow}:{g.oh}"
        if c.key:  # the key made some pixels transparent already: multiply that with the moving opacity instead of replacing it
            pieces += [chain + f",format=yuva420p,split[r{idx}][k{idx}]", f"[k{idx}]alphaextract,format=gray[ka{idx}]", mask + f",format=gray[m{idx}]",
                       f"[ka{idx}][m{idx}]blend=all_mode=multiply[am{idx}]", f"[r{idx}][am{idx}]alphamerge{zoom}[l{idx}]"]
        else:
            pieces += [chain + f",format=yuva420p[r{idx}]", mask + f"[m{idx}]", f"[r{idx}][m{idx}]alphamerge{zoom}[l{idx}]"]
    else:
        if t.opacity < 1:
            chain += f",format=yuva420p,colorchannelmixer=aa={t.opacity:.4f}"
        pieces.append(chain + zoom + f"[l{idx}]")
    return pieces


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
        chains += _layer_chain(tl, seg, c, i, w, h)
    base = "[l0]"
    if _placed(seg.layers[0]) or seg.layers[0].transform.scale > 1 or _timing(seg.layers[0]).alpha:  # a see-through/smaller/moved bottom layer needs a black frame under it
        args += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={tl.fps}"]
        chains.append(f"[{len(seg.layers)}:v]null[black]")
        chains.append(f"[black][l0]{_overlay(seg, seg.layers[0], w, h)}[o0]")
        base = "[o0]"
    for i in range(1, len(seg.layers)):
        chains.append(f"{base}[l{i}]{_overlay(seg, seg.layers[i], w, h)}[o{i}]")
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
    fsutil.replace(part, dst)
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
    fsutil.replace(part, dst)
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
    progress: Progress | None = None, preset: str | None = None,
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
    w, h = render_size(aspect or tl.aspect, quality, preset)

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
