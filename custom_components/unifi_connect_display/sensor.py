# custom_components/unifi_connect_display/sensor.py

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
import logging

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []

    for dev in devices:
        # 🔴 use raw_model with the -Pro if it’s there, but only real displays have “brightness”
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        if raw_model not in ACTION_MAPS or "brightness" not in ACTION_MAPS[raw_model]:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", raw_model)
        entities.append(
            UniFiDisplayStatusSensor(
                client, device_id, device_name, raw_model
            )
        )

    async_add_entities(entities, True)


class UniFiDisplayStatusSensor(SensorEntity):
    def __init__(self, client, device_id, device_name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._state = None
        self._attrs = {}

        # 👇 put the device name in parentheses so HA won’t strip it
        self._attr_name = f"Status ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_status"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def icon(self):
        return "mdi:power"

    @property
    def extra_state_attributes(self):
        return self._attrs

    async def async_update(self):
        try:
            data = await self._client.perform_action(
                self._device_id,
                ACTION_MAPS[self._model]["switch"]
            )
            self._state = data.get("powerState")
            self._attrs["brightness"] = data.get("brightness")
            self._attrs["volume"]     = data.get("volume")
        except Exception as e:
            _LOGGER.warning("Status update failed for %s: %s", self._attr_name, e)
