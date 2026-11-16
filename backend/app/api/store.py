"""Projects on disk: <projects_dir>/<id>/project.json plus all files of that project's run."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_ID = re.compile(r"^[0-9a-f]{32}$")
Status = Literal["queued", "running", "done", "failed"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectInfo(BaseModel):
    id: str
    name: str
    status: Status = "queued"
    stage: str = ""
    progress: float = 0.0  # 0..1
    message: str = ""
    error: str | None = None
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    original_filename: str = ""
    audio_file: str = ""  # name inside the project dir (never the user's filename)
    language: str | None = None
    aspect: str = "16:9"
    options: dict = Field(default_factory=dict)
    video_ready: bool = False


class ProjectNotFound(KeyError):
    pass


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, project_id: str) -> Path:
        if not _ID.match(project_id):  # also rules out path traversal
            raise ProjectNotFound(project_id)
        return self.root / project_id

    def create(self, name: str, **fields) -> ProjectInfo:
        pid = uuid.uuid4().hex
        (self.root / pid).mkdir(parents=True)
        info = ProjectInfo(id=pid, name=name, **fields)
        self._write(info)
        return info

    def _write(self, info: ProjectInfo) -> None:
        target = self.path(info.id) / "project.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(info.model_dump_json(indent=2), "utf-8")
        os.replace(tmp, target)  # atomic: a reader never sees half a file

    def get(self, project_id: str) -> ProjectInfo:
        f = self.path(project_id) / "project.json"
        with self._lock:
            if not f.is_file():
                raise ProjectNotFound(project_id)
            return ProjectInfo.model_validate_json(f.read_text("utf-8"))

    def update(self, project_id: str, **fields) -> ProjectInfo:
        with self._lock:
            info = self.get(project_id).model_copy(update={**fields, "updated_at": now()})
            self._write(info)
            return info

    def list(self) -> list[ProjectInfo]:
        out = []
        for d in self.root.iterdir():
            try:
                out.append(self.get(d.name))
            except (ProjectNotFound, json.JSONDecodeError, ValueError):
                continue  # a broken folder must not break the list
        return sorted(out, key=lambda p: p.created_at, reverse=True)

    def delete(self, project_id: str) -> None:
        d = self.path(project_id)
        if not d.is_dir():
            raise ProjectNotFound(project_id)
        shutil.rmtree(d)

    def recover_interrupted(self) -> int:
        """After a restart nothing is really running: mark leftovers as failed."""
        n = 0
        for p in self.list():
            if p.status in ("queued", "running"):
                self.update(p.id, status="failed", error="The server restarted while this project was processing. Start it again.")
                n += 1
        return n
