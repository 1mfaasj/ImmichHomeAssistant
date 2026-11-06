"""Tests voor de config- en optiesflow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immichhomeassistant.const import CONF_WATCHED_ALBUMS, DOMAIN
from custom_components.immichhomeassistant.hub import CannotConnect

FLOW_HUB = "custom_components.immichhomeassistant.config_flow.ImmichHomeAssistantHub"


async def test_user_flow(hass: HomeAssistant) -> None:
    with (
        patch(FLOW_HUB, autospec=True) as hub_cls,
        patch("custom_components.immichhomeassistant.async_setup_entry", return_value=True),
    ):
        hub_cls.return_value.get_my_user_info.return_value = {"name": "John"}
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "http://immich.local:2283/", "api_key": "k"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "John @ immich.local"
    assert result["data"]["host"] == "http://immich.local:2283"


async def test_only_one_server(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_abort_keeps_albums_when_immich_down(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch(FLOW_HUB, autospec=True) as hub_cls:
        hub_cls.return_value.list_all_albums.side_effect = CannotConnect("down")
        result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert config_entry.options[CONF_WATCHED_ALBUMS] == ["album-1"]


async def test_options_flow_saves(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch(FLOW_HUB, autospec=True) as hub_cls:
        hub_cls.return_value.list_all_albums.return_value = [
            {"id": "album-1", "albumName": "Vakantie"},
            {"id": "album-2", "albumName": "Tuin"},
        ]
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_WATCHED_ALBUMS: ["album-2"],
                "refresh_interval": 120,
                "no_repeat_window": 5,
                "shuffle_mode": True,
                "random_speed": False,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_WATCHED_ALBUMS] == ["album-2"]


def test_normalize_url() -> None:
    from custom_components.immichhomeassistant.config_flow import normalize_url

    assert normalize_url(" Immich.Local:2283/ ") == "https://immich.local:2283"
    assert normalize_url("http://192.168.1.10:2283/") == "http://192.168.1.10:2283"
    assert normalize_url("https://example.com/immich/?x=1") == "https://example.com/immich"
