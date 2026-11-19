"""Per-user limits of the hosted mode: how many projects, how many bytes, how many jobs at once, how many exports a day."""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.api.store import ProjectStore
from app.config import Settings

WORDS_PER_MINUTE = 150  # to price a typed script before it is spoken


class CreditsExhausted(Exception):
    """Not enough credits for this video; the message says how many it needs, how many are left and when they renew."""


def month_start(now: float | None = None) -> datetime:
    t = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc)
    return t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now: float | None = None) -> datetime:
    s = month_start(now)
    return s.replace(year=s.year + 1, month=1) if s.month == 12 else s.replace(month=s.month + 1)


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
    def __init__(self, s: Settings, store: ProjectStore, accounts=None) -> None:
        self.s, self.store, self.accounts = s, store, accounts
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

    # ---- credits
    def cost_for_seconds(self, seconds: float) -> int:
        return max(1, math.ceil(seconds / 60 / max(0.1, self.s.credit_minutes)))

    def cost_for_script(self, text: str) -> int:
        return self.cost_for_seconds(len(text.split()) / WORDS_PER_MINUTE * 60)

    def credits(self, user_id: str, admin: bool = False) -> dict:
        monthly = self.s.credits_per_month
        used = 0 if self.accounts is None else -self.accounts.credit_sum(user_id, month_start().timestamp())
        return {"plan": self.s.credits_plan_name, "monthly": monthly, "used": max(0, used), "remaining": max(0, monthly - used),
                "resets_on": next_month_start().date().isoformat(), "unlimited": admin, "minutes_per_credit": self.s.credit_minutes}

    def charge(self, user_id: str, cost: int, project_id: str, admin: bool = False) -> None:
        """Takes the credits for a new video, or raises CreditsExhausted. Administrators are not charged."""
        if admin or self.accounts is None:
            return
        c = self.credits(user_id)
        if cost > c["remaining"]:
            raise CreditsExhausted(f"Not enough credits: this video needs {cost}, you have {c['remaining']} left this month (they renew on {c['resets_on']}).")
        self.accounts.credit_add(user_id, -cost, "video", project_id)

    def refund_project(self, user_id: str | None, project_id: str) -> None:
        """A video that could not be made gives its credits back (once)."""
        if self.accounts is None or not user_id:
            return
        spent = self.accounts.credit_event_for(project_id, "video")
        if spent and self.accounts.credit_event_for(project_id, "refund") is None:
            self.accounts.credit_add(user_id, -spent, "refund", project_id)

    def summary(self, user_id: str, admin: bool = False) -> dict:
        used = self.storage_bytes(user_id, max_age=0)
        return {"credits": self.credits(user_id, admin), "projects": len(self.projects(user_id)), "max_projects": self.s.max_projects_per_user,
                "storage_bytes": used, "max_storage_bytes": self.s.max_storage_mb_per_user * 1024 * 1024,
                "max_exports_per_day": self.s.max_exports_per_day}
