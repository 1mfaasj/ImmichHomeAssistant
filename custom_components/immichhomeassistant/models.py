from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import (
    DOMAIN,
    UID_FAVORITES,
    album_unique_id,
)

if TYPE_CHECKING:
    from .hub import ImmichHomeAssistantHub
    from .image import BaseImmichHomeAssistantImage


class SourceKind(StrEnum):
    FAVORITES = "favorites"
    ALBUM = "album"


@dataclass(frozen=True, slots=True)
class ImageSource:
    """Beschrijving van een fotobron (favorieten of album)."""

    kind: SourceKind
    album_id: str | None = None
    album_name: str | None = None

    @property
    def unique_id(self) -> str:
        if self.kind is SourceKind.ALBUM:
            assert self.album_id is not None
            return album_unique_id(self.album_id)
        return UID_FAVORITES


@dataclass(slots=True)
class ImmichRuntimeData:
    hub: ImmichHomeAssistantHub
    sources: list[ImageSource]
    device_info: DeviceInfo
    entities: dict[str, BaseImmichHomeAssistantImage] = field(default_factory=dict)


type ImmichConfigEntry = ConfigEntry[ImmichRuntimeData]


def build_device_info(entry: ConfigEntry, host: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Immich",
        manufacturer="Immich",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=host,
    )
