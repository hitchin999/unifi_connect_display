# custom_components/unifi_connect_display/__init__.py

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from .api import UniFiConnectClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Initialize the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a UniFi Connect Display config entry."""
    # 1️⃣ Create and log in the client once
    client = UniFiConnectClient(
        hass,
        entry.data["host"],
        entry.data["username"],
        entry.data["password"],
        entry.data.get("site"),
    )
    await client.login()
    hass.data[DOMAIN][entry.entry_id] = client

    # — Listen for HA stopping so we can always close our session —
    async def _shutdown(event):
        """Close our client session on HA stop."""
        await client.close()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)

    # 2️⃣ Forward to all supported platforms
    await hass.config_entries.async_forward_entry_setups(
        entry,
        [
            "sensor",
            "switch",
            "button",
            "media_player",
            "number",
            "text",
        ],
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a UniFi Connect Display config entry."""
    # 3️⃣ Unload all platforms and close the client session
    await hass.config_entries.async_unload_platforms(
        entry,
        [
            "sensor",
            "switch",
            "button",
            "media_player",
            "number",
            "text",
        ],
    )
    client = hass.data[DOMAIN].pop(entry.entry_id)
    await client.close()
    return True
