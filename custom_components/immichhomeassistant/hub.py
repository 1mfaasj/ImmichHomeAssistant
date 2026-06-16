from __future__ import annotations

import logging
from urllib.parse import urljoin

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
_HEADER_API_KEY = "x-api-key"
_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}

class ImmichHomeAssistantHub:
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
                    raise ApiError(await response.text())
                return await response.json()
        except ClientError as exception:
            raise CannotConnect from exception

    async def _post_json(self, path: str, data: dict) -> dict | list:
        url = urljoin(f"{self.host}/", path.lstrip("/"))
        try:
            # Immich v3 validates request bodies strictly. Use JSON here so
            # booleans stay booleans instead of becoming form strings.
            async with self._session.post(url, headers=self._headers, json=data) as response:
                if response.status != 200:
                    raise ApiError(await response.text())
                return await response.json()
        except ClientError as exception:
            raise CannotConnect from exception

    async def authenticate(self) -> bool:
        url = urljoin(f"{self.host}/", "api/auth/validateToken")
        try:
            async with self._session.post(url, headers=self._headers) as response:
                if response.status != 200:
                    return False
                data = await response.json()
                return bool(data.get("authStatus"))
        except ClientError as exception:
            raise CannotConnect from exception

    async def get_my_user_info(self) -> dict:
        result = await self._get_json("/api/users/me")
        if not isinstance(result, dict):
            raise ApiError("Unexpected response")
        return result

    async def get_asset_info(self, asset_id: str) -> dict:
        result = await self._get_json(f"/api/assets/{asset_id}")
        if not isinstance(result, dict):
            raise ApiError("Unexpected response")
        return result

    async def _download_binary(self, path: str, params: dict | None = None) -> bytes | None:
        url = urljoin(f"{self.host}/", path.lstrip("/"))
        try:
            async with self._session.get(url, headers={_HEADER_API_KEY: self.api_key}, params=params, allow_redirects=True) as response:
                if response.status != 200:
                    _LOGGER.error("Binary endpoint failed: %s status=%s", path, response.status)
                    return None
                if response.content_type not in _ALLOWED_MIME_TYPES:
                    _LOGGER.error("Unsupported MIME type: %s", response.content_type)
                    return None
                return await response.read()
        except ClientError as exception:
            _LOGGER.error("Binary download failed on %s: %s", path, exception)
            return None

    async def download_asset_thumbnail(self, asset_id: str) -> bytes | None:
        return await self._download_binary(f"api/assets/{asset_id}/thumbnail", {"edited": "true"})

    async def download_asset(self, asset_id: str) -> bytes | None:
        return await self._download_binary(f"api/assets/{asset_id}/original")

    async def list_favorite_images(self) -> list[dict]:
        result = await self._post_json("/api/search/metadata", {"isFavorite": True})
        if not isinstance(result, dict):
            raise ApiError("Unexpected response")
        items = result.get("assets", {}).get("items", [])
        return [asset for asset in items if asset.get("type") == "IMAGE"]

    async def list_all_albums(self) -> list[dict]:
        result = await self._get_json("/api/albums")
        if not isinstance(result, list):
            raise ApiError("Unexpected response")
        return result

    async def list_album_images(self, album_id: str) -> list[dict]:
        result = await self._get_json(f"/api/albums/{album_id}")
        if not isinstance(result, dict):
            raise ApiError("Unexpected response")
        items = result.get("assets", [])
        return [asset for asset in items if asset.get("type") == "IMAGE"]

class CannotConnect(HomeAssistantError):
    pass

class InvalidAuth(HomeAssistantError):
    pass

class ApiError(HomeAssistantError):
    pass
