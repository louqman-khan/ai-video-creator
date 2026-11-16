"""AvatarRenderer provider interface (Step 5, needs a GPU).
Planned defaults: LatentSync / MuseTalk."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.providers.base import Registry


class AvatarRenderer(Protocol):
    def render(self, avatar_id: str, audio: Path, out: Path) -> Path:
        """Lip-synced avatar video for the given narration audio."""
        ...


class UnavailableAvatarRenderer:
    def render(self, avatar_id: str, audio: Path, out: Path) -> Path:
        raise NotImplementedError("No avatar renderer is configured yet (planned for Step 5, GPU).")


registry: Registry[AvatarRenderer] = Registry("avatar renderer")


@registry.register("none")
def _none(settings: Settings) -> AvatarRenderer:
    return UnavailableAvatarRenderer()


def create_avatar_renderer(settings: Settings) -> AvatarRenderer:
    return registry.create(settings.avatar_renderer, settings)


__all__ = ["AvatarRenderer", "create_avatar_renderer"]
