# custom_components/unifi_connect_display/switch.py
import logging
from typing import Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)

# Accept either "power_*" or "display_*" as canonical on/off
_ON_KEYS = ("power_on", "display_on")
_OFF_KEYS = ("power_off", "display_off")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities: list[UniFiDisplayPowerSwitch] = []

    for dev in devices:
        model_key = dev.get("model") or dev.get("type", {}).get("name", "")
        if model_key not in ACTION_MAPS:
            continue

        actions = ACTION_MAPS[model_key]
        on_action = _first_present(actions, _ON_KEYS)
        off_action = _first_present(actions, _OFF_KEYS)

        # Only add a switch if we know how to turn it on AND off
        if not on_action or not off_action:
            _LOGGER.debug(
                "Skipping power switch for %s (%s): missing on/off actions",
                dev.get("name", model_key),
                model_key,
            )
            continue

        device_id = dev["id"]
        name = dev.get("name", model_key)

        entities.append(
            UniFiDisplayPowerSwitch(
                client=client,
                device_id=device_id,
                name=name,
                model=model_key,
                on_action=on_action,
                off_action=off_action,
            )
        )

    async_add_entities(entities, update_before_add=True)


def _first_present(mapping: dict, keys: tuple[str, ...]) -> Optional[str]:
    """Return the first key present in mapping from keys, else None."""
    for k in keys:
        if k in mapping:
            return k
    return None


class UniFiDisplayPowerSwitch(SwitchEntity):
    """Power/display switch that syncs with UniFi shadow.display."""

    _attr_should_poll = True
    _attr_icon = "mdi:power"

    def __init__(
        self,
        client: UniFiConnectClient,
        device_id: str,
        name: str,
        model: str,
        on_action: str,
        off_action: str,
    ):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._on_action = on_action
        self._off_action = off_action

        self._attr_name = name
        self._attr_unique_id = f"ucd_{device_id}_power"
        self._attr_available = True
        self._is_on = False

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Ubiquiti",
            model=model,
        )

        self._unsub_dispatcher = None

    # ─────────── Live push updates via dispatcher ───────────

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

    # ─────────────────────────── Read state ───────────────────────────

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_update(self) -> None:
        """Populate from cached device snapshot: shadow.display + online."""
        dev = self._client.get_cached_device(self._device_id)
        if not dev:
            # rare fallback: refresh cache once
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)

        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}

        # UniFi reports screen power as boolean "display"
        disp = shadow.get("display")
        if isinstance(disp, bool):
            self._is_on = disp

    # ─────────────────────────── Controls ───────────────────────────────

    async def async_turn_on(self, **kwargs):
        _LOGGER.debug("Turning ON %s (%s) via %s", self._attr_name, self._model, self._on_action)
        await self._client.perform_action(self._device_id, self._on_action)
        # optimistic; WS/refresh will correct quickly
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        _LOGGER.debug("Turning OFF %s (%s) via %s", self._attr_name, self._model, self._off_action)
        await self._client.perform_action(self._device_id, self._off_action)
        self._is_on = False
        self.async_write_ha_state()
