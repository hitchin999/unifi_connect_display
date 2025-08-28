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

# Any actions that should be represented as a switch (not as buttons)
_POWER_ACTIONS = {"power_on", "power_off", "display_on", "display_off"}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]

    devices = await client.list_devices()
    entities: list[UniFiDisplayButton] = []

    for dev in devices:
        model_key = dev.get("model") or dev.get("type", {}).get("name", "")
        if model_key not in ACTION_MAPS:
            continue

        is_cast_pro = model_key == "UC-Cast-Pro"

        device_id = dev["id"]
        device_name = dev.get("name", model_key)

        for action_name in ACTION_MAPS[model_key].keys():
            # 1) Never create volume buttons (Number entity handles it elsewhere)
            if action_name in ("volume", "set_volume"):
                continue

            # 2) UC-Cast-Pro: play/rotate/switch are selects, not buttons
            if is_cast_pro and action_name in ("play", "rotate", "switch"):
                continue

            # 3) Power-related actions are now handled by a Switch entity
            if action_name in _POWER_ACTIONS:
                continue

            # 4) Keep a single explicit STOP signage button
            if action_name == "stop":
                name = f"Stop (Signage) ({device_name})"
                unique_id = f"ucd_{device_id}_stop"
                entities.append(
                    UniFiDisplayButton(
                        client=client,
                        device_id=device_id,
                        model=model_key,
                        action_name="stop",
                        name=name,
                        unique_id=unique_id,
                    )
                )
                continue

            # 5) For non–Cast-Pro models create arg-specific Switch & Rotate buttons
            if not is_cast_pro and action_name == "switch":
                for mode in ("web", "youtube", "digitalSignage"):
                    friendly_mode = f"Switch → {mode} ({device_name})"
                    unique_mode_id = f"ucd_{device_id}_switch_{mode}"
                    btn = UniFiDisplayButton(
                        client=client,
                        device_id=device_id,
                        model=model_key,
                        action_name="switch",
                        name=friendly_mode,
                        unique_id=unique_mode_id,
                    )
                    btn._args = {"mode": mode}
                    entities.append(btn)
                continue

            if not is_cast_pro and action_name == "rotate":
                for scale in ("portraitPrim", "landscapePrim", "landscapeSec", "portraitSec"):
                    friendly_scale = f"Rotate → {scale} ({device_name})"
                    unique_scale_id = f"ucd_{device_id}_rotate_{scale}"
                    btn = UniFiDisplayButton(
                        client=client,
                        device_id=device_id,
                        model=model_key,
                        action_name="rotate",
                        name=friendly_scale,
                        unique_id=unique_scale_id,
                    )
                    btn._args = {"scale": scale}
                    entities.append(btn)
                continue

            # 6) Default button for everything else
            friendly = action_name.replace("_", " ").title()
            name = f"{friendly} ({device_name})"
            unique_id = f"ucd_{device_id}_{action_name}"
            entities.append(
                UniFiDisplayButton(
                    client=client,
                    device_id=device_id,
                    model=model_key,
                    action_name=action_name,
                    name=name,
                    unique_id=unique_id,
                )
            )

    async_add_entities(entities)


class UniFiDisplayButton(ButtonEntity):
    def __init__(
        self,
        client: UniFiConnectClient,
        device_id: str,
        model: str,
        action_name: str,
        name: str,
        unique_id: str,
    ):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._action_name = action_name
        self._args: dict = {}

        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name.split(" (")[1][:-1],
            manufacturer="Ubiquiti",
            model=model,
        )

    @property
    def name(self) -> str:
        return self._attr_name

    async def async_press(self) -> None:
        _LOGGER.debug(
            "Button press %s on %s (args=%s)", self._action_name, self._device_id, self._args
        )
        await self._client.perform_action(self._device_id, self._action_name, self._args)
