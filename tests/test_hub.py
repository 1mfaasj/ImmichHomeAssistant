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


async def test_album_images_use_search(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        f"{HOST}/api/search/metadata",
        json={"assets": {"items": [make_asset("a")], "nextPage": None}},
    )
    hub = ImmichHomeAssistantHub(hass, HOST, "key")
    assets = await hub.list_album_images("album-1", tag_id="t1")
    assert [a["id"] for a in assets] == ["a"]
    body = aioclient_mock.mock_calls[0][2]
    assert body["albumIds"] == ["album-1"] and body["tagIds"] == ["t1"]


async def test_retry_on_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, monkeypatch
) -> None:
    from custom_components.immichhomeassistant import hub as hub_mod

    monkeypatch.setattr(hub_mod, "RETRY_DELAY_SECONDS", 0)
    calls = iter([503, 200])

    async def handler(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        status = next(calls)
        return AiohttpClientMockResponse(method, url, status=status, json={"id": "x"} if status == 200 else {"message": "bezig"})

    aioclient_mock.get(f"{HOST}/api/assets/x", side_effect=handler)
    hub = ImmichHomeAssistantHub(hass, HOST, "key")
    assert (await hub.get_asset_info("x"))["id"] == "x"
    assert aioclient_mock.call_count == 2


async def test_no_retry_on_client_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{HOST}/api/assets/x", status=404, json={"message": "weg"})
    hub = ImmichHomeAssistantHub(hass, HOST, "key")
    with pytest.raises(ApiError):
        await hub.get_asset_info("x")
    assert aioclient_mock.call_count == 1
