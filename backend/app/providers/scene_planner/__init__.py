from __future__ import annotations

import logging

from app.config import Settings
from app.providers.base import Registry

from .gemini import GeminiPlanner
from .heuristic import HeuristicPlanner
from .interface import PlannerError, ScenePlanner

log = logging.getLogger("avc.planner")
registry: Registry[ScenePlanner] = Registry("scene planner")


class FallbackPlanner:
    """Try the LLM planner; if it fails, use the no-LLM planner (English only) and say so."""

    def __init__(self, primary: ScenePlanner, fallback: ScenePlanner) -> None:
        self.primary, self.fallback = primary, fallback

    def plan(self, transcript):
        try:
            return self.primary.plan(transcript)
        except PlannerError as e:
            log.warning("LLM planner failed (%s); falling back to the heuristic planner", e)
            return self.fallback.plan(transcript)  # raises a clear error for non-English


@registry.register("gemini")
def _gemini(s: Settings) -> ScenePlanner:
    return GeminiPlanner(s.gemini_api_key, s.gemini_model, s.scene_min_s, s.scene_max_s)


@registry.register("heuristic")
def _heuristic(s: Settings) -> ScenePlanner:
    return HeuristicPlanner(s.scene_min_s, s.scene_max_s)


def create_planner(settings: Settings) -> ScenePlanner:
    planner = registry.create(settings.scene_planner, settings)
    if settings.scene_planner != "heuristic":
        planner = FallbackPlanner(planner, registry.create("heuristic", settings))
    return planner


__all__ = ["PlannerError", "ScenePlanner", "create_planner"]
