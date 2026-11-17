"""Per-user limits of the hosted mode: how many projects, how many bytes, how many jobs at once, how many exports a day."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.api.store import ProjectStore
from app.config import Settings


def dir_bytes(p: Path) -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


class Quotas:
    def __init__(self, s: Settings, store: ProjectStore) -> None:
        self.s, self.store = s, store
        self._cache: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def projects(self, user_id: str):
        return self.store.list(owner=user_id)

    def storage_bytes(self, user_id: str, max_age: float = 20.0) -> int:
        """Bytes in all of the user's project folders (remembered for a few seconds: measuring a big folder is not free)."""
        with self._lock:
            hit = self._cache.get(user_id)
            if hit and time.monotonic() - hit[0] < max_age:
                return hit[1]
        total = sum(dir_bytes(self.store.path(p.id)) for p in self.projects(user_id))
        with self._lock:
            self._cache[user_id] = (time.monotonic(), total)
        return total

    def forget(self, user_id: str) -> None:
        with self._lock:
            self._cache.pop(user_id, None)

    def active_jobs(self, user_id: str, except_project: str | None = None) -> int:
        return sum(1 for p in self.projects(user_id) if p.status in ("queued", "running") and p.id != except_project)

    def summary(self, user_id: str) -> dict:
        used = self.storage_bytes(user_id, max_age=0)
        return {"projects": len(self.projects(user_id)), "max_projects": self.s.max_projects_per_user,
                "storage_bytes": used, "max_storage_bytes": self.s.max_storage_mb_per_user * 1024 * 1024,
                "max_exports_per_day": self.s.max_exports_per_day}
