from __future__ import annotations

from app.config import Settings
from app.providers.base import Registry

from .gemini import GeminiPlanner
from .heuristic import HeuristicPlanner
from .interface import PlannerError, ScenePlanner

registry: Registry[ScenePlanner] = Registry("scene planner")


@registry.register("gemini")
def _gemini(s: Settings) -> ScenePlanner:
    return GeminiPlanner(s.gemini_api_key, s.gemini_model, s.scene_min_s, s.scene_max_s)


@registry.register("heuristic")
def _heuristic(s: Settings) -> ScenePlanner:
    return HeuristicPlanner(s.scene_min_s, s.scene_max_s)


def create_planner(settings: Settings) -> ScenePlanner:
    return registry.create(settings.scene_planner, settings)


__all__ = ["PlannerError", "ScenePlanner", "create_planner"]
