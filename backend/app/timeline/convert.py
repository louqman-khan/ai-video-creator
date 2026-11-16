"""Project files <-> timeline document.

Today's projects store their layout as scenes.json + assets.json (+ captions). `build_timeline` turns
those into a timeline once; `scenes_from_timeline` is the reverse, used to prove the conversion loses
nothing and, later, to keep the Step 3 screens working as views over the timeline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import Settings
from app.media import ffmpeg
from app.models import MediaAsset, Scene, ScenePick, Transcript
from app.pipeline.caption_style import CaptionStyle
from app.pipeline.captions import Cue, build_cues
from app.timeline.models import Asset, Clip, Effect, Timeline, Track, Word

_TRANSCRIPTS = ("transcript.final.json", "transcript.cut.json", "transcript.aligned.json", "transcript.json")
_EMPTY_KEY = "empty_scenes"  # scenes without media have no clip: kept here so nothing is lost
BUILDER_VERSION = 2  # bump when build_timeline changes what it produces: unedited timelines are then rebuilt
KENBURNS_PERCENT = 10.0  # the slow zoom stills always had


class ProjectNotReady(RuntimeError):
    pass


def frames(seconds: float, fps: int) -> int:
    return round(seconds * fps)


def _read(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def load_transcript(d: Path) -> Transcript | None:
    for name in _TRANSCRIPTS:
        if (d / name).is_file():
            return Transcript.model_validate_json((d / name).read_text("utf-8"))
    return None


def narration_file(d: Path, audio_file: str) -> Path:
    """The audio the video was built on (before the final loudness step): cut > cleaned > original."""
    for name in ("audio_cut.flac", "audio_clean.flac"):
        if (d / name).is_file():
            return d / name
    return d / audio_file


def asset_from_media(m: MediaAsset, path: str, fps: int, duration_frames: int | None) -> Asset:
    return Asset(
        id=m.id, kind=m.kind, path=path, url=m.url, duration=duration_frames, width=m.width, height=m.height,
        source=m.source, license=m.license, license_url=m.license_url, author=m.author, author_url=m.author_url,
        page_url=m.page_url, thumb_url=m.thumb_url, title=m.title, attribution=m.attribution,
        attribution_required=m.attribution_required,
    )


def build_timeline(d: Path, info, settings: Settings) -> Timeline:
    """Create the timeline of a finished project. Raises ProjectNotReady if its files are missing."""
    scenes_raw, picks_raw = _read(d / "scenes.json"), _read(d / "assets.json")
    transcript = load_transcript(d)
    if scenes_raw is None or picks_raw is None or transcript is None:
        raise ProjectNotReady("The project is not ready yet")
    fps = settings.fps
    scenes = [Scene.model_validate(s) for s in scenes_raw]
    picks = {p["scene_id"]: ScenePick.model_validate(p) for p in picks_raw}

    tracks = [
        Track(id="V1", kind="video", name="Visuals"),
        Track(id="A1", kind="audio", name="Narration"),
        Track(id="C1", kind="caption", name="Captions"),
    ]
    assets: dict[str, Asset] = {}
    clips: list[Clip] = []

    # scenes -> video/image clips on V1. Frame positions use cumulative rounding, like the renderer,
    # so the clips tile exactly and the total never drifts.
    marks = [frames(s.start, fps) for s in scenes] + [frames(scenes[-1].end, fps)]
    empty: list[dict] = []
    for i, scene in enumerate(scenes):
        start, dur = marks[i], max(1, marks[i + 1] - marks[i])
        meta = {"scene_id": scene.id, "text": scene.text, "query_en": scene.query_en,
                "keywords": scene.keywords, "preferred_kind": scene.preferred_kind}
        pick = picks.get(scene.id)
        if not (pick and pick.asset and pick.local_path):
            empty.append({**meta, "start": start, "duration": dur})
            continue
        m = pick.asset
        if m.id not in assets:
            length = None
            if m.kind == "video":
                try:
                    length = max(1, frames(ffmpeg.probe_duration(Path(pick.local_path)), fps))
                except ffmpeg.FfmpegError:
                    length = max(1, frames(m.duration or scene.duration, fps))
            assets[m.id] = asset_from_media(m, pick.local_path, fps, length)
        a = assets[m.id]
        clips.append(Clip(id=f"scene-{scene.id}", track="V1", kind=m.kind, asset=m.id, start=start, duration=dur,
                          loop=bool(m.kind == "video" and a.duration and dur > a.duration), meta=meta,
                          effects=[Effect(type="kenburns", value=KENBURNS_PERCENT)] if m.kind == "image" else []))

    # narration -> one audio clip on A1 carrying the word timestamps (source frames == timeline frames here)
    nar = narration_file(d, info.audio_file)
    nar_len = max(1, frames(ffmpeg.probe_duration(nar), fps))
    assets["narration"] = Asset(id="narration", kind="audio", path=str(nar), duration=nar_len, source="narration",
                                license="User-provided", attribution="Narration", title="Narration")
    words = [Word(text=w.text, start=frames(w.start, fps), end=max(frames(w.start, fps), frames(w.end, fps)))
             for w in transcript.words if w.text.strip()]
    clips.append(Clip(id="narration", track="A1", kind="audio", asset="narration", start=0, duration=nar_len, words=words))

    # captions -> clips on C1 (edited cues if the user edited them, otherwise derived exactly as the renderer does)
    style_raw = info.options.get("style")
    style = CaptionStyle.model_validate(style_raw) if style_raw else CaptionStyle()
    edited = d / "captions.json"
    cues = [Cue.model_validate(c) for c in _read(edited)] if edited.is_file() else build_cues(transcript, style)
    last_end = 0
    for i, cue in enumerate(cues):
        if not cue.text.strip():
            continue
        start = max(frames(cue.start, fps), last_end)  # never overlap the previous cue after rounding
        end = max(frames(cue.end, fps), start + 1)
        clips.append(Clip(id=f"cap-{i}", track="C1", kind="caption", start=start, duration=end - start, text=cue.text))
        last_end = end

    return Timeline(fps=fps, aspect=info.aspect, tracks=tracks, clips=clips, assets=assets,
                    caption_style=style_raw or None,
                    meta={"builder": BUILDER_VERSION, "language": transcript.language, **({_EMPTY_KEY: empty} if empty else {})})


def scenes_from_timeline(tl: Timeline) -> tuple[list[Scene], list[ScenePick]]:
    """The inverse of the scene part of `build_timeline`."""
    items: list[tuple[int, Scene, ScenePick]] = []
    for c in tl.clips:
        if c.track != "V1" or "scene_id" not in c.meta:
            continue
        a = tl.assets[c.asset]  # type: ignore[index]
        scene = Scene(id=c.meta["scene_id"], start=c.start / tl.fps, end=(c.start + c.duration) / tl.fps,
                      text=c.meta.get("text", ""), query_en=c.meta.get("query_en", ""),
                      keywords=c.meta.get("keywords", []), preferred_kind=c.meta.get("preferred_kind"))
        media = MediaAsset(id=a.id, source=a.source, kind=a.kind, url=a.url, license=a.license, license_url=a.license_url,
                           page_url=a.page_url, thumb_url=a.thumb_url, width=a.width, height=a.height,
                           duration=None, title=a.title, author=a.author, author_url=a.author_url,
                           attribution=a.attribution, attribution_required=a.attribution_required)
        items.append((c.start, scene, ScenePick(scene_id=scene.id, asset=media, local_path=a.path)))
    for e in tl.meta.get(_EMPTY_KEY, []):
        scene = Scene(id=e["scene_id"], start=e["start"] / tl.fps, end=(e["start"] + e["duration"]) / tl.fps,
                      text=e.get("text", ""), query_en=e.get("query_en", ""), keywords=e.get("keywords", []),
                      preferred_kind=e.get("preferred_kind"))
        items.append((e["start"], scene, ScenePick(scene_id=scene.id)))
    items.sort(key=lambda t: t[0])
    return [s for _, s, _ in items], [p for _, _, p in items]


# ---- storage ---------------------------------------------------------------------------------

def timeline_path(d: Path) -> Path:
    return d / "timeline.json"


def load(d: Path) -> Timeline | None:
    f = timeline_path(d)
    if not f.is_file():
        return None
    return Timeline.model_validate_json(f.read_text("utf-8"))


def ensure_timeline(d: Path, facts, settings: Settings) -> Timeline:
    """The timeline to render. An edited one is kept as it is; a never-edited one is rebuilt from the
    project's current scenes, media and captions (they may have changed since it was made)."""
    try:
        current = load(d)
    except ValueError:
        current = None
    if current is not None and current.rev > 1:
        return current
    from app.timeline.validate import check  # local import: validate imports models only, keeps this module light

    tl = build_timeline(d, facts, settings)
    problems = check(tl)
    if problems:
        raise ValueError("The timeline could not be built: " + "; ".join(problems[:6]))
    save(d, tl)
    return tl


def has_edits(d: Path) -> bool:
    """True once the timeline was changed by an edit (revision > 1): then it is the only truth."""
    try:
        tl = load(d)
    except ValueError:
        return False
    return tl is not None and tl.rev > 1


def discard_unedited(d: Path) -> None:
    """After the project's scenes/captions were re-rendered the old, never-edited timeline is stale:
    drop it, it is rebuilt on the next request. An edited timeline is never dropped."""
    if not has_edits(d):
        timeline_path(d).unlink(missing_ok=True)


def save(d: Path, tl: Timeline) -> None:
    f = timeline_path(d)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(tl.model_dump_json(indent=1), "utf-8")
    os.replace(tmp, f)  # atomic: a reader never sees half a file
