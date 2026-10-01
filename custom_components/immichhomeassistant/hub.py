from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientResponse, ContentTypeError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import REQUEST_TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)
_HEADER_API_KEY = "x-api-key"
_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ImmichHomeAssistantHub:
    """Client voor communicatie met de Immich API."""

    def __init__(self, hass: HomeAssistant, host: str, api_key: str) -> None:
        self.hass = hass
        self.host = host.rstrip("/")
        self.api_key = api_key
        self._session = async_get_clientsession(hass)
        self.last_success: datetime | None = None
        self.last_error: str | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", _HEADER_API_KEY: self.api_key}

    def _url(self, path: str) -> str:
        return urljoin(f"{self.host}/", path.lstrip("/"))

    def _record_success(self) -> None:
        self.last_success = datetime.now(UTC)
        self.last_error = None

    def _record_error(self, error: Exception | str) -> None:
        self.last_error = str(error)

    async def _raise_for_status(self, response: ClientResponse) -> None:
        if response.status in (401, 403):
            raise InvalidAuth("Immich heeft de API-sleutel geweigerd")
        if response.status < 200 or response.status >= 300:
            body = (await response.text())[:500]
            raise ApiError(f"Immich HTTP {response.status}: {body}")

    async def _get_json(self, path: str) -> dict[str, Any] | list[Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(
                    self._url(path), headers=self._headers
                ) as response:
                    await self._raise_for_status(response)
                    result = await response.json()
            self._record_success()
            return result
        except InvalidAuth:
            raise
        except (TimeoutError, ClientError, ContentTypeError) as error:
            self._record_error(error)
            raise CannotConnect(f"Immich is niet bereikbaar: {error}") from error

    async def _post_json(
        self, path: str, data: dict[str, Any]
    ) -> dict[str, Any] | list[Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.post(
                    self._url(path), headers=self._headers, json=data
                ) as response:
                    await self._raise_for_status(response)
                    result = await response.json()
            self._record_success()
            return result
        except InvalidAuth:
            raise
        except (TimeoutError, ClientError, ContentTypeError) as error:
            self._record_error(error)
            raise CannotConnect(f"Immich is niet bereikbaar: {error}") from error

    async def authenticate(self) -> bool:
        """Controleer de ingestelde API-sleutel."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.post(
                    self._url("api/auth/validateToken"), headers=self._headers
                ) as response:
                    if response.status in (401, 403):
                        raise InvalidAuth("Ongeldige Immich API-sleutel")
                    await self._raise_for_status(response)
                    data = await response.json()
            authenticated = bool(data.get("authStatus"))
            if not authenticated:
                raise InvalidAuth("Ongeldige Immich API-sleutel")
            self._record_success()
            return True
        except InvalidAuth:
            raise
        except (TimeoutError, ClientError, ContentTypeError) as error:
            self._record_error(error)
            raise CannotConnect(f"Immich is niet bereikbaar: {error}") from error

    async def get_my_user_info(self) -> dict[str, Any]:
        result = await self._get_json("api/users/me")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte response van /api/users/me")
        return result

    async def get_asset_info(self, asset_id: str) -> dict[str, Any]:
        result = await self._get_json(f"api/assets/{asset_id}")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte assetresponse")
        return result

    async def _download_binary(
        self, path: str, params: dict[str, str] | None = None
    ) -> bytes:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(
                    self._url(path),
                    headers={_HEADER_API_KEY: self.api_key},
                    params=params,
                    allow_redirects=True,
                ) as response:
                    await self._raise_for_status(response)
                    if response.content_type not in _ALLOWED_MIME_TYPES:
                        raise ApiError(
                            f"Niet-ondersteund MIME-type: {response.content_type}"
                        )
                    image = await response.read()
            if not image:
                raise ApiError("Immich gaf een lege afbeelding terug")
            self._record_success()
            return image
        except (InvalidAuth, ApiError):
            raise
        except (TimeoutError, ClientError) as error:
            self._record_error(error)
            raise CannotConnect(f"Afbeelding kon niet worden opgehaald: {error}") from error

    async def download_asset_thumbnail(self, asset_id: str) -> bytes:
        return await self._download_binary(
            f"api/assets/{asset_id}/thumbnail", {"edited": "true"}
        )

    async def download_asset(self, asset_id: str) -> bytes:
        return await self._download_binary(f"api/assets/{asset_id}/original")

    async def list_favorite_images(self) -> list[dict[str, Any]]:
        result = await self._post_json("api/search/metadata", {"isFavorite": True})
        if not isinstance(result, dict):
            raise ApiError("Onverwachte favorietenresponse")
        assets = result.get("assets", {})
        items = assets.get("items", []) if isinstance(assets, dict) else []
        return [item for item in items if item.get("type") == "IMAGE"]

    async def list_all_albums(self) -> list[dict[str, Any]]:
        result = await self._get_json("api/albums")
        if not isinstance(result, list):
            raise ApiError("Onverwachte albumresponse")
        return [album for album in result if isinstance(album, dict)]

    async def list_album_images(self, album_id: str) -> list[dict[str, Any]]:
        result = await self._get_json(f"api/albums/{album_id}")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte albumresponse")
        items = result.get("assets", [])
        return [item for item in items if item.get("type") == "IMAGE"]


class CannotConnect(HomeAssistantError):
    """Immich kan tijdelijk niet worden bereikt."""


class InvalidAuth(HomeAssistantError):
    """De API-sleutel is ongeldig."""


class ApiError(HomeAssistantError):
    """Immich gaf een ongeldige of onverwachte response terug."""
