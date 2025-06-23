# custom_components/unifi_connect_display/switch.py

import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []

    for dev in devices:
        raw = dev.get("model") or dev.get("type", {}).get("name", "")
        model = raw.replace("-Pro", "")
        if model not in ACTION_MAPS or "power_on" not in ACTION_MAPS[model]:
            continue

        device_id = dev["id"]
        name = dev.get("name", raw)
        entities.append(UniFiDisplayPowerSwitch(client, device_id, name, model))

    async_add_entities(entities, True)


class UniFiDisplayPowerSwitch(SwitchEntity):
    def __init__(self, client, device_id, name, model):
        self._client = client
        self._device_id = device_id
        self._attr_name = f"Status ({device_name})"
        self._model = model
        self._state = False
        self._attr_unique_id = f"ucd_{device_id}_power"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def is_on(self):
        return self._state

    @property
    def icon(self):
        return "mdi:power"

    async def async_turn_on(self, **kwargs):
        await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["power_on"])
        self._state = True

    async def async_turn_off(self, **kwargs):
        await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["power_off"])
        self._state = False

    async def async_update(self):
        try:
            data = await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["switch"])
            self._state = data.get("powerState") == "ON"
        except Exception as e:
            _LOGGER.warning("Power update failed for %s: %s", self._attr_name, e)
