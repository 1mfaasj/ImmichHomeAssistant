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

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): str,
    }
)


async def validate_input(
    hass, data: dict[str, Any]
) -> dict[str, Any]:
    """Valideer de verbinding en geef genormaliseerde data terug."""
    url = url_normalize(data[CONF_HOST]).rstrip("/")
    hub = ImmichHomeAssistantHub(hass, url, data[CONF_API_KEY])
    await hub.authenticate()
    user_info = await hub.get_my_user_info()
    username = user_info.get("name") or user_info.get("email") or "Immich"
    hostname = urlparse(url).hostname or url
    return {
        "title": f"{username} @ {hostname}",
        "data": {CONF_HOST: url, CONF_API_KEY: data[CONF_API_KEY]},
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Beheer de configuratiestroom."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Onverwachte fout tijdens configuratie")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["data"][CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"], data=info["data"]
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._reauth_entry is not None:
            data = {
                CONF_HOST: self._reauth_entry.data[CONF_HOST],
                CONF_API_KEY: user_input[CONF_API_KEY],
            }
            try:
                await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Onverwachte fout tijdens herauthenticatie")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Beheer de opties van de integratie."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        errors: dict[str, str] = {}
        album_map: dict[str, str] = {}
        try:
            hub = ImmichHomeAssistantHub(
                self.hass,
                self.config_entry.data[CONF_HOST],
                self.config_entry.data[CONF_API_KEY],
            )
            albums = await hub.list_all_albums()
            album_map = {
                album["id"]: album["albumName"]
                for album in albums
                if album.get("id") and album.get("albumName")
            }
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Albums konden niet worden geladen")
            errors["base"] = "unknown"

        options = self.config_entry.options
        current = [
            album
            for album in options.get(CONF_WATCHED_ALBUMS, [])
            if album in album_map
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_WATCHED_ALBUMS, default=current): cv.multi_select(
                    album_map
                ),
                vol.Required(
                    CONF_REFRESH_INTERVAL,
                    default=options.get(
                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_REFRESH_INTERVAL,
                        max=MAX_REFRESH_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_NO_REPEAT_WINDOW,
                    default=options.get(
                        CONF_NO_REPEAT_WINDOW, DEFAULT_NO_REPEAT_WINDOW
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_NO_REPEAT_WINDOW,
                        max=MAX_NO_REPEAT_WINDOW,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_TAG_FILTER,
                    default=options.get(CONF_TAG_FILTER, DEFAULT_TAG_FILTER),
                ): TextSelector(TextSelectorConfig()),
                vol.Required(
                    CONF_SHUFFLE_MODE,
                    default=options.get(CONF_SHUFFLE_MODE, DEFAULT_SHUFFLE_MODE),
                ): BooleanSelector(),
                vol.Required(
                    CONF_RANDOM_SPEED,
                    default=options.get(CONF_RANDOM_SPEED, DEFAULT_RANDOM_SPEED),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
