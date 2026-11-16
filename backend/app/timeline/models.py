"""Timeline document v1 (see docs/STEP4_PLAN.md, decision D1).

All positions and lengths are **integer frames** at `fps`: no float drift, and "no gaps"/"snap" are
exact. The document is the single source of truth for a project's layout; the renderer and the editor
both read it. Fields for features that arrive later (fades, transforms, effects, transitions) exist
already with neutral defaults so adding those features does not need a schema bump.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1
MAX_TRACKS = 16
MAX_CLIPS = 2000
MAX_WORDS_PER_CLIP = 20_000
MAX_EFFECTS = 8
MAX_META_CHARS = 4000
MAX_TEXT = 300
MAX_FRAMES = 30 * 60 * 60 * 3  # 3 hours at 30 fps: a sanity cap, not a promise

_ID = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

TrackKind = Literal["video", "audio", "caption"]
ClipKind = Literal["video", "image", "audio", "caption"]
AssetKind = Literal["video", "image", "audio"]

# which clips may live on which track
TRACK_ACCEPTS: dict[str, set[str]] = {
    "video": {"video", "image"},
    "audio": {"audio"},
    "caption": {"caption"},
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are errors, never silently dropped


def _check_id(v: str) -> str:
    if not _ID.match(v):
        raise ValueError("ids may only contain letters, digits and _ - : . (max 64 characters)")
    return v


def _check_asset_id(v: str) -> str:
    """Asset ids come from the media providers (e.g. a local file name with spaces). They are only
    dictionary keys / references, never file paths, so they just need to be bounded and printable."""
    if not 1 <= len(v) <= 200 or _CONTROL.search(v):
        raise ValueError("asset ids must be 1-200 printable characters")
    return v


def _clean_text(v: str | None, limit: int) -> str | None:
    if v is None:
        return None
    if len(v) > limit:
        raise ValueError(f"text is longer than {limit} characters")
    if _CONTROL.search(v):
        raise ValueError("text contains control characters")
    return v


class Transform(_Strict):
    x: float = Field(0.0, ge=-10, le=10)  # offset as a fraction of the frame width
    y: float = Field(0.0, ge=-10, le=10)
    scale: float = Field(1.0, gt=0, le=20)
    rotation: float = Field(0.0, ge=-360, le=360)
    opacity: float = Field(1.0, ge=0, le=1)
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # left, top, right, bottom as fractions

    @field_validator("crop")
    @classmethod
    def _crop(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        if any(not 0 <= c < 1 for c in v) or v[0] + v[2] >= 1 or v[1] + v[3] >= 1:
            raise ValueError("crop values must be fractions in [0, 1) that leave some picture")
        return v


class Effect(_Strict):
    type: Literal["brightness", "contrast", "saturation", "blur"]
    value: float = Field(0.0, ge=-100, le=100)


class Transition(_Strict):
    type: Literal["crossfade", "dip", "slide", "zoom"]
    duration: int = Field(..., ge=1, le=30 * 10)


class Word(_Strict):
    """A recognised word in *source* frames of its audio asset (so moving/trimming never changes it)."""

    text: str = Field(..., max_length=80)
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)


class Track(_Strict):
    id: str
    kind: TrackKind
    name: str = Field("", max_length=60)
    muted: bool = False
    locked: bool = False

    _id = field_validator("id")(_check_id)


class Clip(_Strict):
    id: str
    track: str
    kind: ClipKind
    asset: str | None = None  # key into Timeline.assets (None for captions)
    start: int = Field(..., ge=0, le=MAX_FRAMES)  # position on the timeline
    duration: int = Field(..., ge=1, le=MAX_FRAMES)
    in_point: int = Field(0, ge=0, le=MAX_FRAMES)  # offset into the asset
    loop: bool = False  # a video shorter than the clip repeats instead of ending
    volume: float = Field(1.0, ge=0, le=4)
    fade_in: int = Field(0, ge=0, le=MAX_FRAMES)
    fade_out: int = Field(0, ge=0, le=MAX_FRAMES)
    transform: Transform = Field(default_factory=Transform)
    effects: list[Effect] = Field(default_factory=list, max_length=MAX_EFFECTS)
    transition_in: Transition | None = None
    text: str | None = None  # caption clips
    words: list[Word] = Field(default_factory=list, max_length=MAX_WORDS_PER_CLIP)  # narration clips
    meta: dict = Field(default_factory=dict)  # small free-form data (e.g. scene text); bounded

    _id = field_validator("id", "track")(_check_id)

    @field_validator("asset")
    @classmethod
    def _asset(cls, v: str | None) -> str | None:
        return None if v is None else _check_asset_id(v)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _clean_text(v, MAX_TEXT)

    @field_validator("meta")
    @classmethod
    def _meta(cls, v: dict) -> dict:
        try:
            if len(json.dumps(v, allow_nan=False)) > MAX_META_CHARS:
                raise ValueError("meta is too large")
        except (TypeError, ValueError) as e:
            raise ValueError(f"meta must be small, plain JSON ({e})") from None
        return v


class Asset(_Strict):
    """A media file the clips refer to. `path` and `url` stay on the server (see AssetOut)."""

    id: str
    kind: AssetKind
    path: str  # file on disk (cache or project folder)
    url: str = ""  # where it was downloaded from (server only)
    duration: int | None = Field(None, ge=1, le=MAX_FRAMES)  # frames; None for images
    width: int = Field(0, ge=0)
    height: int = Field(0, ge=0)
    source: str = ""
    license: str = Field(..., min_length=1)  # no asset without a license, same rule as everywhere else
    license_url: str = ""
    author: str = ""
    author_url: str = ""
    page_url: str = ""
    thumb_url: str = ""
    title: str = ""
    attribution: str = ""
    attribution_required: bool = False

    _id = field_validator("id")(_check_asset_id)


class AssetOut(_Strict):
    """What the browser may see of an asset."""

    id: str
    kind: AssetKind
    duration: int | None
    width: int
    height: int
    source: str
    license: str
    license_url: str
    author: str
    page_url: str
    thumb_url: str
    title: str
    attribution: str
    attribution_required: bool

    @classmethod
    def of(cls, a: Asset) -> "AssetOut":
        return cls(**a.model_dump(include=set(cls.model_fields)))


class Timeline(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    rev: int = Field(1, ge=1)  # bumped on every accepted write (optimistic concurrency)
    fps: int = Field(30, ge=1, le=120)
    aspect: Literal["16:9", "9:16"] = "16:9"
    tracks: list[Track] = Field(default_factory=list, max_length=MAX_TRACKS)
    clips: list[Clip] = Field(default_factory=list, max_length=MAX_CLIPS)
    assets: dict[str, Asset] = Field(default_factory=dict)
    caption_style: dict | None = None
    meta: dict = Field(default_factory=dict)

    @property
    def duration(self) -> int:
        """Length in frames: the end of the last clip on any track."""
        return max((c.start + c.duration for c in self.clips), default=0)
