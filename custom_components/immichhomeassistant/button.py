from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import next_button_unique_id
from .models import ImageSource, ImmichConfigEntry, SourceKind

_TRANSLATION_KEYS = {
    SourceKind.FAVORITES: "next_favorites",
    SourceKind.ON_THIS_DAY: "next_on_this_day",
    SourceKind.ALBUM: "next_album",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Stel een 'volgende foto'-knop per fotobron in."""
    async_add_entities(
        ImmichNextImageButton(config_entry, source)
        for source in config_entry.runtime_data.sources
    )


class ImmichNextImageButton(ButtonEntity):
    """Knop die direct naar de volgende foto van een bron springt."""

    _attr_has_entity_name = True

    def __init__(self, config_entry: ImmichConfigEntry, source: ImageSource) -> None:
        self._entry = config_entry
        self._source = source
        self._attr_unique_id = next_button_unique_id(source.unique_id)
        self._attr_device_info = config_entry.runtime_data.device_info
        self._attr_translation_key = _TRANSLATION_KEYS[source.kind]
        if source.kind is SourceKind.ALBUM:
            self._attr_translation_placeholders = {
                "album": source.album_name or source.album_id or ""
            }

    async def async_press(self) -> None:
        entity = self._entry.runtime_data.entities.get(self._source.unique_id)
        if entity is None:
            raise HomeAssistantError("De bijbehorende afbeelding is niet geladen")
        await entity.async_force_next_image()
