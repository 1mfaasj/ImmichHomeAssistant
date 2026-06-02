"""Hub for the Immich integration."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
_HEADER_API_KEY = "x-api-key"
_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg"}


class ImmichHub:
    """Immich API hub."""

    def __init__(self, hass: HomeAssistant, host: str, api_key: str) -> None:
        self.hass = hass
        self.host = host.rstrip("/")
        self.api_key = api_key
        self._session = async_get_clientsession(hass)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", _HEADER_API_KEY: self.api_key}

    async def _get_json(self, path: str) -> dict | list:
        url = urljoin(f"{self.host}/", path.lstrip("/"))
        try:
            async with self._session.get(url, headers=self._headers) as response:
                if response.status != 200:
                    raw_result = await response.text()
                    _LOGGER.error("Error from API: body=%s", raw_result)
                    raise ApiError()
                return await response.json()
        except ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def _post_json(self, path: str, data: dict) -> dict | list:
        url = urljoin(f"{self.host}/", path.lstrip("/"))
        try:
            async with self._session.post(url, headers=self._headers, data=data) as response:
                if response.status != 200:
                    raw_result = await response.text()
                    _LOGGER.error("Error from API: body=%s", raw_result)
                    raise ApiError()
                return await response.json()
        except ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def authenticate(self) -> bool:
        url = urljoin(f"{self.host}/", "api/auth/validateToken")
        try:
            async with self._session.post(url, headers=self._headers) as response:
                if response.status != 200:
                    raw_result = await response.text()
                    _LOGGER.error("Error from API: body=%s", raw_result)
                    return False
                auth_result = await response.json()
                return bool(auth_result.get("authStatus"))
        except ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def get_my_user_info(self) -> dict:
        result = await self._get_json("/api/users/me")
        if not isinstance(result, dict):
            raise ApiError()
        return result

    async def get_asset_info(self, asset_id: str) -> dict | None:
        result = await self._get_json(f"/api/assets/{asset_id}")
        if not isinstance(result, dict):
            raise ApiError()
        return result

    async def download_asset(self, asset_id: str) -> bytes | None:
        url = urljoin(f"{self.host}/", f"api/assets/{asset_id}/original")
        try:
            async with self._session.get(url, headers={_HEADER_API_KEY: self.api_key}) as response:
                if response.status != 200:
                    _LOGGER.error("Error from API: status=%d", response.status)
                    return None
                if response.content_type not in _ALLOWED_MIME_TYPES:
                    _LOGGER.error("MIME type is not supported: %s", response.content_type)
                    return None
                return await response.read()
        except ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def list_favorite_images(self) -> list[dict]:
        result = await self._post_json("/api/search/metadata", {"isFavorite": "true"})
        if not isinstance(result, dict):
            raise ApiError()
        assets = result.get("assets", {}).get("items", [])
        return [asset for asset in assets if asset.get("type") == "IMAGE"]

    async def list_all_albums(self) -> list[dict]:
        result = await self._get_json("/api/albums")
        if not isinstance(result, list):
            raise ApiError()
        return result

    async def list_album_images(self, album_id: str) -> list[dict]:
        result = await self._get_json(f"/api/albums/{album_id}")
        if not isinstance(result, dict):
            raise ApiError()
        assets = result.get("assets", [])
        return [asset for asset in assets if asset.get("type") == "IMAGE"]


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class ApiError(HomeAssistantError):
    """Error to indicate that the API returned an error."""
