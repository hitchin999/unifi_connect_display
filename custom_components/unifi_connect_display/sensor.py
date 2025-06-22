# custom_components/unifi_connect_display/sensor.py

"""Sensor platform for UniFi Connect Display."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, ACTION_MAPS
from .api import UniFiConnectClient

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []
    for dev in devices:
        # get raw model or fall back to type.name
        raw = dev.get("model") or dev.get("type", {}).get("name", "")
        # strip off any "-Pro" suffix
        model = raw.replace("-Pro", "")
        if model not in ACTION_MAPS:
            continue
        entities.append(
            UniFiDisplayStatusSensor(client, dev["id"], dev["name"], model)
        )
    async_add_entities(entities, True)

class UniFiDisplayStatusSensor(SensorEntity):
    def __init__(self, client: UniFiConnectClient, device_id: str, name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._attr_name = name
        self._model = model
        self._state = None
        self._attrs = {}
        # give HA a stable unique ID
        self._attr_unique_id = f"unifi_{device_id}_status"


    @property
    def name(self):
        return self._attr_name
        
    @property
    def icon(self):
        # power symbol
        return "mdi:power"

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attrs

    async def async_update(self):
        action = ACTION_MAPS[self._model]["switch"]
        data = await self._client.perform_action(self._device_id, action)
        self._state = data.get("powerState")
        self._attrs["brightness"] = data.get("brightness")
        self._attrs["volume"] = data.get("volume")
