"""Caption look: loaded from an optional TOML file, then overridden by CLI flags."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
ALIGNMENT = {"bottom": 2, "center": 5, "top": 8}  # ASS numpad alignment, horizontally centred


def hex_to_ass(color: str) -> str:
    """'#RRGGBB' -> ASS '&H00BBGGRR'."""
    m = _HEX.match(color.strip())
    if not m:
        raise ValueError(f"colour must look like #FFFFFF, got {color!r}")
    rr, gg, bb = m.group(1)[0:2], m.group(1)[2:4], m.group(1)[4:6]
    return f"&H00{bb}{gg}{rr}".upper()


class CaptionStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a style file must fail loudly

    font: str | None = None  # None -> Noto Nastaliq Urdu for Urdu, Arial otherwise
    size_pct: float | None = Field(None, gt=1, le=30, description="font size, % of frame height")
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = Field(3.0, ge=0, le=20, description="px at 1080p")
    position: Literal["bottom", "center", "top"] = "bottom"
    margin_pct: float = Field(7.0, ge=0, le=40, description="distance from the edge, % of height")
    bold: bool = False
    words_per_line: int = Field(7, ge=1, le=30)
    max_chars: int = Field(40, ge=10, le=120)

    @field_validator("font")
    @classmethod
    def _check_font(cls, v: str | None) -> str | None:
        # the name is written into an ASS style line: commas/newlines would inject other fields
        if v is not None and not re.fullmatch(r"[\w .\-]{1,60}", v):
            raise ValueError("font names may only contain letters, digits, spaces, '.' and '-'")
        return v

    @field_validator("color", "outline_color")
    @classmethod
    def _check_hex(cls, v: str) -> str:
        hex_to_ass(v)
        return v


def load_style(path: Path | None = None, **overrides) -> CaptionStyle:
    """TOML file (optional) < explicit overrides (None values are ignored)."""
    data: dict = {}
    if path:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        data = raw.get("captions", raw)  # accept [captions] table or top-level keys
    data.update({k: v for k, v in overrides.items() if v is not None})
    return CaptionStyle.model_validate(data)
