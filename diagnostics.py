from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import ImmichConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ImmichConfigEntry
) -> dict[str, Any]:
    """Geef veilige diagnostische informatie terug."""
    hub = entry.runtime_data
    entities = hass.data.get("immichhomeassistant_entities", {}).get(entry.entry_id, [])
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "hub": {
            "host": hub.host,
            "last_success": hub.last_success,
            "last_error": hub.last_error,
        },
        "entities": [
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "available": entity.available,
                "attributes": entity.extra_state_attributes,
            }
            for entity in entities
        ],
    }
