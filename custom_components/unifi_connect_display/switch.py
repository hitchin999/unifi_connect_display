"""Switch platform for UniFi Connect Display."""
from homeassistant.components.switch import SwitchEntity
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
        raw = dev.get("model") or dev.get("type", {}).get("name", "")
        model = raw.replace("-Pro", "")
        if model not in ACTION_MAPS:
            continue
        entities.append(
            UniFiDisplayPowerSwitch(client, dev["id"], dev["name"], model)
        )
    async_add_entities(entities, True)

class UniFiDisplayPowerSwitch(SwitchEntity):
    def __init__(self, client: UniFiConnectClient, device_id: str, name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._attr_name = name
        self._model = model
        self._state = False
        # stable unique ID
        self._attr_unique_id = f"unifi_{device_id}_power"

    @property
    def name(self):
        return self._attr_name

    @property
    def is_on(self):
        return self._state

    @property
    def icon(self):
        # power symbol
        return "mdi:power"

    async def async_turn_on(self, **kwargs):
        action = ACTION_MAPS[self._model]["power_on"]
        await self._client.perform_action(self._device_id, action)
        self._state = True

    async def async_turn_off(self, **kwargs):
        action = ACTION_MAPS[self._model]["power_off"]
        await self._client.perform_action(self._device_id, action)
        self._state = False

    async def async_update(self):
        action = ACTION_MAPS[self._model]["switch"]
        data = await self._client.perform_action(self._device_id, action)
        self._state = data.get("powerState") == "ON"
