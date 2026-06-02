from __future__ import annotations

from datetime import datetime, UTC
import logging

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import ImmichHomeAssistantHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up image entity."""
    hub: ImmichHomeAssistantHub = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([
        ImmichImage(hub)
    ])


class ImmichImage(ImageEntity):
    """Basic Immich image entity."""

    _attr_name = "Immich Favorite"
    _attr_unique_id = "immichhomeassistant_favorite_image"
    _attr_should_poll = False
    _attr_content_type = "image/jpeg"

    def __init__(self, hub: ImmichHomeAssistantHub):
        self.hub = hub
        self._image = None
        self._attr_image_last_updated = None

    async def async_added_to_hass(self):
        await self._update_image()

    async def _update_image(self):
        """Fetch image."""
        try:
            assets = await self.hub.list_favorite_images()

            if not assets:
                return

            asset_id = assets[0]["id"]

            # ✅ thumbnail eerst
            image = await self.hub.download_asset_thumbnail(asset_id)

            # fallback
            if not image:
                image = await self.hub.download_asset(asset_id)

            if not image:
                return

            self._image = image
            self._attr_image_last_updated = datetime.now(UTC)
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Image update failed: %s", e)

    async def async_image(self):
        return self._image
