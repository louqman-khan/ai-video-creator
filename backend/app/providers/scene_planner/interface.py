from __future__ import annotations

from typing import Protocol

from app.models import Scene, Transcript


class PlannerError(RuntimeError):
    pass


class ScenePlanner(Protocol):
    def plan(self, transcript: Transcript) -> list[Scene]:
        """Transcript -> timed scenes, each with an English search query + keywords."""
        ...
