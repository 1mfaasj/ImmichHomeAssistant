"""Tests voor de image-entities en bedieningsentities."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immichhomeassistant.const import (
    CONF_REFRESH_INTERVAL,
    CONF_SHUFFLE_MODE,
    CONF_TAG_FILTER,
    DOMAIN,
)
from custom_components.immichhomeassistant.image import (
    ImmichHomeAssistantFavoriteImage,
    asset_metadata,
    parse_tag_filter,
)

from .conftest import make_asset


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id
    return entity_id


async def test_setup_creates_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    await _setup(hass, config_entry)

    fav = _entity_id(hass, "image", "immichhomeassistant_favorite_image")
    state = hass.states.get(fav)
    assert state.state != "unavailable"
    assert state.name == "Immich Favorites"
    assert state.attributes["available_assets"] == 2
    assert state.attributes["city"] == "Utrecht"
    assert state.attributes["photo_date"].year == 2020

    for platform, uid in (
        ("image", "immichhomeassistant_favorite_image_original"),
        ("image", "immichhomeassistant_album_album-1"),
        ("image", "immichhomeassistant_album_album-1_original"),
        ("button", "immichhomeassistant_favorite_image_next"),
        ("button", "immichhomeassistant_album_album-1_next"),
        ("switch", "immichhomeassistant_shuffle_mode"),
        ("switch", "immichhomeassistant_random_speed"),
        ("number", "immichhomeassistant_refresh_interval"),
    ):
        _entity_id(hass, platform, uid)

    album = hass.states.get(_entity_id(hass, "image", "immichhomeassistant_album_album-1"))
    assert album.name == "Immich Vakantie"
    mock_hub.download_asset_preview.assert_called()


async def test_button_and_service_switch_image(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    await _setup(hass, config_entry)
    fav = _entity_id(hass, "image", "immichhomeassistant_favorite_image")
    first = hass.states.get(fav).attributes["current_asset_id"]

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: _entity_id(hass, "button", "immichhomeassistant_favorite_image_next")},
        blocking=True,
    )
    second = hass.states.get(fav).attributes["current_asset_id"]
    assert second != first

    # Service via de originele entity werkt door op de bron.
    await hass.services.async_call(
        DOMAIN,
        "next_image",
        {ATTR_ENTITY_ID: _entity_id(hass, "image", "immichhomeassistant_favorite_image_original")},
        blocking=True,
    )
    assert hass.states.get(fav).attributes["current_asset_id"] == first
    assert hass.states.get(fav).attributes["refresh_counter"] == 3


async def test_switch_and_number_persist_options(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    await _setup(hass, config_entry)
    fav = _entity_id(hass, "image", "immichhomeassistant_favorite_image")

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: _entity_id(hass, "switch", "immichhomeassistant_shuffle_mode")},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: _entity_id(hass, "number", "immichhomeassistant_refresh_interval"),
            "value": 60,
        },
        blocking=True,
    )

    assert config_entry.options[CONF_SHUFFLE_MODE] is True
    assert config_entry.options[CONF_REFRESH_INTERVAL] == 60
    attributes = hass.states.get(fav).attributes
    assert attributes["shuffle_mode"] is True
    assert attributes["refresh_interval"] == 60


async def test_original_falls_back_for_heic(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    mock_hub.list_favorite_images.return_value = [
        make_asset("heic", originalMimeType="image/heic")
    ]
    await _setup(hass, config_entry)
    data = config_entry.runtime_data
    original = data.entities["immichhomeassistant_favorite_image"].original_entity

    assert await original.async_image() == b"fullsize"
    mock_hub.download_asset.assert_not_called()


async def test_tag_filter_uses_server_side_search(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=config_entry.unique_id,
        data=dict(config_entry.data),
        options={**config_entry.options, CONF_TAG_FILTER: "Strand, zee"},
    )
    mock_hub.list_tags.return_value = [
        {"id": "t1", "name": "Strand", "value": "Vakantie/Strand"},
        {"id": "t2", "name": "Bergen", "value": "Bergen"},
    ]
    mock_hub.list_tagged_images.return_value = [make_asset("alb-1"), make_asset("x")]
    mock_hub.list_album_images.return_value = [make_asset("alb-1"), make_asset("alb-2")]
    await _setup(hass, config_entry)

    album = config_entry.runtime_data.entities["immichhomeassistant_album_album-1"]
    assert [a["id"] for a in album._asset_list] == ["alb-1"]
    mock_hub.list_tagged_images.assert_any_call("t1", favorites_only=True)
    mock_hub.list_tagged_images.assert_any_call("t1")
    mock_hub.get_asset_info.assert_not_called()


async def test_stale_album_entities_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AsyncMock
) -> None:
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "image", DOMAIN, "immichhomeassistant_album_gone", config_entry=config_entry
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None


def test_selection_respects_no_repeat_window(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={"no_repeat_window": 3})
    entry.runtime_data = AsyncMock()
    from custom_components.immichhomeassistant.models import ImageSource, SourceKind

    entity = ImmichHomeAssistantFavoriteImage(hass, entry, ImageSource(SourceKind.FAVORITES))
    entity._asset_list = [{"id": str(i)} for i in range(5)]

    for shuffle in (False, True):
        entity._shuffle_mode = shuffle
        entity._recent_asset_ids.clear()
        entity._current_asset = None
        seen: list[str] = []
        for _ in range(50):
            asset = entity._select_next_asset()
            assert asset["id"] not in list(entity._recent_asset_ids)
            entity._recent_asset_ids.append(asset["id"])
            entity._current_asset = asset
            seen.append(asset["id"])
        assert set(seen) == {str(i) for i in range(5)}


def test_single_asset_is_repeated(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.runtime_data = AsyncMock()
    from custom_components.immichhomeassistant.models import ImageSource, SourceKind

    entity = ImmichHomeAssistantFavoriteImage(hass, entry, ImageSource(SourceKind.FAVORITES))
    entity._asset_list = [{"id": "only"}]
    entity._current_asset = {"id": "only"}
    entity._recent_asset_ids.append("only")
    assert entity._select_next_asset()["id"] == "only"


def test_helpers() -> None:
    assert parse_tag_filter(" Strand, ,ZEE ") == {"strand", "zee"}
    meta = asset_metadata(
        make_asset("a", people=[{"name": "Anna"}, {"name": ""}], exifInfo={"description": "Hoi"})
    )
    assert meta["people"] == ["Anna"]
    assert meta["description"] == "Hoi"
    assert meta["city"] is None
    assert asset_metadata(None)["photo_date"] is None
