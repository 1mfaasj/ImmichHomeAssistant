"""Config flow for ImmichHomeAssistant."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from url_normalize import url_normalize

from .const import (
    CONF_NO_REPEAT_WINDOW,
    CONF_RANDOM_SPEED,
    CONF_REFRESH_INTERVAL,
    CONF_SHUFFLE_MODE,
    CONF_TAG_FILTER,
    CONF_WATCHED_ALBUMS,
    DEFAULT_NO_REPEAT_WINDOW,
    DEFAULT_RANDOM_SPEED,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_SHUFFLE_MODE,
    DEFAULT_TAG_FILTER,
    DOMAIN,
    MAX_NO_REPEAT_WINDOW,
    MAX_REFRESH_INTERVAL,
    MIN_NO_REPEAT_WINDOW,
    MIN_REFRESH_INTERVAL,
)
from .hub import CannotConnect, ImmichHomeAssistantHub, InvalidAuth

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_API_KEY): str,
})


async def validate_input(hass, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    url = url_normalize(data[CONF_HOST])
    api_key = data[CONF_API_KEY]
    hub = ImmichHomeAssistantHub(hass=hass, host=url, api_key=api_key)

    if not await hub.authenticate():
        raise InvalidAuth

    user_info = await hub.get_my_user_info()
    username = user_info.get("name", "ImmichHomeAssistant")
    clean_hostname = urlparse(url).hostname or url
    return {
        "title": f"{username} @ {clean_hostname}",
        "data": {CONF_HOST: url, CONF_API_KEY: api_key},
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ImmichHomeAssistant."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["data"][CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=info["data"])

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """ImmichHomeAssistant options flow handler."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            merged = dict(self.config_entry.options)
            merged.update(user_input)
            return self.async_create_entry(title="", data=merged)

        url = url_normalize(self.config_entry.data[CONF_HOST])
        api_key = self.config_entry.data[CONF_API_KEY]
        hub = ImmichHomeAssistantHub(hass=self.hass, host=url, api_key=api_key)

        if not await hub.authenticate():
            raise InvalidAuth

        albums = await hub.list_all_albums()
        album_map = {
            album["id"]: album["albumName"]
            for album in albums
            if "id" in album and "albumName" in album
        }
        current_albums_value = [
            album for album in self.config_entry.options.get(CONF_WATCHED_ALBUMS, [])
            if album in album_map
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WATCHED_ALBUMS, default=current_albums_value): cv.multi_select(album_map),
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=self.config_entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL, step=1, mode=NumberSelectorMode.BOX)
                    ),
                    vol.Required(
                        CONF_NO_REPEAT_WINDOW,
                        default=self.config_entry.options.get(CONF_NO_REPEAT_WINDOW, DEFAULT_NO_REPEAT_WINDOW),
                    ): NumberSelector(
                        NumberSelectorConfig(min=MIN_NO_REPEAT_WINDOW, max=MAX_NO_REPEAT_WINDOW, step=1, mode=NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_TAG_FILTER,
                        default=self.config_entry.options.get(CONF_TAG_FILTER, DEFAULT_TAG_FILTER),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Required(
                        CONF_SHUFFLE_MODE,
                        default=self.config_entry.options.get(CONF_SHUFFLE_MODE, DEFAULT_SHUFFLE_MODE),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_RANDOM_SPEED,
                        default=self.config_entry.options.get(CONF_RANDOM_SPEED, DEFAULT_RANDOM_SPEED),
                    ): BooleanSelector(),
                }
            ),
        )
