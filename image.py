from __future__ import annotations

from collections import deque
from datetime import datetime, UTC
import logging
import random
import secrets

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    DOMAIN,
    CONF_WATCHED_ALBUMS,
    CONF_REFRESH_INTERVAL,
    CONF_NO_REPEAT_WINDOW,
    CONF_TAG_FILTER,
    CONF_SHUFFLE_MODE,
    CONF_RANDOM_SPEED,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_NO_REPEAT_WINDOW,
    DEFAULT_TAG_FILTER,
    DEFAULT_SHUFFLE_MODE,
    DEFAULT_RANDOM_SPEED,
    ID_LIST_REFRESH_INTERVAL_SECONDS,
)
from .hub import ImmichHomeAssistantHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ImmichHomeAssistant image entities."""
    hub: ImmichHomeAssistantHub = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[ImageEntity] = [
        ImmichHomeAssistantFavoriteImage(hass, config_entry, hub)
    ]

    watched_album_ids = config_entry.options.get(CONF_WATCHED_ALBUMS, [])
    if watched_album_ids:
        try:
            albums = await hub.list_all_albums()
            album_map = {
                album["id"]: album["albumName"]
                for album in albums
                if "id" in album and "albumName" in album
            }

            for album_id in watched_album_ids:
                album_name = album_map.get(album_id)
                if album_name:
                    entities.append(
                        ImmichHomeAssistantAlbumImage(
                            hass,
                            config_entry,
                            hub,
                            album_id,
                            album_name,
                        )
                    )
        except Exception as err:
            _LOGGER.exception("Failed to load albums: %s", err)

    hass.data.setdefault(f"{DOMAIN}_entities", {})
    hass.data[f"{DOMAIN}_entities"][config_entry.entry_id] = entities

    async_add_entities(entities)


class BaseImmichHomeAssistantImage(ImageEntity):
    """Base image entity for ImmichHomeAssistant."""

    _attr_should_poll = False
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        hub: ImmichHomeAssistantHub,
        name: str,
        unique_id: str,
    ) -> None:
        """Initialize image entity."""
        # BELANGRIJK: expliciet ImageEntity init doen
        # Home Assistant Core voorbeelden doen dit ook voor image entities.
        ImageEntity.__init__(self, hass)

        self.hass = hass
        self.config_entry = config_entry
        self.hub = hub

        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_image_last_updated = None

        # Hard fix voor jouw huidige fout:
        # Home Assistant image platform verwacht access_tokens.
        self.access_tokens = deque([secrets.token_hex(32)], maxlen=2)

        self._refresh_interval = int(
            config_entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
        )
        self._no_repeat_window = int(
            config_entry.options.get(CONF_NO_REPEAT_WINDOW, DEFAULT_NO_REPEAT_WINDOW)
        )
        self._tag_filter = self._parse_tag_filter(
            config_entry.options.get(CONF_TAG_FILTER, DEFAULT_TAG_FILTER)
        )
        self._shuffle_mode = bool(
            config_entry.options.get(CONF_SHUFFLE_MODE, DEFAULT_SHUFFLE_MODE)
        )
        self._random_speed = bool(
            config_entry.options.get(CONF_RANDOM_SPEED, DEFAULT_RANDOM_SPEED)
        )

        self._current_asset_id: str | None = None
        self._current_image_bytes: bytes | None = None
        self._last_asset_ids_refresh: datetime | None = None
        self._asset_list: list[dict] = []
        self._recent_asset_ids: deque[str] = deque(
            maxlen=max(self._no_repeat_window, 1)
        )
        self._shuffle_queue: list[dict] = []
        self._refresh_counter = 0
        self._unsub_refresh = None

    @staticmethod
    def _parse_tag_filter(value: str | None) -> set[str]:
        """Parse comma-separated tags."""
        if not value:
            return set()
        return {item.strip().lower() for item in value.split(",") if item.strip()}

    def async_update_token(self) -> None:
        """Rotate image access token."""
        self.access_tokens.append(secrets.token_hex(32))

    async def async_added_to_hass(self) -> None:
        """Handle entity added to HA."""
        await self._async_refresh(force_asset_list=True)
        self._schedule_next_refresh()

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when entity is removed."""
        if self._unsub_refresh:
            self._unsub_refresh()
            self._unsub_refresh = None

    def _schedule_next_refresh(self) -> None:
        """Schedule next refresh."""
        if self._unsub_refresh:
            self._unsub_refresh()

        delay = self._next_delay_seconds()
        self._unsub_refresh = async_call_later(self.hass, delay, self._handle_refresh)

    def _next_delay_seconds(self) -> int:
        """Return next refresh delay."""
        base = max(10, self._refresh_interval)

        if not self._random_speed:
            return base

        low = max(10, int(base * 0.5))
        high = max(low, int(base * 1.5))
        return random.randint(low, high)

    async def _handle_refresh(self, _now) -> None:
        """Handle scheduled refresh."""
        await self._async_refresh()
        self._schedule_next_refresh()

    async def _async_get_asset_list(self) -> list[dict]:
        """Get asset list for this entity."""
        raise NotImplementedError

    async def _ensure_asset_list(self, force: bool = False) -> None:
        """Refresh asset list if needed."""
        now = datetime.now(UTC)
        should_refresh = force

        if self._last_asset_ids_refresh is None:
            should_refresh = True
        else:
            age_seconds = (now - self._last_asset_ids_refresh).total_seconds()
            if age_seconds >= ID_LIST_REFRESH_INTERVAL_SECONDS:
                should_refresh = True

        if not should_refresh:
            return

        assets = await self._async_get_asset_list()
        assets = await self._apply_tag_filter(assets)

        self._asset_list = assets
        self._shuffle_queue = []
        self._last_asset_ids_refresh = now

    async def _apply_tag_filter(self, assets: list[dict]) -> list[dict]:
        """Apply optional tag filter."""
        if not self._tag_filter:
            return assets

        filtered: list[dict] = []

        for asset in assets:
            tag_names = set()
            raw_tags = asset.get("tags") or []

            if isinstance(raw_tags, list):
                for tag in raw_tags:
                    if isinstance(tag, dict):
                        value = tag.get("value") or tag.get("name")
                        if value:
                            tag_names.add(str(value).lower())
                    elif isinstance(tag, str):
                        tag_names.add(tag.lower())

            # fallback: asset details ophalen als tags niet in lijst zitten
            if not tag_names:
                try:
                    asset_info = await self.hub.get_asset_info(asset["id"])
                except Exception:
                    asset_info = None

                if isinstance(asset_info, dict):
                    for tag in asset_info.get("tags", []):
                        if isinstance(tag, dict):
                            value = tag.get("value") or tag.get("name")
                            if value:
                                tag_names.add(str(value).lower())
                        elif isinstance(tag, str):
                            tag_names.add(tag.lower())

            if self._tag_filter.intersection(tag_names):
                filtered.append(asset)

        return filtered

    def _next_asset_from_shuffle(self) -> dict | None:
        """Return next shuffled asset."""
        while self._shuffle_queue:
            asset = self._shuffle_queue.pop(0)
            asset_id = asset.get("id")
            if (
                asset_id != self._current_asset_id
                and asset_id not in self._recent_asset_ids
            ):
                return asset

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

        if not candidates:
            candidates = self._asset_list[:]

        self._shuffle_queue = candidates[:]
        random.shuffle(self._shuffle_queue)

        return self._shuffle_queue.pop(0) if self._shuffle_queue else None

    def _select_next_asset(self) -> dict | None:
        """Select next asset."""
        if not self._asset_list:
            return None

        if self._shuffle_mode:
            return self._next_asset_from_shuffle()

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

        if not candidates:
            candidates = self._asset_list

        return random.choice(candidates)

    async def _async_refresh(self, force_asset_list: bool = False) -> None:
        """Refresh displayed image."""
        try:
            await self._ensure_asset_list(force=force_asset_list)

            if not self._asset_list:
                _LOGGER.warning("No assets available for %s", self.name)
                return

            asset = self._select_next_asset()
            if not asset:
                _LOGGER.warning("No asset selected for %s", self.name)
                return

            asset_id = asset.get("id")
            if not asset_id:
                _LOGGER.warning("Selected asset has no id for %s", self.name)
                return

            # Eerst thumbnail endpoint
            image_bytes = await self.hub.download_asset_thumbnail(asset_id)

            # Fallback naar original
            if not image_bytes:
                image_bytes = await self.hub.download_asset(asset_id)

            if not image_bytes:
                _LOGGER.warning("Failed to fetch image bytes for %s", asset_id)
                return

            self._current_asset_id = asset_id
            self._current_image_bytes = image_bytes
            self._recent_asset_ids.append(asset_id)
            self._refresh_counter += 1

            # Token roteren + timestamp bijwerken zodat frontend herlaadt
            self.async_update_token()
            self._attr_image_last_updated = datetime.now(UTC)

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.exception("Failed refreshing %s: %s", self.name, err)

    async def async_force_next_image(self) -> None:
        """Force next image immediately."""
        await self._async_refresh()
        self._schedule_next_refresh()

    async def async_set_shuffle_mode(self, enabled: bool) -> None:
        """Toggle shuffle mode at runtime."""
        self._shuffle_mode = bool(enabled)
        self._shuffle_queue = []
        self.async_write_ha_state()

    async def async_set_random_speed(self, enabled: bool) -> None:
        """Toggle random speed at runtime."""
        self._random_speed = bool(enabled)
        self._schedule_next_refresh()
        self.async_write_ha_state()

    async def async_set_refresh_interval(self, seconds: int) -> None:
        """Set refresh interval at runtime."""
        self._refresh_interval = int(seconds)
        self._schedule_next_refresh()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return image bytes."""
        return self._current_image_bytes

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra info."""
        return {
            "refresh_interval": self._refresh_interval,
            "no_repeat_window": self._no_repeat_window,
            "tag_filter": sorted(self._tag_filter),
            "shuffle_mode": self._shuffle_mode,
            "random_speed": self._random_speed,
            "refresh_counter": self._refresh_counter,
            "current_asset_id": self._current_asset_id,
            "available_assets": len(self._asset_list),
        }


class ImmichHomeAssistantFavoriteImage(BaseImmichHomeAssistantImage):
    """Favorite image entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        hub: ImmichHomeAssistantHub,
    ) -> None:
        super().__init__(
            hass=hass,
            config_entry=config_entry,
            hub=hub,
            name="Immich Favorite",
            unique_id="immichhomeassistant_favorite_image",
        )

    async def _async_get_asset_list(self) -> list[dict]:
        return await self.hub.list_favorite_images()


class ImmichHomeAssistantAlbumImage(BaseImmichHomeAssistantImage):
    """Album image entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        hub: ImmichHomeAssistantHub,
        album_id: str,
        album_name: str,
    ) -> None:
        self.album_id = album_id
        self.album_name = album_name

        super().__init__(
            hass=hass,
            config_entry=config_entry,
            hub=hub,
            name=f"Immich {album_name}",
            unique_id=f"immichhomeassistant_album_{album_id}",
        )

    async def _async_get_asset_list(self) -> list[dict]:
        return await self.hub.list_album_images(self.album_id)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        attrs.update(
            {
                "album_id": self.album_id,
                "album_name": self.album_name,
            }
        )
        return attrs
