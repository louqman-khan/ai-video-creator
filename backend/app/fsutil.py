"""File helpers that behave the same on macOS, Linux and Windows."""

from __future__ import annotations

import os
import time
from pathlib import Path


def replace(src: Path | str, dst: Path | str, tries: int = 8, delay: float = 0.05) -> None:
    """`os.replace` that survives a short-lived reader. On Windows a file that is open anywhere (a browser streaming the preview, another thread
    reading the timeline) cannot be replaced and `os.replace` raises PermissionError; a moment later it works, so try again before giving up."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay * (attempt + 1))
