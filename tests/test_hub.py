"""Tests voor de Immich API-client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.immichhomeassistant.hub import (
    ApiError,
    ImmichHomeAssistantHub,
    InvalidAuth,
)

from .conftest import HOST, make_asset


async def test_search_follows_all_pages(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    pages = iter(
        [
            {"assets": {"items": [make_asset("a"), make_asset("b")], "nextPage": "2"}},
            {"assets": {"items": [make_asset("c")], "nextPage": None}},
        ]
    )

    async def handler(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        return AiohttpClientMockResponse(method, url, json=next(pages))

    aioclient_mock.post(f"{HOST}/api/search/metadata", side_effect=handler)
    hub = ImmichHomeAssistantHub(hass, HOST, "key")

    assets = await hub.list_favorite_images()

    assert [a["id"] for a in assets] == ["a", "b", "c"]
    assert aioclient_mock.call_count == 2
    first_body = aioclient_mock.mock_calls[0][2]
    assert first_body["isFavorite"] is True
    assert first_body["page"] == 1
    assert aioclient_mock.mock_calls[1][2]["page"] == 2


async def test_auth_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", status=401)
    hub = ImmichHomeAssistantHub(hass, HOST, "key")
    with pytest.raises(InvalidAuth):
        await hub.authenticate()


async def test_preview_returns_content_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{HOST}/api/assets/x/thumbnail",
        content=b"img",
        headers={"Content-Type": "image/webp"},
    )
    hub = ImmichHomeAssistantHub(hass, HOST, "key")

    assert await hub.download_asset_preview("x") == (b"img", "image/webp")
    assert aioclient_mock.mock_calls[0][1].query["size"] == "preview"


async def test_heic_original_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{HOST}/api/assets/x/original",
        content=b"heic",
        headers={"Content-Type": "image/heic"},
    )
    hub = ImmichHomeAssistantHub(hass, HOST, "key")
    with pytest.raises(ApiError):
        await hub.download_asset("x")
