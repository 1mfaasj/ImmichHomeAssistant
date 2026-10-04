from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
import random
import secrets
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

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
    ID_LIST_REFRESH_INTERVAL_SECONDS,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
)
from .hub import ApiError, CannotConnect, ImmichHomeAssistantHub, InvalidAuth
from . import ENTITY_STORE, ImmichConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Stel de Immich image-entities in."""
    hub = config_entry.runtime_data

    entities: list[BaseImmichHomeAssistantImage] = [
        ImmichHomeAssistantFavoriteImage(hass, config_entry, hub)
    ]

    watched_album_ids = config_entry.options.get(CONF_WATCHED_ALBUMS, [])

    if watched_album_ids:
        try:
            albums = await hub.list_all_albums()

            album_map = {
                album["id"]: album["albumName"]
                for album in albums
                if album.get("id") and album.get("albumName")
            }

            for album_id in watched_album_ids:
                if album_name := album_map.get(album_id):
                    entities.append(
                        ImmichHomeAssistantAlbumImage(
                            hass,
                            config_entry,
                            hub,
                            album_id,
                            album_name,
                        )
                    )

        except (CannotConnect, InvalidAuth, ApiError) as error:
            _LOGGER.warning(
                "Immich-albums konden niet worden geladen: %s",
                error,
            )

    hass.data.setdefault(ENTITY_STORE, {})[config_entry.entry_id] = entities
    async_add_entities(entities)


class BaseImmichHomeAssistantImage(ImageEntity):
    """Basisklasse voor een Immich-afbeelding."""

    _attr_should_poll = False
    _attr_content_type = "image/jpeg"
    _attr_available = False

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ImmichConfigEntry,
        hub: ImmichHomeAssistantHub,
        name: str,
        unique_id: str,
    ) -> None:
        ImageEntity.__init__(self, hass)

        self.config_entry = config_entry
        self.hub = hub

        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_image_last_updated = None

        self.access_tokens = deque([secrets.token_hex(32)], maxlen=2)

        options = config_entry.options

        self._refresh_interval = int(
            options.get(
                CONF_REFRESH_INTERVAL,
                DEFAULT_REFRESH_INTERVAL,
            )
        )

        self._no_repeat_window = int(
            options.get(
                CONF_NO_REPEAT_WINDOW,
                DEFAULT_NO_REPEAT_WINDOW,
            )
        )

        self._tag_filter = self._parse_tag_filter(
            options.get(
                CONF_TAG_FILTER,
                DEFAULT_TAG_FILTER,
            )
        )

        self._shuffle_mode = bool(
            options.get(
                CONF_SHUFFLE_MODE,
                DEFAULT_SHUFFLE_MODE,
            )
        )

        self._random_speed = bool(
            options.get(
                CONF_RANDOM_SPEED,
                DEFAULT_RANDOM_SPEED,
            )
        )

        self._current_asset_id: str | None = None

        # Datum/tijd van de huidige foto zoals bekend bij Immich.
        self._current_photo_date: datetime | None = None

        self._current_image_bytes: bytes | None = None

        self._last_asset_ids_refresh: datetime | None = None
        self._last_successful_refresh: datetime | None = None
        self._last_error: str | None = None

        self._asset_list: list[dict[str, Any]] = []

        self._recent_asset_ids: deque[str] = deque(
            maxlen=max(self._no_repeat_window, 1)
        )

        self._shuffle_queue: list[dict[str, Any]] = []

        self._refresh_counter = 0
        self._unsub_refresh = None

    @staticmethod
    def _parse_tag_filter(value: str | None) -> set[str]:
        if not value:
            return set()

        return {
            item.strip().casefold()
            for item in value.split(",")
            if item.strip()
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        await self._async_refresh(force_asset_list=True)

        self._schedule_next_refresh()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None

        await super().async_will_remove_from_hass()

    def _schedule_next_refresh(self) -> None:
        if self._unsub_refresh:
            self._unsub_refresh()

        self._unsub_refresh = async_call_later(
            self.hass,
            self._next_delay_seconds(),
            self._handle_refresh,
        )

    def _next_delay_seconds(self) -> int:
        base = min(
            MAX_REFRESH_INTERVAL,
            max(
                MIN_REFRESH_INTERVAL,
                self._refresh_interval,
            ),
        )

        if not self._random_speed:
            return base

        return random.randint(
            max(MIN_REFRESH_INTERVAL, base // 2),
            max(
                MIN_REFRESH_INTERVAL,
                int(base * 1.5),
            ),
        )

    async def _handle_refresh(self, _now) -> None:
        try:
            await self._async_refresh()
        finally:
            self._schedule_next_refresh()

    async def _async_get_asset_list(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _ensure_asset_list(self, force: bool = False) -> None:
        now = datetime.now(UTC)

        expired = (
            self._last_asset_ids_refresh is None
            or (
                now - self._last_asset_ids_refresh
            ).total_seconds()
            >= ID_LIST_REFRESH_INTERVAL_SECONDS
        )

        if not force and not expired:
            return

        assets = await self._apply_tag_filter(
            await self._async_get_asset_list()
        )

        self._asset_list = [
            asset
            for asset in assets
            if asset.get("id")
        ]

        self._shuffle_queue.clear()
        self._last_asset_ids_refresh = now

    async def _apply_tag_filter(
        self,
        assets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self._tag_filter:
            return assets

        filtered = []

        for asset in assets:
            tag_names = self._extract_tags(
                asset.get("tags")
            )

            if not tag_names:
                try:
                    details = await self.hub.get_asset_info(
                        asset["id"]
                    )

                    tag_names = self._extract_tags(
                        details.get("tags")
                    )

                except (
                    CannotConnect,
                    InvalidAuth,
                    ApiError,
                    KeyError,
                ):
                    continue

            if self._tag_filter.intersection(tag_names):
                filtered.append(asset)

        return filtered

    @staticmethod
    def _extract_tags(raw_tags: Any) -> set[str]:
        result: set[str] = set()

        if not isinstance(raw_tags, list):
            return result

        for tag in raw_tags:
            if isinstance(tag, str):
                result.add(tag.casefold())

            elif isinstance(tag, dict):
                if value := tag.get("value") or tag.get("name"):
                    result.add(str(value).casefold())

        return result

    def _candidates(self) -> list[dict[str, Any]]:
        candidates = [
            asset
            for asset in self._asset_list
            if asset.get("id") != self._current_asset_id
            and asset.get("id") not in self._recent_asset_ids
        ]

        if not candidates:
            candidates = [
                asset
                for asset in self._asset_list
                if asset.get("id") != self._current_asset_id
            ]

        return candidates or self._asset_list[:]

    def _select_next_asset(self) -> dict[str, Any] | None:
        if not self._asset_list:
            return None

        if not self._shuffle_mode:
            return random.choice(self._candidates())

        while self._shuffle_queue:
            asset = self._shuffle_queue.pop()

            if asset in self._candidates():
                return asset

        self._shuffle_queue = self._candidates()
        random.shuffle(self._shuffle_queue)

        return (
            self._shuffle_queue.pop()
            if self._shuffle_queue
            else None
        )

    async def _async_refresh(
        self,
        force_asset_list: bool = False,
    ) -> None:
        try:
            await self._ensure_asset_list(
                force=force_asset_list
            )

            asset = self._select_next_asset()

            if not asset:
                raise ApiError(
                    "Geen afbeeldingen beschikbaar"
                )

            asset_id = asset["id"]

            try:
                image_bytes = (
                    await self.hub.download_asset_thumbnail(
                        asset_id
                    )
                )

            except (CannotConnect, ApiError):
                image_bytes = (
                    await self.hub.download_asset(
                        asset_id
                    )
                )

            self._current_asset_id = asset_id

            # Reset de vorige datum.
            self._current_photo_date = None

            # Haal de volledige assetinformatie op uit Immich.
            #
            # fileCreatedAt is de datum/tijd die Immich
            # voor dit asset beschikbaar stelt.
            try:
                asset_info = (
                    await self.hub.get_asset_info(
                        asset_id
                    )
                )

                photo_date = asset_info.get(
                    "fileCreatedAt"
                )

                if photo_date:
                    self._current_photo_date = (
                        datetime.fromisoformat(
                            str(photo_date).replace(
                                "Z",
                                "+00:00",
                            )
                        )
                    )

            except (
                CannotConnect,
                InvalidAuth,
                ApiError,
                KeyError,
                ValueError,
            ) as error:
                _LOGGER.warning(
                    "Datum/tijd van Immich-foto %s "
                    "kon niet worden opgehaald: %s",
                    asset_id,
                    error,
                )

            self._current_image_bytes = image_bytes

            self._recent_asset_ids.append(
                asset_id
            )

            self._refresh_counter += 1

            self._last_successful_refresh = (
                datetime.now(UTC)
            )

            self._last_error = None
            self._attr_available = True

            self.access_tokens.append(
                secrets.token_hex(32)
            )

            self._attr_image_last_updated = (
                self._last_successful_refresh
            )

        except InvalidAuth as error:
            self._last_error = str(error)

            self._attr_available = (
                self._current_image_bytes is not None
            )

            self.config_entry.async_start_reauth(
                self.hass
            )

            _LOGGER.error(
                "Authenticatie met Immich mislukt voor %s",
                self.name,
            )

        except (
            CannotConnect,
            ApiError,
            KeyError,
            ValueError,
        ) as error:
            self._last_error = str(error)

            self._attr_available = (
                self._current_image_bytes is not None
            )

            _LOGGER.warning(
                "Verversen van %s mislukt: %s",
                self.name,
                error,
            )

        finally:
            self.async_write_ha_state()

    async def async_force_next_image(self) -> None:
        await self._async_refresh()
        self._schedule_next_refresh()

    async def async_set_shuffle_mode(
        self,
        enabled: bool,
    ) -> None:
        self._shuffle_mode = bool(enabled)
        self._shuffle_queue.clear()

        self.async_write_ha_state()

    async def async_set_random_speed(
        self,
        enabled: bool,
    ) -> None:
        self._random_speed = bool(enabled)

        self._schedule_next_refresh()

        self.async_write_ha_state()

    async def async_set_refresh_interval(
        self,
        seconds: int,
    ) -> None:
        self._refresh_interval = min(
            MAX_REFRESH_INTERVAL,
            max(
                MIN_REFRESH_INTERVAL,
                int(seconds),
            ),
        )

        self._schedule_next_refresh()

        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return self._current_image_bytes

    @property
    def extra_state_attributes(
        self,
    ) -> dict[str, Any]:
        return {
            "refresh_interval": self._refresh_interval,
            "no_repeat_window": self._no_repeat_window,
            "tag_filter": sorted(self._tag_filter),
            "shuffle_mode": self._shuffle_mode,
            "random_speed": self._random_speed,
            "refresh_counter": self._refresh_counter,
            "current_asset_id": self._current_asset_id,

            # Datum en tijd van de foto volgens Immich.
            "photo_date": self._current_photo_date,

            "available_assets": len(self._asset_list),
            "last_successful_refresh": self._last_successful_refresh,
            "last_error": self._last_error,
        }


class ImmichHomeAssistantFavoriteImage(
    BaseImmichHomeAssistantImage
):
    def __init__(
        self,
        hass,
        config_entry,
        hub,
    ) -> None:
        super().__init__(
            hass,
            config_entry,
            hub,
            "Immich Favorieten",
            "immichhomeassistant_favorite_image",
        )

    async def _async_get_asset_list(
        self,
    ) -> list[dict[str, Any]]:
        return await self.hub.list_favorite_images()


class ImmichHomeAssistantAlbumImage(
    BaseImmichHomeAssistantImage
):
    def __init__(
        self,
        hass,
        config_entry,
        hub,
        album_id: str,
        album_name: str,
    ) -> None:
        self.album_id = album_id
        self.album_name = album_name

        super().__init__(
            hass,
            config_entry,
            hub,
            f"Immich {album_name}",
            f"immichhomeassistant_album_{album_id}",
        )

    async def _async_get_asset_list(
        self,
    ) -> list[dict[str, Any]]:
        return await self.hub.list_album_images(
            self.album_id
        )

    @property
    def extra_state_attributes(
        self,
    ) -> dict[str, Any]:
        return {
            **super().extra_state_attributes,
            "album_id": self.album_id,
            "album_name": self.album_name,
        }
