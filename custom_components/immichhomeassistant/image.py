
async def _async_refresh(self, force_asset_list=False):
    await self._ensure_asset_list(force=force_asset_list)
    asset = self._select_next_asset()
    asset_id = asset.get('id')

    # eerst thumbnail
    image_bytes = await self.hub.download_asset_thumbnail(asset_id)

    # fallback
    if not image_bytes:
        image_bytes = await self.hub.download_asset(asset_id)

    self._current_image_bytes = image_bytes
    self._attr_image_last_updated = datetime.now(UTC)
    self.async_write_ha_state()
