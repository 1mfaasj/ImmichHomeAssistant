"""The ImmichHomeAssistant integration."""
from __future__ import annotations

from collections.abc import Iterable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .hub import ImmichHomeAssistantHub, InvalidAuth

PLATFORMS: list[Platform] = [Platform.IMAGE]

SERVICE_NEXT_IMAGE = "next_image"
SERVICE_SET_SHUFFLE_MODE = "set_shuffle_mode"
SERVICE_SET_RANDOM_SPEED = "set_random_speed"
SERVICE_SET_REFRESH_INTERVAL = "set_refresh_interval"
ATTR_ENABLED = "enabled"
ATTR_SECONDS = "seconds"

SERVICE_ENTITY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id]),
    }
)

SERVICE_ENABLED_SCHEMA = SERVICE_ENTITY_SCHEMA.extend(
    {
        vol.Required(ATTR_ENABLED): bool,
    }
)

SERVICE_INTERVAL_SCHEMA = SERVICE_ENTITY_SCHEMA.extend(
    {
        vol.Required(ATTR_SECONDS): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up services for ImmichHomeAssistant."""
    hass.data.setdefault(DOMAIN, {})

    def _iter_entities() -> Iterable:
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, dict):
                for entity in entry_data.get("entities", []):
                    yield entity

    def _target_entities(call: ServiceCall):
        requested = call.data.get(ATTR_ENTITY_ID)
        if requested is None:
            return list(_iter_entities())
        if isinstance(requested, str):
            requested_ids = {requested}
        else:
            requested_ids = set(requested)
        return [entity for entity in _iter_entities() if entity.entity_id in requested_ids]

    async def handle_next_image(call: ServiceCall) -> None:
        for entity in _target_entities(call):
            await entity.async_force_next_image()

    async def handle_set_shuffle_mode(call: ServiceCall) -> None:
        enabled = bool(call.data[ATTR_ENABLED])
        for entity in _target_entities(call):
            await entity.async_set_shuffle_mode(enabled)

    async def handle_set_random_speed(call: ServiceCall) -> None:
        enabled = bool(call.data[ATTR_ENABLED])
        for entity in _target_entities(call):
            await entity.async_set_random_speed(enabled)

    async def handle_set_refresh_interval(call: ServiceCall) -> None:
        seconds = int(call.data[ATTR_SECONDS])
        for entity in _target_entities(call):
            await entity.async_set_refresh_interval(seconds)

    if not hass.services.has_service(DOMAIN, SERVICE_NEXT_IMAGE):
        hass.services.async_register(DOMAIN, SERVICE_NEXT_IMAGE, handle_next_image, schema=SERVICE_ENTITY_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SHUFFLE_MODE):
        hass.services.async_register(DOMAIN, SERVICE_SET_SHUFFLE_MODE, handle_set_shuffle_mode, schema=SERVICE_ENABLED_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_RANDOM_SPEED):
        hass.services.async_register(DOMAIN, SERVICE_SET_RANDOM_SPEED, handle_set_random_speed, schema=SERVICE_ENABLED_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_REFRESH_INTERVAL):
        hass.services.async_register(DOMAIN, SERVICE_SET_REFRESH_INTERVAL, handle_set_refresh_interval, schema=SERVICE_INTERVAL_SCHEMA)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ImmichHomeAssistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = ImmichHomeAssistantHub(
        hass=hass,
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
    )

    if not await hub.authenticate():
        raise InvalidAuth

    hass.data[DOMAIN][entry.entry_id] = {"hub": hub, "entities": []}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
