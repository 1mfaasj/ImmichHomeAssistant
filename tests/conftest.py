"""Gedeelde fixtures voor de tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immichhomeassistant.const import CONF_WATCHED_ALBUMS, DOMAIN

HOST = "http://immich.local:2283"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Laat Home Assistant de custom integratie laden."""


def make_asset(asset_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": asset_id,
        "type": "IMAGE",
        "originalMimeType": "image/jpeg",
        "originalFileName": f"{asset_id}.jpg",
        "fileCreatedAt": "2020-06-01T12:00:00.000Z",
        "exifInfo": {"city": "Utrecht", "country": "Nederland"},
        **extra,
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="John @ immich.local",
        unique_id=HOST,
        data={"host": HOST, "api_key": "secret"},
        options={CONF_WATCHED_ALBUMS: ["album-1"]},
    )


@pytest.fixture
def mock_hub() -> Generator[AsyncMock]:
    """Vervang alle netwerkcalls van de hub."""
    with patch(
        "custom_components.immichhomeassistant.ImmichHomeAssistantHub",
        autospec=True,
    ) as hub_cls:
        hub = hub_cls.return_value
        hub.host = HOST
        hub.last_success = None
        hub.last_error = None
        hub.authenticate.return_value = True
        hub.list_all_albums.return_value = [{"id": "album-1", "albumName": "Vakantie"}]
        hub.list_favorite_images.return_value = [make_asset("fav-1"), make_asset("fav-2")]
        hub.list_album_images.return_value = [make_asset("alb-1")]
        hub.download_asset_preview.return_value = (b"preview", "image/webp")
        hub.download_asset_fullsize.return_value = (b"fullsize", "image/jpeg")
        hub.download_asset.return_value = (b"original", "image/jpeg")
        yield hub
