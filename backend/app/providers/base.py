from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Name -> factory. Config picks the implementation, e.g. SCENE_PLANNER=gemini."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, name: str):
        def deco(factory: Callable[..., T]) -> Callable[..., T]:
            self._factories[name] = factory
            return factory

        return deco

    def create(self, name: str, *args, **kwargs) -> T:
        try:
            factory = self._factories[name]
        except KeyError:
            known = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(f"Unknown {self.kind} '{name}'. Available: {known}") from None
        return factory(*args, **kwargs)

    @property
    def names(self) -> list[str]:
        return sorted(self._factories)
