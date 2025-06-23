# custom_components/unifi_connect_display/button.py

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []

    for dev in devices:
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        if raw_model not in ACTION_MAPS:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", raw_model)

        for action_key, action_id in ACTION_MAPS[raw_model].items():
            # Friendly label for the action
            friendly = action_key.replace("_", " ").title()
            # A name like "Play (Pool Display Cast Pro)"
            name = f"{friendly} ({device_name})"
            unique_id = f"ucd_{device_id}_{action_key}"

            entities.append(
                UniFiDisplayButton(
                    client, device_id, raw_model, action_key, action_id, name, unique_id
                )
            )

    async_add_entities(entities)


class UniFiDisplayButton(ButtonEntity):
    def __init__(
        self,
        client: UniFiConnectClient,
        device_id: str,
        model: str,
        action_key: str,
        action_id: str,
        name: str,
        unique_id: str,
    ):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._action_key = action_key
        self._action_id = action_id

        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name.split(" (")[1][:-1],  # extract just the device_name
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def name(self) -> str:
        return self._attr_name

    async def async_press(self) -> None:
        _LOGGER.debug("Button press %s on %s", self._action_key, self._device_id)
        await self._client.perform_action(self._device_id, self._action_id)
