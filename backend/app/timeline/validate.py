"""Cross-checks that a single pydantic field cannot express. The server never trusts a timeline
sent by the browser: every write goes through `check`."""

from __future__ import annotations

from app.timeline.models import MAX_FRAMES, TRACK_ACCEPTS, Timeline


def check(tl: Timeline) -> list[str]:
    """Return every problem found (empty list = valid)."""
    problems: list[str] = []
    tracks = {}
    for t in tl.tracks:
        if t.id in tracks:
            problems.append(f"duplicate track id '{t.id}'")
        tracks[t.id] = t

    seen: set[str] = set()
    per_track: dict[str, list] = {}
    for c in tl.clips:
        where = f"clip '{c.id}'"
        if c.id in seen:
            problems.append(f"duplicate clip id '{c.id}'")
        seen.add(c.id)

        track = tracks.get(c.track)
        if track is None:
            problems.append(f"{where}: unknown track '{c.track}'")
        elif c.kind not in TRACK_ACCEPTS[track.kind]:
            problems.append(f"{where}: a {c.kind} clip cannot sit on the {track.kind} track '{track.id}'")
        else:
            per_track.setdefault(c.track, []).append(c)

        if c.start + c.duration > MAX_FRAMES:
            problems.append(f"{where}: ends beyond the maximum length")
        if c.fade_in + c.fade_out > c.duration:
            problems.append(f"{where}: fades are longer than the clip")
        if c.transition_in and c.transition_in.duration > c.duration:
            problems.append(f"{where}: transition is longer than the clip")

        if c.kind == "caption":
            if c.asset is not None:
                problems.append(f"{where}: captions have no asset")
            if not (c.text and c.text.strip()):
                problems.append(f"{where}: caption text is empty")
            continue

        asset = tl.assets.get(c.asset) if c.asset else None
        if asset is None:
            problems.append(f"{where}: unknown asset '{c.asset}'")
            continue
        if asset.kind != c.kind:
            problems.append(f"{where}: a {c.kind} clip cannot use the {asset.kind} asset '{asset.id}'")
            continue
        if asset.kind == "image":
            if c.in_point:
                problems.append(f"{where}: images have no in-point")
        else:
            length = asset.duration or 0
            if c.in_point >= length:
                problems.append(f"{where}: starts after the end of its media")
            elif not c.loop and c.in_point + c.duration > length:
                problems.append(f"{where}: runs past the end of its media ({c.in_point + c.duration} > {length} frames); trim it or turn on looping")
        if c.kind != "audio" and c.words:
            problems.append(f"{where}: only audio clips carry words")
        for w in c.words:
            if w.end < w.start:
                problems.append(f"{where}: a word ends before it starts")
                break

    for track_id, clips in per_track.items():
        clips.sort(key=lambda c: c.start)
        for a, b in zip(clips, clips[1:]):
            if b.start < a.start + a.duration:
                problems.append(f"clips '{a.id}' and '{b.id}' overlap on track '{track_id}'")
    return problems
