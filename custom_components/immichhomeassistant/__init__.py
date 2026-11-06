from __future__ import annotations

import logging

from homeassistant.const import CONF_API_KEY, CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ON_THIS_DAY,
    CONF_WATCHED_ALBUMS,
    DEFAULT_ON_THIS_DAY,
    UID_RANDOM_SPEED,
    UID_REFRESH_INTERVAL,
    UID_SHUFFLE_MODE,
    next_button_unique_id,
    original_unique_id,
)
from .hub import ApiError, CannotConnect, ImmichHomeAssistantHub, InvalidAuth
from .models import (
    ImageSource,
    ImmichConfigEntry,
    ImmichRuntimeData,
    SourceKind,
    build_device_info,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.IMAGE,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ImmichConfigEntry) -> bool:
    """Stel ImmichHomeAssistant in vanuit een config entry."""
    hub = ImmichHomeAssistantHub(
        hass=hass,
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
    )

    try:
        await hub.authenticate()
        sources = await _async_build_sources(hub, entry)
    except InvalidAuth as error:
        raise ConfigEntryAuthFailed("De Immich API-sleutel is ongeldig") from error
    except (CannotConnect, ApiError) as error:
        raise ConfigEntryNotReady(str(error)) from error

    entry.runtime_data = ImmichRuntimeData(
        hub=hub,
        sources=sources,
        device_info=build_device_info(entry, hub.host),
    )
    _async_remove_stale_entities(hass, entry, sources)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ImmichConfigEntry) -> bool:
    """Verwijder een config entry en alle gekoppelde entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_build_sources(
    hub: ImmichHomeAssistantHub, entry: ImmichConfigEntry
) -> list[ImageSource]:
    sources = [ImageSource(SourceKind.FAVORITES)]

    if entry.options.get(CONF_ON_THIS_DAY, DEFAULT_ON_THIS_DAY):
        sources.append(ImageSource(SourceKind.ON_THIS_DAY))

    watched_album_ids = entry.options.get(CONF_WATCHED_ALBUMS, [])
    if watched_album_ids:
        album_map = {
            album["id"]: album["albumName"]
            for album in await hub.list_all_albums()
            if album.get("id") and album.get("albumName")
        }
        for album_id in watched_album_ids:
            if album_name := album_map.get(album_id):
                sources.append(ImageSource(SourceKind.ALBUM, album_id, album_name))
            else:
                _LOGGER.warning(
                    "Gekozen Immich-album %s bestaat niet meer en wordt overgeslagen",
                    album_id,
                )

    return sources


def _async_remove_stale_entities(
    hass: HomeAssistant, entry: ImmichConfigEntry, sources: list[ImageSource]
) -> None:
    """Ruim entities op van albums die niet meer gevolgd worden."""
    expected = {UID_SHUFFLE_MODE, UID_RANDOM_SPEED, UID_REFRESH_INTERVAL}
    for source in sources:
        expected.update(
            {
                source.unique_id,
                original_unique_id(source.unique_id),
                next_button_unique_id(source.unique_id),
            }
        )

    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.unique_id not in expected:
            _LOGGER.debug("Verouderde entity %s verwijderd", registry_entry.entity_id)
            registry.async_remove(registry_entry.entity_id)
