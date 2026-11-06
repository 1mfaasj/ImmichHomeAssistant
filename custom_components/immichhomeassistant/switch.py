from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_RANDOM_SPEED,
    CONF_SHUFFLE_MODE,
    DEFAULT_RANDOM_SPEED,
    DEFAULT_SHUFFLE_MODE,
    UID_RANDOM_SPEED,
    UID_SHUFFLE_MODE,
)
from .models import ImmichConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Stel de schakelaars voor shuffle en willekeurige snelheid in."""
    async_add_entities(
        [
            ImmichOptionSwitch(
                config_entry,
                CONF_SHUFFLE_MODE,
                DEFAULT_SHUFFLE_MODE,
                UID_SHUFFLE_MODE,
                "async_set_shuffle_mode",
            ),
            ImmichOptionSwitch(
                config_entry,
                CONF_RANDOM_SPEED,
                DEFAULT_RANDOM_SPEED,
                UID_RANDOM_SPEED,
                "async_set_random_speed",
            ),
        ]
    )


class ImmichOptionSwitch(SwitchEntity):
    """Schakelaar die een integratie-optie aanpast voor alle fotobronnen.

    De waarde wordt in de opties opgeslagen en blijft dus na een herstart
    behouden.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        config_entry: ImmichConfigEntry,
        option: str,
        default: bool,
        unique_id: str,
        entity_method: str,
    ) -> None:
        self._entry = config_entry
        self._option = option
        self._default = default
        self._entity_method = entity_method
        self._attr_unique_id = unique_id
        self._attr_translation_key = option
        self._attr_device_info = config_entry.runtime_data.device_info

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(self._option, self._default))

    async def _async_set(self, value: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, self._option: value}
        )
        for entity in self._entry.runtime_data.entities.values():
            await getattr(entity, self._entity_method)(value)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
