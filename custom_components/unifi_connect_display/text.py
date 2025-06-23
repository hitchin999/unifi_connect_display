# custom_components/unifi_connect_display/text.py

import logging
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []

    for dev in devices:
        # 🔴 keep the full raw model (with -Pro)
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        # only add if load_website exists for this model
        if raw_model not in ACTION_MAPS or "load_website" not in ACTION_MAPS[raw_model]:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", raw_model)
        entities.append(
            UniFiLoadWebsiteText(client, device_id, device_name, raw_model)
        )

    async_add_entities(entities)


class UniFiLoadWebsiteText(TextEntity):
    """TextEntity to send arbitrary URLs to the display via load_website."""

    _attr_mode = "text"  # single-line text input

    def __init__(self, client, device_id, device_name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._value = ""

        # Put the display name in parentheses so HA won’t strip it
        self._attr_name = f"Website URL ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_url"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def value(self) -> str:
        return self._value or ""

    async def async_set_value(self, value: str) -> None:
        """Called when user types a URL and hits ‘Update’ in HA."""
        # wrap in JSON args
        args = f"\"url\":\"{value}\""
        action = ACTION_MAPS[self._model]["load_website"]
        try:
            await self._client.perform_action(self._device_id, action, args)
            # remember last sent URL
            self._value = value
        except Exception as e:
            _LOGGER.warning("Failed loading URL for %s: %s", self._attr_name, e)

    async def async_update(self):
        """No polling needed—keep last value."""
        pass
    