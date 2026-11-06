from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .models import ImmichConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ImmichConfigEntry
) -> dict[str, Any]:
    """Geef veilige diagnostische informatie terug."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "hub": {
            "host": data.hub.host,
            "last_success": data.hub.last_success,
            "last_error": data.hub.last_error,
        },
        "sources": [
            {"kind": source.kind, "album_id": source.album_id, "name": source.album_name}
            for source in data.sources
        ],
        "entities": [
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "available": entity.available,
                "attributes": entity.extra_state_attributes,
            }
            for entity in data.entities.values()
        ],
    }
