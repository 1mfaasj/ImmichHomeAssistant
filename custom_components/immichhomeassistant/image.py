from __future__ import annotations

from collections import deque
from datetime import datetime, UTC
import logging
import secrets

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
    """Set up ImmichHomeAssistant image entities."""
    hub: ImmichHomeAssistantHub = hass.data[DOMAIN][config_entry.entry_id]

    entities = [ImmichImage(hass, hub)]

    hass.data.setdefault(f"{DOMAIN}_entities", {})
    hass.data[f"{DOMAIN}_entities"][config_entry.entry_id] = entities

    async_add_entities(entities)


class ImmichImage(ImageEntity):
    """Immich image entity."""

    _attr_name = "Immich Favorite"
    _attr_unique_id = "immichhomeassistant_favorite_image"
    _attr_should_poll = False
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, hub: ImmichHomeAssistantHub) -> None:
        """Initialize image entity."""
        # Home Assistant ImageEntity basis initialiseren
        ImageEntity.__init__(self, hass)

        self.hub = hub
        self._image: bytes | None = None
        self._attr_image_last_updated = None

        # Belangrijk: expliciet access_tokens aanwezig maken
        self.access_tokens = deque([secrets.token_hex(32)], maxlen=2)

    def async_update_token(self) -> None:
        """Update access token for the image endpoint."""
        self.access_tokens.append(secrets.token_hex(32))

    async def async_added_to_hass(self) -> None:
        """Load first image when entity is added."""
        await self._update_image()

    async def _update_image(self) -> None:
        """Fetch image from Immich."""
        try:
            assets = await self.hub.list_favorite_images()

            if not assets:
                _LOGGER.warning("No favorite images returned by Immich")
                return

            asset_id = assets[0]["id"]

            # Eerst thumbnail endpoint
            image = await self.hub.download_asset_thumbnail(asset_id)

            # Fallback naar originele asset
            if not image:
                image = await self.hub.download_asset(asset_id)

            if not image:
                _LOGGER.warning("No image bytes returned for asset %s", asset_id)
                return

            self._image = image

            # Nieuwe token en nieuwe timestamp zodat frontend opnieuw ophaalt
            self.async_update_token()
            self._attr_image_last_updated = datetime.now(UTC)

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.exception("Image update failed: %s", err)

    async def async_force_next_image(self) -> None:
        """Service helper for next_image."""
        await self._update_image()

    async def async_set_shuffle_mode(self, enabled: bool) -> None:
        """Compatibility stub for current service handler."""
        self.async_write_ha_state()

    async def async_set_random_speed(self, enabled: bool) -> None:
        """Compatibility stub for current service handler."""
        self.async_write_ha_state()

    async def async_set_refresh_interval(self, seconds: int) -> None:
        """Compatibility stub for current service handler."""
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return image bytes."""
        return self._image
