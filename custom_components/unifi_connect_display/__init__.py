# custom_components/unifi_connect_display/__init__.py

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .api import UniFiConnectClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # 1️⃣ Create and login the client one single time here
    client = UniFiConnectClient(
        hass,
        entry.data["host"],
        entry.data["username"],
        entry.data["password"],
        entry.data.get("site"),
    )
    await client.login()
    hass.data[DOMAIN][entry.entry_id] = client

    # 2️⃣ Forward to all three platforms in one call
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "switch", "button"]
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # 3️⃣ Unload those platforms and close the session once
    await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "switch", "button"]
    )
    client = hass.data[DOMAIN].pop(entry.entry_id)
    await client.close()
    return True
