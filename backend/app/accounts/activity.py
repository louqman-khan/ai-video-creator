"""What an account did, in plain words, recorded for the operator (hosted mode). Only the facts the server already sees: no page views, no keystrokes, no content of scripts.

Requests are mapped to a short kind by method and path; sign-in events are logged by the auth routes."""

from __future__ import annotations

import re

LABELS = {
    "signed_up": "Created the account",
    "confirmed": "Confirmed the e-mail address",
    "login": "Logged in",
    "logout": "Logged out",
    "password_reset": "Reset the password",
    "project_created": "Created a project",
    "project_deleted": "Deleted a project",
    "export_started": "Started an export",
    "export_downloaded": "Downloaded an export",
    "video_viewed": "Watched the video",
    "captions_edited": "Edited the captions",
    "picture_swapped": "Swapped a picture",
    "avatar_added": "Added an avatar",
    "timeline_rendered": "Rendered the timeline",
    "media_added": "Added media",
    "edited": "Edited the project",
    "bonus": "Received bonus credits",
    "account_deleted": "Deleted the account",
}

# (method, path pattern, kind, seconds in which repeats count once)
RULES: list[tuple[str, re.Pattern[str], str, float]] = [
    ("POST", re.compile(r"^/api/projects$"), "project_created", 0),
    ("DELETE", re.compile(r"^/api/projects/[^/]+$"), "project_deleted", 0),
    ("POST", re.compile(r"^/api/projects/[^/]+/export$"), "export_started", 0),
    ("GET", re.compile(r"^/api/projects/[^/]+/export$"), "export_downloaded", 60),
    ("GET", re.compile(r"^/api/projects/[^/]+/video$"), "video_viewed", 600),
    ("PUT", re.compile(r"^/api/projects/[^/]+/captions$"), "captions_edited", 120),
    ("POST", re.compile(r"^/api/projects/[^/]+/scenes/\d+/swap$"), "picture_swapped", 0),
    ("POST", re.compile(r"^/api/projects/[^/]+/avatar$"), "avatar_added", 0),
    ("POST", re.compile(r"^/api/projects/[^/]+/timeline/render$"), "timeline_rendered", 0),
    ("POST", re.compile(r"^/api/projects/[^/]+/(media|bin/add)$"), "media_added", 0),
]
ANY_EDIT = re.compile(r"^/api/projects/[^/]+/.+")
PROJECT = re.compile(r"^/api/projects/([^/]+)")


def classify(method: str, path: str) -> tuple[str, str | None, float] | None:
    """(kind, project id, dedupe seconds) for a request worth logging, else None. Other changes inside a project count as one 'edited' per two minutes."""
    m = PROJECT.match(path)
    pid = m.group(1) if m else None
    for rule_method, pattern, kind, dedupe in RULES:
        if method == rule_method and pattern.match(path):
            return kind, pid, dedupe
    if method in ("POST", "PUT", "PATCH", "DELETE") and ANY_EDIT.match(path):
        return "edited", pid, 120
    return None
