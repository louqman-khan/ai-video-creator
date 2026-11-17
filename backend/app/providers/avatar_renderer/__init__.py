"""AvatarRenderer: a talking character for the narration (task 5.2).

- `simple` (default, CPU, no model files): cartoon characters drawn in code; the mouth, blinking and a small head bob follow the loudness of the
  narration. It is "lip-sync" in the sense of open/close timing, not of speech sounds. Rendered on solid green: the editor puts it on the timeline
  with the green screen key already on.
- `remote`: a GPU service (MuseTalk, LatentSync, ...) over a small HTTP protocol, see docs/avatars.md. It can run on a rented GPU or Colab and is
  NOT verified here (no GPU); `backend/tools/avatar_service.py` is the reference server for the protocol.
- `none`: off."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.providers.base import Registry

KEY_COLOUR = "#00ff00"  # the background every renderer draws on


class AvatarUnavailable(RuntimeError):
    """The renderer cannot be used (the message says why and what to do)."""


@dataclass(frozen=True)
class AvatarInfo:
    id: str
    name: str


class AvatarRenderer(Protocol):
    def avatars(self) -> list[AvatarInfo]: ...

    def thumbnail(self, avatar_id: str) -> bytes:
        """A PNG preview of the avatar for the picker."""
        ...

    def render(self, avatar_id: str, audio: Path, out: Path, progress: Callable[[float], None] | None = None) -> Path:
        """An mp4 of the avatar speaking `audio` (same length as the audio, KEY_COLOUR background, no sound track)."""
        ...


class UnavailableAvatarRenderer:
    def avatars(self) -> list[AvatarInfo]:
        return []

    def thumbnail(self, avatar_id: str) -> bytes:
        raise AvatarUnavailable("Avatars are switched off (AVATAR_RENDERER=none).")

    def render(self, avatar_id: str, audio: Path, out: Path, progress: Callable[[float], None] | None = None) -> Path:
        raise AvatarUnavailable("Avatars are switched off (AVATAR_RENDERER=none).")


registry: Registry[AvatarRenderer] = Registry("avatar renderer")


@registry.register("none")
def _none(settings: Settings) -> AvatarRenderer:
    return UnavailableAvatarRenderer()


@registry.register("simple")
def _simple(settings: Settings) -> AvatarRenderer:
    from app.providers.avatar_renderer.simple import SimpleAvatars

    return SimpleAvatars()


@registry.register("remote")
def _remote(settings: Settings) -> AvatarRenderer:
    from app.providers.avatar_renderer.remote import RemoteAvatars

    return RemoteAvatars(settings.avatar_url, settings.avatar_token)


def create_avatar_renderer(settings: Settings) -> AvatarRenderer:
    return registry.create(settings.avatar_renderer, settings)


__all__ = ["AvatarInfo", "AvatarRenderer", "AvatarUnavailable", "KEY_COLOUR", "create_avatar_renderer"]
