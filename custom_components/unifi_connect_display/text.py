# custom_components/unifi_connect_display/text.py

import logging
from typing import Any, Optional

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities: list[TextEntity] = []

    for dev in devices:
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        if raw_model not in ACTION_MAPS:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", raw_model)
        actions = ACTION_MAPS[raw_model]

        if "load_website" in actions:
            entities.append(UniFiLoadWebsiteText(client, device_id, device_name, raw_model))

        if "load_youtube" in actions:
            entities.append(UniFiYouTubeText(client, device_id, device_name, raw_model))

    async_add_entities(entities, update_before_add=True)


class _BaseUniFiText(TextEntity):
    """Base helper with common push updates + cached reads."""

    _attr_mode = "text"
    _attr_should_poll = True  # we also listen for push updates

    def __init__(self, client: UniFiConnectClient, device_id: str, device_name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_native_value: Optional[str] = None
        self._attrs: dict[str, Any] = {}
        self._attr_available = True
        self._unsub_dispatcher = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def native_value(self) -> str | None:
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    async def async_added_to_hass(self) -> None:
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, SIGNAL_DEVICE_UPDATE, self._handle_device_push
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None

    def _handle_device_push(self, device_id: str) -> None:
        if device_id == self._device_id:
            # Re-read from cache immediately
            self.schedule_update_ha_state(True)

    def _get_cached(self) -> Optional[dict]:
        return self._client.get_cached_device(self._device_id)

    async def _fetch_device(self) -> Optional[dict]:
        """Fetch device from cache; rare fallback to refresh."""
        dev = self._get_cached()
        if dev:
            self._attr_available = True
            return dev

        try:
            devices = await self._client.list_devices()
            for d in devices:
                if d.get("id") == self._device_id:
                    self._attr_available = True
                    return d
        except Exception as e:
            _LOGGER.warning("Failed to refresh device %s: %s", self._device_id, e)

        self._attr_available = False
        return None


class UniFiLoadWebsiteText(_BaseUniFiText):
    """TextEntity to send arbitrary URLs to the display via load_website."""

    def __init__(self, client, device_id, device_name, model):
        super().__init__(client, device_id, device_name, model)
        self._attr_name = f"Website URL ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_url"

    async def async_set_value(self, value: str) -> None:
        try:
            # Call by ACTION NAME; client maps to UUID internally
            await self._client.perform_action(
                self._device_id,
                "load_website",
                {"url": value},
            )
            self._attr_native_value = value  # optimistic; WS will confirm
        except Exception as e:
            _LOGGER.warning("Failed loading URL for %s: %s", self._attr_name, e)

    async def async_update(self) -> None:
        """Read current web URL + metadata from device shadow/snapshot."""
        dev = await self._fetch_device()
        if not dev:
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}
        snapshot = dev.get("snapshot") or {}

        # "currentHomePage": "https://…"
        self._attr_native_value = shadow.get("currentHomePage") or ""

        # Extras for UI
        self._attrs = {
            "mode": shadow.get("mode"),
            "page_title": snapshot.get("title"),
            "favicon": snapshot.get("favicon"),
            "thumbnail": snapshot.get("url"),   # may be empty if OG image not found
            "auto_reload": shadow.get("autoReload"),
        }


class UniFiYouTubeText(_BaseUniFiText):
    """TextEntity for YouTube: shows current link/title and lets you load a new link."""

    def __init__(self, client, device_id, device_name, model):
        super().__init__(client, device_id, device_name, model)
        self._attr_name = f"YouTube URL ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_youtube_url"

    async def async_set_value(self, value: str) -> None:
        try:
            await self._client.perform_action(
                self._device_id,
                "load_youtube",   # call by name
                {"url": value},
            )
            self._attr_native_value = value  # optimistic; WS will confirm
        except Exception as e:
            _LOGGER.warning("Failed loading YouTube URL for %s: %s", self._attr_name, e)

    async def async_update(self) -> None:
        """Pull current YouTube page + snapshot metadata; keep entity available."""
        dev = await self._fetch_device()
        if not dev:
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}
        snapshot = dev.get("snapshot") or {}

        # Current YouTube link shown in the text field
        self._attr_native_value = shadow.get("currentYouTubePage") or ""

        # Helpful metadata
        self._attrs = {
            "mode": shadow.get("mode"),
            "page_title": snapshot.get("title"),
            "thumbnail": snapshot.get("url"),
            "favicon": snapshot.get("favicon"),
        }

        # Optional: restrict availability to only YouTube mode
        # self._attr_available = (shadow.get("mode") == "youtube")
