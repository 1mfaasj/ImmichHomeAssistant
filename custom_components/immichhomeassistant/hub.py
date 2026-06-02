
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from urllib.parse import urljoin
from aiohttp import ClientError

class ImmichHomeAssistantHub:
    def __init__(self, hass, host, api_key):
        self.hass = hass
        self.host = host.rstrip('/')
        self.api_key = api_key
        self.session = async_get_clientsession(hass)

    async def download_asset_thumbnail(self, asset_id):
        url = urljoin(f"{self.host}/", f"api/assets/{asset_id}/thumbnail")
        try:
            async with self.session.get(url, headers={"x-api-key": self.api_key}) as r:
                if r.status == 200:
                    return await r.read()
                return None
        except ClientError:
            return None

    async def download_asset(self, asset_id):
        url = urljoin(f"{self.host}/", f"api/assets/{asset_id}/original")
        try:
            async with self.session.get(url, headers={"x-api-key": self.api_key}) as r:
                if r.status == 200:
                    return await r.read()
                return None
        except ClientError:
            return None
