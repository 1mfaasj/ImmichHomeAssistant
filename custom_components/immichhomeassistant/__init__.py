from __future__ import annotations

from collections.abc import Iterable
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_API_KEY, CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
)
from .hub import CannotConnect, ImmichHomeAssistantHub, InvalidAuth

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.IMAGE]

type ImmichConfigEntry = ConfigEntry[ImmichHomeAssistantHub]

SERVICE_NEXT_IMAGE = "next_image"
SERVICE_SET_SHUFFLE_MODE = "set_shuffle_mode"
SERVICE_SET_RANDOM_SPEED = "set_random_speed"
SERVICE_SET_REFRESH_INTERVAL = "set_refresh_interval"
ATTR_ENABLED = "enabled"
ATTR_SECONDS = "seconds"
ENTITY_STORE = f"{DOMAIN}_entities"

SERVICE_ENTITY_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id])}
)
SERVICE_ENABLED_SCHEMA = SERVICE_ENTITY_SCHEMA.extend(
    {vol.Required(ATTR_ENABLED): cv.boolean}
)
SERVICE_INTERVAL_SCHEMA = SERVICE_ENTITY_SCHEMA.extend(
    {
        vol.Required(ATTR_SECONDS): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL),
        )
    }
)


def _iter_entities(hass: HomeAssistant) -> Iterable:
    for entity_list in hass.data.get(ENTITY_STORE, {}).values():
        yield from entity_list


def _target_entities(hass: HomeAssistant, call: ServiceCall) -> list:
    requested = call.data.get(ATTR_ENTITY_ID)
    if requested is None:
        return list(_iter_entities(hass))
    entity_ids = {requested} if isinstance(requested, str) else set(requested)
    return [entity for entity in _iter_entities(hass) if entity.entity_id in entity_ids]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registreer integratiebrede acties."""
    hass.data.setdefault(ENTITY_STORE, {})

    async def handle_next_image(call: ServiceCall) -> None:
        for entity in _target_entities(hass, call):
            await entity.async_force_next_image()

    async def handle_set_shuffle_mode(call: ServiceCall) -> None:
        for entity in _target_entities(hass, call):
            await entity.async_set_shuffle_mode(bool(call.data[ATTR_ENABLED]))

    async def handle_set_random_speed(call: ServiceCall) -> None:
        for entity in _target_entities(hass, call):
            await entity.async_set_random_speed(bool(call.data[ATTR_ENABLED]))

    async def handle_set_refresh_interval(call: ServiceCall) -> None:
        for entity in _target_entities(hass, call):
            await entity.async_set_refresh_interval(int(call.data[ATTR_SECONDS]))

    services = (
        (SERVICE_NEXT_IMAGE, handle_next_image, SERVICE_ENTITY_SCHEMA),
        (SERVICE_SET_SHUFFLE_MODE, handle_set_shuffle_mode, SERVICE_ENABLED_SCHEMA),
        (SERVICE_SET_RANDOM_SPEED, handle_set_random_speed, SERVICE_ENABLED_SCHEMA),
        (
            SERVICE_SET_REFRESH_INTERVAL,
            handle_set_refresh_interval,
            SERVICE_INTERVAL_SCHEMA,
        ),
    )
    for name, handler, schema in services:
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ImmichConfigEntry
) -> bool:
    """Stel ImmichHomeAssistant in vanuit een config entry."""
    hub = ImmichHomeAssistantHub(
        hass=hass,
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
    )

    try:
        await hub.authenticate()
    except InvalidAuth as error:
        raise ConfigEntryAuthFailed("De Immich API-sleutel is ongeldig") from error
    except CannotConnect as error:
        raise ConfigEntryNotReady(str(error)) from error

    entry.runtime_data = hub
    hass.data.setdefault(ENTITY_STORE, {})[entry.entry_id] = []
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ImmichConfigEntry
) -> bool:
    """Verwijder een config entry en alle gekoppelde entities."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(ENTITY_STORE, {}).pop(entry.entry_id, None)
    return unload_ok
