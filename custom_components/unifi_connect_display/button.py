# custom_components/unifi_connect_display/button.py

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)

BUTTON_ACTIONS = {
    "power_on",
    "power_off",
    "start_locating",
    "stop_locating",
    "play",
    "stop",
    "reboot",
    "rotate",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities: list[UniFiDisplayButton] = []

    for dev in devices:
        model = dev.get("type", {}).get("name", "")
        if model not in ACTION_MAPS:
            continue
        device_id = dev["id"]
        device_name = dev.get("name", "UniFi Display")

        for action_key, action_id in ACTION_MAPS[model].items():
            if action_key not in BUTTON_ACTIONS:
                continue
            entities.append(
                UniFiDisplayButton(
                    client,
                    device_id,
                    device_name,
                    model,
                    action_key,
                    action_id,
                )
            )

    async_add_entities(entities)


class UniFiDisplayButton(ButtonEntity):
    """Represents a single UniFi Connect display action as a button."""

    # 1) Force HA to use our full name() field
    _attr_has_entity_name = False

    def __init__(
        self,
        client: UniFiConnectClient,
        device_id: str,
        device_name: str,
        model: str,
        action_key: str,
        action_id: str,
    ):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._action_key = action_key
        self._action_id = action_id

        # Friendly name: "<Display Name> <Action>"
        friendly = action_key.replace("_", " ").title()
        self._attr_name = f"{device_name} {friendly}"

        # 2) Unique ID so it’s manageable in HA
        self._attr_unique_id = f"ucd_{device_id}_{action_key}"

        # DO NOT set device_info — that makes HA group you under the device.

    async def async_press(self) -> None:
        """Send the action command to the display."""
        _LOGGER.debug("Sending %s to %s", self._action_key, self._device_id)
        await self._client.perform_action(self._device_id, self._action_id)

    @property
    def name(self) -> str:
        """Return the full friendly name (<Display Name> <Action>)."""
        return self._attr_name
