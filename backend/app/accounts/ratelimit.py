"""A small in-memory sliding-window limiter (one process; enough for one server, replace by Redis when there are several)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, per_seconds: float) -> bool:
        """True and counts the attempt, or False when `key` already used `limit` attempts in the last `per_seconds`."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > per_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # forget idle keys so that the table cannot grow forever
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > per_seconds]:
                    self._hits.pop(k, None)
            return True
