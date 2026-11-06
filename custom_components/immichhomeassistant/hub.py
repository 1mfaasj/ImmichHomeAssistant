from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientResponse, ContentTypeError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import MAX_SEARCH_PAGES, REQUEST_TIMEOUT_SECONDS, SEARCH_PAGE_SIZE

_LOGGER = logging.getLogger(__name__)
_HEADER_API_KEY = "x-api-key"

# MIME-types die een browser direct kan tonen.
WEB_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
)


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

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.request(
                    method,
                    self._url(path),
                    headers=self._headers,
                    json=json,
                    params=params,
                ) as response:
                    await self._raise_for_status(response)
                    result = await response.json()
        except InvalidAuth:
            raise
        except ApiError as error:
            self._record_error(error)
            raise
        except (TimeoutError, ClientError, ContentTypeError, ValueError) as error:
            self._record_error(error)
            raise CannotConnect(f"Immich is niet bereikbaar: {error}") from error
        self._record_success()
        return result

    async def authenticate(self) -> bool:
        """Controleer de ingestelde API-sleutel."""
        data = await self._request_json("POST", "api/auth/validateToken")
        if not isinstance(data, dict) or not data.get("authStatus"):
            raise InvalidAuth("Ongeldige Immich API-sleutel")
        return True

    async def get_my_user_info(self) -> dict[str, Any]:
        result = await self._request_json("GET", "api/users/me")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte response van /api/users/me")
        return result

    async def get_asset_info(self, asset_id: str) -> dict[str, Any]:
        result = await self._request_json("GET", f"api/assets/{asset_id}")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte assetresponse")
        return result

    # ------------------------------------------------------------------ zoeken

    async def search_images(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Doorzoek alle pagina's van /api/search/metadata naar foto's."""
        items: list[dict[str, Any]] = []
        page: int | None = 1
        pages = 0
        while page is not None:
            pages += 1
            if pages > MAX_SEARCH_PAGES:
                _LOGGER.warning(
                    "Zoekopdracht afgebroken na %s pagina's (%s foto's)",
                    MAX_SEARCH_PAGES,
                    len(items),
                )
                break
            body = {
                "page": page,
                "size": SEARCH_PAGE_SIZE,
                "type": "IMAGE",
                "withExif": True,
                "withPeople": True,
                **filters,
            }
            result = await self._request_json("POST", "api/search/metadata", json=body)
            if not isinstance(result, dict):
                raise ApiError("Onverwachte zoekresponse")
            assets = result.get("assets")
            if not isinstance(assets, dict):
                raise ApiError("Onverwachte zoekresponse")
            items.extend(
                item
                for item in assets.get("items", [])
                if isinstance(item, dict) and item.get("type") == "IMAGE"
            )
            next_page = assets.get("nextPage")
            try:
                page = int(next_page) if next_page else None
            except (TypeError, ValueError):
                page = None
        return items

    async def list_favorite_images(self) -> list[dict[str, Any]]:
        return await self.search_images({"isFavorite": True})

    async def list_tagged_images(
        self, tag_id: str, *, favorites_only: bool = False
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"tagIds": [tag_id]}
        if favorites_only:
            filters["isFavorite"] = True
        return await self.search_images(filters)

    async def list_tags(self) -> list[dict[str, Any]]:
        result = await self._request_json("GET", "api/tags")
        if not isinstance(result, list):
            raise ApiError("Onverwachte tagresponse")
        return [tag for tag in result if isinstance(tag, dict)]

    async def list_all_albums(self) -> list[dict[str, Any]]:
        result = await self._request_json("GET", "api/albums")
        if not isinstance(result, list):
            raise ApiError("Onverwachte albumresponse")
        return [album for album in result if isinstance(album, dict)]

    async def list_album_images(self, album_id: str) -> list[dict[str, Any]]:
        result = await self._request_json("GET", f"api/albums/{album_id}")
        if not isinstance(result, dict):
            raise ApiError("Onverwachte albumresponse")
        items = result.get("assets", [])
        return [
            item
            for item in items
            if isinstance(item, dict) and item.get("type") == "IMAGE"
        ]

    async def list_on_this_day_images(
        self, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Foto's uit de 'Op deze dag'-herinneringen van vandaag."""
        now = now or datetime.now(UTC)
        result = await self._request_json(
            "GET",
            "api/memories",
            params={
                "type": "on_this_day",
                "for": now.isoformat(),
                "isTrashed": "false",
            },
        )
        if not isinstance(result, list):
            raise ApiError("Onverwachte herinneringenresponse")

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for memory in result:
            if not isinstance(memory, dict) or not _memory_is_current(memory, now):
                continue
            for asset in memory.get("assets", []):
                if (
                    isinstance(asset, dict)
                    and asset.get("type") == "IMAGE"
                    and asset.get("id")
                    and asset["id"] not in seen
                    and not asset.get("isTrashed")
                ):
                    seen.add(asset["id"])
                    items.append(asset)
        return items

    # --------------------------------------------------------------- download

    async def _download_binary(
        self, path: str, params: dict[str, str] | None = None
    ) -> tuple[bytes, str]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(
                    self._url(path),
                    headers={_HEADER_API_KEY: self.api_key},
                    params=params,
                    allow_redirects=True,
                ) as response:
                    await self._raise_for_status(response)
                    content_type = response.content_type
                    if content_type not in WEB_IMAGE_MIME_TYPES:
                        raise ApiError(
                            f"Niet-ondersteund MIME-type: {content_type}"
                        )
                    image = await response.read()
        except InvalidAuth:
            raise
        except ApiError as error:
            self._record_error(error)
            raise
        except (TimeoutError, ClientError) as error:
            self._record_error(error)
            raise CannotConnect(
                f"Afbeelding kon niet worden opgehaald: {error}"
            ) from error
        if not image:
            raise ApiError("Immich gaf een lege afbeelding terug")
        self._record_success()
        return image, content_type

    async def download_asset_preview(self, asset_id: str) -> tuple[bytes, str]:
        """Middelgrote versie (ca. 1440 px), geschikt voor dashboards."""
        return await self._download_binary(
            f"api/assets/{asset_id}/thumbnail", {"size": "preview", "edited": "true"}
        )

    async def download_asset_fullsize(self, asset_id: str) -> tuple[bytes, str]:
        """Volledige resolutie in een browservriendelijk formaat."""
        return await self._download_binary(
            f"api/assets/{asset_id}/thumbnail", {"size": "fullsize", "edited": "true"}
        )

    async def download_asset(self, asset_id: str) -> tuple[bytes, str]:
        return await self._download_binary(f"api/assets/{asset_id}/original")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _memory_is_current(memory: dict[str, Any], now: datetime) -> bool:
    if memory.get("type", "on_this_day") != "on_this_day":
        return False
    if memory.get("isTrashed") or memory.get("deletedAt"):
        return False
    show_at = _parse_datetime(memory.get("showAt"))
    hide_at = _parse_datetime(memory.get("hideAt"))
    if show_at or hide_at:
        return (show_at is None or show_at <= now) and (
            hide_at is None or now < hide_at
        )
    memory_at = _parse_datetime(memory.get("memoryAt"))
    if memory_at is None:
        return True
    return (memory_at.month, memory_at.day) == (now.month, now.day)


class CannotConnect(HomeAssistantError):
    """Immich kan tijdelijk niet worden bereikt."""


class InvalidAuth(HomeAssistantError):
    """De API-sleutel is ongeldig."""


class ApiError(HomeAssistantError):
    """Immich gaf een ongeldige of onverwachte response terug."""
