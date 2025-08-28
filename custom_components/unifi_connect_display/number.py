# custom_components/unifi_connect_display/number.py

import logging
from typing import Optional

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from aiohttp import ClientResponseError

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities: list[NumberEntity] = []

    for dev in devices:
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        device_id = dev["id"]
        device_name = dev.get("name", raw_model)

        # Brightness slider if supported
        if any(k in ACTION_MAPS.get(raw_model, {}) for k in ("brightness", "set_brightness")):
            entities.append(
                UniFiBrightnessNumber(client, device_id, device_name, raw_model)
            )

        # Volume slider if supported
        if any(k in ACTION_MAPS.get(raw_model, {}) for k in ("volume", "set_volume")):
            entities.append(
                UniFiVolumeNumber(client, device_id, device_name, raw_model)
            )

    async_add_entities(entities, update_before_add=True)


class _BaseUcdNumber(NumberEntity):
    """Common helpers for push updates + cached reads."""

    _attr_should_poll = True  # allow HA to call async_update, but we also do push

    def __init__(self, client: UniFiConnectClient, device_id: str, device_name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_available = True
        self._unsub_dispatcher = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

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
            self.async_schedule_update_ha_state(True)

    def _get_cached(self) -> Optional[dict]:
        return self._client.get_cached_device(self._device_id)


class UniFiBrightnessNumber(_BaseUcdNumber):
    def __init__(self, client, device_id, device_name, model):
        super().__init__(client, device_id, device_name, model)
        self._attr_name = f"Brightness ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_brightness"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100  # will be adjusted dynamically
        self._attr_native_step = 1
        self._attr_native_value: Optional[float] = None

    def _max_brightness_for(self, dev: dict) -> int:
        # Prefer extraInfo.maxBrightness if present
        extra = (dev or {}).get("extraInfo") or {}
        if isinstance(extra.get("maxBrightness"), int):
            return max(1, extra["maxBrightness"])
        # Fallback heuristic
        return 100

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_set_native_value(self, value: float):
        # Choose action name available for the model
        if "brightness" in ACTION_MAPS.get(self._model, {}):
            action_name = "brightness"
        elif "set_brightness" in ACTION_MAPS.get(self._model, {}):
            action_name = "set_brightness"
        else:
            _LOGGER.debug("Brightness action not supported for model %s", self._model)
            return

        dev = self._get_cached() or {}
        max_bri = self._max_brightness_for(dev)
        self._attr_native_max_value = max_bri  # keep slider in sync

        ivalue = int(max(0, min(max_bri, round(value))))
        try:
            await self._client.perform_action(self._device_id, action_name, {"value": ivalue})
            self._attr_native_value = float(ivalue)
            self.async_write_ha_state()
        except ClientResponseError as e:
            if e.status != 404:
                _LOGGER.warning("Brightness set failed for %s: %s", self._attr_name, e)
        except Exception as e:
            _LOGGER.warning("Brightness set failed for %s: %s", self._attr_name, e)

    async def async_update(self):
        """Populate from cached device shadow."""
        dev = self._get_cached()
        if not dev:
            # rare fallback: refresh cache once
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)

        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}

        # Update max based on device capability
        max_bri = self._max_brightness_for(dev)
        self._attr_native_max_value = max_bri

        # Read current brightness if present
        bri = shadow.get("brightness")
        if isinstance(bri, (int, float)):
            self._attr_native_value = float(bri)


class UniFiVolumeNumber(_BaseUcdNumber):
    def __init__(self, client, device_id, device_name, model):
        super().__init__(client, device_id, device_name, model)
        self._attr_name = f"Volume ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_volume"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100  # will adjust dynamically
        self._attr_native_step = 1
        self._attr_native_value: Optional[float] = None

    def _max_volume_for(self, dev: dict) -> int:
        ff = (dev or {}).get("featureFlags") or {}
        vol = ff.get("volume") or {}
        if isinstance(vol, dict) and isinstance(vol.get("max"), int):
            return max(1, vol["max"])
        extra = (dev or {}).get("extraInfo") or {}
        if isinstance(extra.get("maxVolume"), int):
            return max(1, extra["maxVolume"])
        return 100

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_set_native_value(self, value: float):
        # Pick correct action name for this model
        if "set_volume" in ACTION_MAPS.get(self._model, {}):
            action_name = "set_volume"
        elif "volume" in ACTION_MAPS.get(self._model, {}):
            action_name = "volume"
        else:
            _LOGGER.debug("Volume action not supported for model %s", self._model)
            return

        dev = self._get_cached() or {}
        max_vol = self._max_volume_for(dev)
        self._attr_native_max_value = max_vol  # keep slider in sync

        ivalue = int(max(0, min(max_vol, round(value))))
        try:
            await self._client.perform_action(self._device_id, action_name, {"value": ivalue})
            self._attr_native_value = float(ivalue)
            self.async_write_ha_state()
        except ClientResponseError as e:
            if e.status != 404:
                _LOGGER.warning("Volume set failed for %s: %s", self._attr_name, e)
        except Exception as e:
            _LOGGER.warning("Volume set failed for %s: %s", self._attr_name, e)

    async def async_update(self):
        """Populate from cached device shadow."""
        dev = self._get_cached()
        if not dev:
            # rare fallback: refresh cache once
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)

        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}

        # Adjust slider range based on capability
        max_vol = self._max_volume_for(dev)
        self._attr_native_max_value = max_vol

        # Read current volume if present
        vol = shadow.get("volume")
        if isinstance(vol, (int, float)):
            self._attr_native_value = float(vol)
