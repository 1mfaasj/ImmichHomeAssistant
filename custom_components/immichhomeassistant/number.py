from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
    UID_REFRESH_INTERVAL,
)
from .models import ImmichConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Stel het verversingsinterval als number-entity in."""
    async_add_entities([ImmichRefreshIntervalNumber(config_entry)])


class ImmichRefreshIntervalNumber(NumberEntity):
    """Verversingsinterval voor alle fotobronnen (blijft na herstart bewaard)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = CONF_REFRESH_INTERVAL
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_REFRESH_INTERVAL
    _attr_native_max_value = MAX_REFRESH_INTERVAL
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, config_entry: ImmichConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = UID_REFRESH_INTERVAL
        self._attr_device_info = config_entry.runtime_data.device_info

    @property
    def native_value(self) -> float:
        return float(
            self._entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
        )

    async def async_set_native_value(self, value: float) -> None:
        seconds = int(value)
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_REFRESH_INTERVAL: seconds},
        )
        for entity in self._entry.runtime_data.entities.values():
            await entity.async_set_refresh_interval(seconds)
        self.async_write_ha_state()
