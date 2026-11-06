from __future__ import annotations

import asyncio
import logging
import random
import secrets
from collections import deque
from datetime import UTC, date, datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NO_REPEAT_WINDOW,
    CONF_RANDOM_SPEED,
    CONF_REFRESH_INTERVAL,
    CONF_SHUFFLE_MODE,
    CONF_TAG_FILTER,
    DEFAULT_NO_REPEAT_WINDOW,
    DEFAULT_RANDOM_SPEED,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_SHUFFLE_MODE,
    DEFAULT_TAG_FILTER,
    DOMAIN,
    ID_LIST_REFRESH_INTERVAL_SECONDS,
    MAX_REFRESH_INTERVAL,
    MEMORY_LIST_REFRESH_INTERVAL_SECONDS,
    MIN_REFRESH_INTERVAL,
    original_unique_id,
)
from .hub import (
    WEB_IMAGE_MIME_TYPES,
    ApiError,
    CannotConnect,
    ImmichHomeAssistantHub,
    InvalidAuth,
)
from .models import ImageSource, ImmichConfigEntry, SourceKind

_LOGGER = logging.getLogger(__name__)

SERVICE_NEXT_IMAGE = "next_image"
SERVICE_SET_SHUFFLE_MODE = "set_shuffle_mode"
SERVICE_SET_RANDOM_SPEED = "set_random_speed"
SERVICE_SET_REFRESH_INTERVAL = "set_refresh_interval"

_NO_IMAGES = "Geen afbeeldingen beschikbaar"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Stel de Immich image-entities in."""
    data = config_entry.runtime_data
    entities: list[ImageEntity] = []

    for source in data.sources:
        image = _create_source_entity(hass, config_entry, source)
        original = ImmichOriginalImage(hass, image)
        image.original_entity = original
        data.entities[source.unique_id] = image
        entities.extend([image, original])

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_NEXT_IMAGE, None, "async_force_next_image"
    )
    platform.async_register_entity_service(
        SERVICE_SET_SHUFFLE_MODE,
        {vol.Required("enabled"): cv.boolean},
        "async_set_shuffle_mode",
    )
    platform.async_register_entity_service(
        SERVICE_SET_RANDOM_SPEED,
        {vol.Required("enabled"): cv.boolean},
        "async_set_random_speed",
    )
    platform.async_register_entity_service(
        SERVICE_SET_REFRESH_INTERVAL,
        {
            vol.Required("seconds"): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL),
            )
        },
        "async_set_refresh_interval",
    )


def _create_source_entity(
    hass: HomeAssistant, entry: ImmichConfigEntry, source: ImageSource
) -> BaseImmichHomeAssistantImage:
    if source.kind is SourceKind.ALBUM:
        return ImmichHomeAssistantAlbumImage(hass, entry, source)
    if source.kind is SourceKind.ON_THIS_DAY:
        return ImmichOnThisDayImage(hass, entry, source)
    return ImmichHomeAssistantFavoriteImage(hass, entry, source)


def parse_tag_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().casefold() for item in value.split(",") if item.strip()}


def asset_metadata(asset: dict[str, Any] | None) -> dict[str, Any]:
    """Haal de dashboard-relevante metadata uit een Immich-asset."""
    if not asset:
        return {
            "photo_date": None,
            "city": None,
            "state": None,
            "country": None,
            "description": None,
            "people": [],
            "file_name": None,
        }

    exif = asset.get("exifInfo") or {}
    photo_date = None
    for raw in (asset.get("fileCreatedAt"), exif.get("dateTimeOriginal")):
        if not raw:
            continue
        try:
            photo_date = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            break
        except ValueError:
            continue

    people = [
        person["name"]
        for person in asset.get("people") or []
        if isinstance(person, dict) and person.get("name")
    ]

    return {
        "photo_date": photo_date,
        "city": exif.get("city") or None,
        "state": exif.get("state") or None,
        "country": exif.get("country") or None,
        "description": exif.get("description") or None,
        "people": people,
        "file_name": asset.get("originalFileName"),
    }


class BaseImmichHomeAssistantImage(ImageEntity):
    """Basisklasse voor een wisselende Immich-afbeelding."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"
    _attr_available = False

    _supports_tag_filter = True
    _asset_list_ttl = ID_LIST_REFRESH_INTERVAL_SECONDS

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ImmichConfigEntry,
        source: ImageSource,
    ) -> None:
        super().__init__(hass)

        self.config_entry = config_entry
        self.source = source
        self.hub: ImmichHomeAssistantHub = config_entry.runtime_data.hub

        self._attr_unique_id = source.unique_id
        self._attr_device_info = config_entry.runtime_data.device_info
        self._attr_image_last_updated = None

        options = config_entry.options
        self._refresh_interval = int(
            options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
        )
        self._no_repeat_window = int(
            options.get(CONF_NO_REPEAT_WINDOW, DEFAULT_NO_REPEAT_WINDOW)
        )
        self._tag_filter = (
            parse_tag_filter(options.get(CONF_TAG_FILTER, DEFAULT_TAG_FILTER))
            if self._supports_tag_filter
            else set()
        )
        self._shuffle_mode = bool(options.get(CONF_SHUFFLE_MODE, DEFAULT_SHUFFLE_MODE))
        self._random_speed = bool(options.get(CONF_RANDOM_SPEED, DEFAULT_RANDOM_SPEED))

        self._current_asset: dict[str, Any] | None = None
        self._current_image_bytes: bytes | None = None
        self._last_asset_list_refresh: datetime | None = None
        self._last_successful_refresh: datetime | None = None
        self._last_error: str | None = None
        self._asset_list: list[dict[str, Any]] = []
        self._recent_asset_ids: deque[str] = deque(maxlen=self._no_repeat_window)
        self._shuffle_queue: list[dict[str, Any]] = []
        self._refresh_counter = 0
        self._refresh_lock = asyncio.Lock()
        self._unsub_refresh = None
        self._removed = False

        self.original_entity: ImmichOriginalImage | None = None

    # ------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Niet wachten op Immich: dat zou het opstarten van HA vertragen.
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_initial_refresh(),
            name=f"{DOMAIN} eerste verversing {self.unique_id}",
        )

    async def _async_initial_refresh(self) -> None:
        await self._async_refresh(force_asset_list=True)
        self._schedule_next_refresh()

    async def async_will_remove_from_hass(self) -> None:
        self._removed = True
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        await super().async_will_remove_from_hass()

    def _schedule_next_refresh(self) -> None:
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None
        if self._removed:
            return
        self._unsub_refresh = async_call_later(
            self.hass, self._next_delay_seconds(), self._handle_refresh
        )

    def _next_delay_seconds(self) -> int:
        base = min(MAX_REFRESH_INTERVAL, max(MIN_REFRESH_INTERVAL, self._refresh_interval))
        if not self._random_speed:
            return base
        return random.randint(
            max(MIN_REFRESH_INTERVAL, base // 2),
            max(MIN_REFRESH_INTERVAL, int(base * 1.5)),
        )

    async def _handle_refresh(self, _now: datetime) -> None:
        self._unsub_refresh = None
        try:
            await self._async_refresh()
        finally:
            self._schedule_next_refresh()

    # ------------------------------------------------------------ assetlijst

    async def _async_fetch_assets(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _async_fetch_tagged_assets(
        self, tag_ids: list[str]
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _async_resolve_tag_ids(self) -> list[str]:
        tags = await self.hub.list_tags()
        tag_ids = [
            tag["id"]
            for tag in tags
            if tag.get("id")
            and {
                str(tag.get("name") or "").casefold(),
                str(tag.get("value") or "").casefold(),
            }
            & self._tag_filter
        ]
        if not tag_ids:
            _LOGGER.warning(
                "Geen van de tags %s bestaat in Immich", sorted(self._tag_filter)
            )
        return tag_ids

    async def _async_get_asset_list(self) -> list[dict[str, Any]]:
        if not self._tag_filter:
            return await self._async_fetch_assets()
        tag_ids = await self._async_resolve_tag_ids()
        if not tag_ids:
            return []
        return await self._async_fetch_tagged_assets(tag_ids)

    def _asset_list_expired(self, now: datetime) -> bool:
        return (
            self._last_asset_list_refresh is None
            or (now - self._last_asset_list_refresh).total_seconds()
            >= self._asset_list_ttl
        )

    async def _ensure_asset_list(self, force: bool = False) -> None:
        now = datetime.now(UTC)
        if not force and not self._asset_list_expired(now):
            return

        assets = await self._async_get_asset_list()
        seen: set[str] = set()
        self._asset_list = []
        for asset in assets:
            asset_id = asset.get("id")
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                self._asset_list.append(asset)
        self._shuffle_queue.clear()
        self._last_asset_list_refresh = now

    # -------------------------------------------------------------- selectie

    @property
    def _current_asset_id(self) -> str | None:
        return self._current_asset["id"] if self._current_asset else None

    def _candidates(self, excluded: set[str]) -> list[dict[str, Any]]:
        candidates = [a for a in self._asset_list if a["id"] not in excluded]
        if not candidates:
            current = self._current_asset_id
            candidates = [a for a in self._asset_list if a["id"] != current]
        return candidates or list(self._asset_list)

    def _select_next_asset(self) -> dict[str, Any] | None:
        if not self._asset_list:
            return None

        excluded = set(self._recent_asset_ids)
        if self._current_asset_id:
            excluded.add(self._current_asset_id)

        if not self._shuffle_mode:
            return random.choice(self._candidates(excluded))

        while self._shuffle_queue:
            asset = self._shuffle_queue.pop()
            if asset["id"] not in excluded:
                return asset

        self._shuffle_queue = self._candidates(excluded)
        random.shuffle(self._shuffle_queue)
        return self._shuffle_queue.pop() if self._shuffle_queue else None

    # -------------------------------------------------------------- verversen

    async def _async_download_display_image(
        self, asset: dict[str, Any]
    ) -> tuple[bytes, str]:
        try:
            return await self.hub.download_asset_preview(asset["id"])
        except (CannotConnect, ApiError):
            if asset.get("originalMimeType") not in WEB_IMAGE_MIME_TYPES:
                raise
            return await self.hub.download_asset(asset["id"])

    async def _async_complete_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        """Haal ontbrekende EXIF-gegevens op (alleen als de lijst die niet had)."""
        if "exifInfo" in asset:
            return asset
        try:
            details = await self.hub.get_asset_info(asset["id"])
        except (CannotConnect, ApiError) as error:
            _LOGGER.debug("Details van %s niet opgehaald: %s", asset["id"], error)
            return asset
        return {**asset, **details}

    async def _async_refresh(self, force_asset_list: bool = False) -> None:
        async with self._refresh_lock:
            await self._async_refresh_locked(force_asset_list)

    async def _async_refresh_locked(self, force_asset_list: bool) -> None:
        try:
            await self._ensure_asset_list(force=force_asset_list)

            asset = self._select_next_asset()
            if not asset:
                self._handle_no_images()
                return

            image_bytes, content_type = await self._async_download_display_image(
                asset
            )
            asset = await self._async_complete_metadata(asset)

            self._current_asset = asset
            self._current_image_bytes = image_bytes
            self._attr_content_type = content_type
            self._recent_asset_ids.append(asset["id"])
            self._refresh_counter += 1
            self._last_successful_refresh = datetime.now(UTC)
            self._last_error = None
            self._attr_available = True
            self.access_tokens.append(secrets.token_hex(32))
            self._attr_image_last_updated = self._last_successful_refresh

            if self.original_entity is not None:
                self.original_entity.source_image_changed()

        except InvalidAuth as error:
            self._last_error = str(error)
            self._attr_available = self._current_image_bytes is not None
            self.config_entry.async_start_reauth(self.hass)
            _LOGGER.error("Authenticatie met Immich mislukt voor %s", self.entity_id)

        except (CannotConnect, ApiError, KeyError, ValueError) as error:
            self._last_error = str(error)
            self._attr_available = self._current_image_bytes is not None
            _LOGGER.warning("Verversen van %s mislukt: %s", self.entity_id, error)

        finally:
            if not self._removed and self.hass is not None and self.entity_id:
                self.async_write_ha_state()

    def _handle_no_images(self) -> None:
        if self._last_error != _NO_IMAGES:
            _LOGGER.info("%s: %s", self.entity_id, _NO_IMAGES)
        self._last_error = _NO_IMAGES
        self._current_asset = None
        self._current_image_bytes = None
        self._attr_available = False
        if self.original_entity is not None:
            self.original_entity.source_image_changed()

    # ------------------------------------------------------- acties/services

    async def async_force_next_image(self) -> None:
        await self._async_refresh()
        self._schedule_next_refresh()

    async def async_set_shuffle_mode(self, enabled: bool) -> None:
        self._shuffle_mode = bool(enabled)
        self._shuffle_queue.clear()
        self.async_write_ha_state()

    async def async_set_random_speed(self, enabled: bool) -> None:
        self._random_speed = bool(enabled)
        self._schedule_next_refresh()
        self.async_write_ha_state()

    async def async_set_refresh_interval(self, seconds: int) -> None:
        self._refresh_interval = min(
            MAX_REFRESH_INTERVAL, max(MIN_REFRESH_INTERVAL, int(seconds))
        )
        self._schedule_next_refresh()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Geef de dashboardversie (preview) terug."""
        return self._current_image_bytes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "refresh_interval": self._refresh_interval,
            "no_repeat_window": self._no_repeat_window,
            "tag_filter": sorted(self._tag_filter),
            "shuffle_mode": self._shuffle_mode,
            "random_speed": self._random_speed,
            "refresh_counter": self._refresh_counter,
            "current_asset_id": self._current_asset_id,
            **asset_metadata(self._current_asset),
            "available_assets": len(self._asset_list),
            "last_successful_refresh": self._last_successful_refresh,
            "last_error": self._last_error,
        }


class ImmichOriginalImage(ImageEntity):
    """Volledige resolutie van de huidige Immich-foto, pas geladen bij openen."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"
    _attr_available = False

    def __init__(
        self, hass: HomeAssistant, source_entity: BaseImmichHomeAssistantImage
    ) -> None:
        super().__init__(hass)

        self.source_entity = source_entity
        self.hub = source_entity.hub

        self._attr_unique_id = original_unique_id(source_entity.source.unique_id)
        self._attr_device_info = source_entity.device_info
        self._attr_translation_key = f"{source_entity.translation_key}_original"
        self._attr_translation_placeholders = dict(
            source_entity.translation_placeholders
        )
        self._attr_image_last_updated = None

        self._cached_asset_id: str | None = None
        self._cached_image_bytes: bytes | None = None
        self._last_error: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_available = self.source_entity._current_asset_id is not None
        self._attr_image_last_updated = self.source_entity.image_last_updated
        self.async_write_ha_state()

    def source_image_changed(self) -> None:
        """Verwerk dat de bronafbeelding is gewijzigd."""
        current_asset_id = self.source_entity._current_asset_id
        if current_asset_id != self._cached_asset_id:
            self._cached_asset_id = None
            self._cached_image_bytes = None

        self._last_error = None
        self._attr_available = current_asset_id is not None
        self._attr_image_last_updated = self.source_entity.image_last_updated
        self.access_tokens.append(secrets.token_hex(32))

        if self.entity_id is not None and self.hass is not None:
            self.async_write_ha_state()

    async def _async_download(self, asset: dict[str, Any]) -> tuple[bytes, str]:
        """Origineel als de browser het kan tonen, anders een omgezette versie.

        HEIC/RAW-originelen kan een browser niet tonen; dan vragen we Immich om
        de 'fullsize'-versie (en op oudere servers de preview).
        """
        asset_id = asset["id"]
        attempts = [self.hub.download_asset_fullsize, self.hub.download_asset_preview]
        if asset.get("originalMimeType", "image/jpeg") in WEB_IMAGE_MIME_TYPES:
            attempts.insert(0, self.hub.download_asset)

        last_error: Exception | None = None
        for attempt in attempts:
            try:
                return await attempt(asset_id)
            except (CannotConnect, ApiError) as error:
                last_error = error
        assert last_error is not None
        raise last_error

    async def async_image(self) -> bytes | None:
        asset = self.source_entity._current_asset
        if not asset:
            return None

        asset_id = asset["id"]
        if self._cached_asset_id == asset_id and self._cached_image_bytes is not None:
            return self._cached_image_bytes

        was_available = self._attr_available
        try:
            image_bytes, content_type = await self._async_download(asset)
        except InvalidAuth as error:
            self._last_error = str(error)
            self._attr_available = False
            self.source_entity.config_entry.async_start_reauth(self.hass)
            _LOGGER.error(
                "Authenticatie met Immich mislukt bij ophalen van origineel %s",
                asset_id,
            )
            image_bytes = None
        except (CannotConnect, ApiError) as error:
            self._last_error = str(error)
            self._attr_available = False
            _LOGGER.warning(
                "Originele Immich-foto %s kon niet worden opgehaald: %s",
                asset_id,
                error,
            )
            image_bytes = None
        else:
            self._cached_asset_id = asset_id
            self._cached_image_bytes = image_bytes
            self._attr_content_type = content_type
            self._last_error = None
            self._attr_available = True

        if was_available != self._attr_available and self.entity_id is not None:
            self.async_write_ha_state()
        return image_bytes

    # Acties op de originele entity werken door op de bron, zodat
    # bijvoorbeeld 'volgende afbeelding' op beide entities werkt.
    async def async_force_next_image(self) -> None:
        await self.source_entity.async_force_next_image()

    async def async_set_shuffle_mode(self, enabled: bool) -> None:
        await self.source_entity.async_set_shuffle_mode(enabled)

    async def async_set_random_speed(self, enabled: bool) -> None:
        await self.source_entity.async_set_random_speed(enabled)

    async def async_set_refresh_interval(self, seconds: int) -> None:
        await self.source_entity.async_set_refresh_interval(seconds)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        source = self.source_entity
        return {
            "current_asset_id": source._current_asset_id,
            **asset_metadata(source._current_asset),
            "source_entity": source.entity_id,
            "image_quality": "original",
            "cached": (
                self._cached_image_bytes is not None
                and self._cached_asset_id == source._current_asset_id
            ),
            "last_error": self._last_error,
        }


class ImmichHomeAssistantFavoriteImage(BaseImmichHomeAssistantImage):
    """Willekeurige afbeelding uit Immich-favorieten."""

    _attr_translation_key = "favorites"

    async def _async_fetch_assets(self) -> list[dict[str, Any]]:
        return await self.hub.list_favorite_images()

    async def _async_fetch_tagged_assets(
        self, tag_ids: list[str]
    ) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for tag_id in tag_ids:
            assets.extend(
                await self.hub.list_tagged_images(tag_id, favorites_only=True)
            )
        return assets


class ImmichHomeAssistantAlbumImage(BaseImmichHomeAssistantImage):
    """Willekeurige afbeelding uit een Immich-album."""

    _attr_translation_key = "album"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ImmichConfigEntry,
        source: ImageSource,
    ) -> None:
        super().__init__(hass, config_entry, source)
        assert source.album_id is not None
        self.album_id = source.album_id
        self.album_name = source.album_name or source.album_id
        self._attr_translation_placeholders = {"album": self.album_name}

    async def _async_fetch_assets(self) -> list[dict[str, Any]]:
        return await self.hub.list_album_images(self.album_id)

    async def _async_fetch_tagged_assets(
        self, tag_ids: list[str]
    ) -> list[dict[str, Any]]:
        tagged_ids: set[str] = set()
        for tag_id in tag_ids:
            tagged_ids.update(
                asset["id"]
                for asset in await self.hub.list_tagged_images(tag_id)
                if asset.get("id")
            )
        album_assets = await self.hub.list_album_images(self.album_id)
        return [asset for asset in album_assets if asset.get("id") in tagged_ids]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **super().extra_state_attributes,
            "album_id": self.album_id,
            "album_name": self.album_name,
        }


class ImmichOnThisDayImage(BaseImmichHomeAssistantImage):
    """Foto's van 'Op deze dag' (Immich-herinneringen) van vandaag."""

    _attr_translation_key = "on_this_day"
    _supports_tag_filter = False
    _asset_list_ttl = MEMORY_LIST_REFRESH_INTERVAL_SECONDS

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ImmichConfigEntry,
        source: ImageSource,
    ) -> None:
        super().__init__(hass, config_entry, source)
        self._asset_list_date: date | None = None

    def _asset_list_expired(self, now: datetime) -> bool:
        return (
            super()._asset_list_expired(now)
            or self._asset_list_date != dt_util.now().date()
        )

    async def _async_fetch_assets(self) -> list[dict[str, Any]]:
        self._asset_list_date = dt_util.now().date()
        return await self.hub.list_on_this_day_images(dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        photo_date = attributes.get("photo_date")
        attributes["years_ago"] = (
            dt_util.now().year - photo_date.year if photo_date else None
        )
        return attributes
