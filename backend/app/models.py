from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MediaKind = Literal["video", "image"]


class Word(BaseModel):
    text: str
    start: float
    end: float


class Segment(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str
    duration: float
    segments: list[Segment]

    @property
    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]


class Scene(BaseModel):
    id: int
    start: float
    end: float
    text: str
    query_en: str = ""
    keywords: list[str] = Field(default_factory=list)
    preferred_kind: MediaKind | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


class MediaAsset(BaseModel):
    """A candidate visual. `license` is mandatory: no asset without license info."""

    id: str  # "<source>:<source id>"
    source: str
    kind: MediaKind
    url: str  # direct download URL
    license: str
    page_url: str = ""
    thumb_url: str = ""
    width: int = 0
    height: int = 0
    duration: float | None = None  # seconds, videos only
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    license_url: str = ""
    author: str = ""
    author_url: str = ""
    attribution: str = ""  # ready-to-print credit line
    attribution_required: bool = False


class ScenePick(BaseModel):
    scene_id: int
    asset: MediaAsset | None = None  # None -> black fallback
    local_path: str | None = None
