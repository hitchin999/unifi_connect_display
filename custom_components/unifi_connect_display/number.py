# custom_components/unifi_connect_display/number.py

import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from aiohttp import ClientResponseError

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

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

        # Only add a Brightness slider if the model has a "brightness" action
        if "brightness" in ACTION_MAPS.get(raw_model, {}):
            entities.append(
                UniFiBrightnessNumber(client, device_id, device_name, raw_model)
            )

        # Only add a Volume slider if the model has "volume" or "set_volume"
        if any(k in ACTION_MAPS.get(raw_model, {}) for k in ("volume", "set_volume")):
            entities.append(
                UniFiVolumeNumber(client, device_id, device_name, raw_model)
            )

    async_add_entities(entities, True)


class UniFiBrightnessNumber(NumberEntity):
    def __init__(self, client, device_id, device_name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_name = f"Brightness ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_brightness"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 100
        self._value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def native_value(self):
        return self._value

    async def async_set_native_value(self, value: float):
        args = f"\"value\":{int(value)}"
        await self._client.perform_action(
            self._device_id, ACTION_MAPS[self._model]["brightness"], args
        )
        self._value = value

    async def async_update(self):
        try:
            data = await self._client.perform_action(
                self._device_id, ACTION_MAPS[self._model]["switch"]
            )
            self._value = data.get("brightness")
        except ClientResponseError as e:
            # ignore 404 if switch/status unsupported
            if e.status != 404:
                _LOGGER.warning("Brightness update failed for %s: %s", self._attr_name, e)
        except Exception as e:
            _LOGGER.warning("Brightness update failed for %s: %s", self._attr_name, e)


class UniFiVolumeNumber(NumberEntity):
    def __init__(self, client, device_id, device_name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_name = f"Volume ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_volume"
        # UC Cast Pro reports maxVolume 40
        self._attr_native_min_value = 0
        self._attr_native_max_value = 40
        self._attr_native_step = 1
        self._value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def native_value(self):
        return self._value

    async def async_set_native_value(self, value: float):
        # clamp and cast to int
        ivalue = max(0, min(40, int(round(value))))
        # choose the action NAME your model exposes
        action_name = "set_volume" if "set_volume" in ACTION_MAPS[self._model] else "volume"
        # call by NAME with args dict (perform_action maps to UUID)
        await self._client.perform_action(self._device_id, action_name, {"value": ivalue})
        self._value = float(ivalue)
        self.async_write_ha_state()

    async def async_update(self):
        # Optimistic: many firmwares don’t expose a direct “read volume” API.
        # If you later add a GET status helper, you can populate self._value here.
        return

