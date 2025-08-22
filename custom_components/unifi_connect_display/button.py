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

    # Devices + playlists
    devices = await client.list_devices()
    playlists_resp = await client.list_playlists()
    playlists = playlists_resp.get("data", []) if isinstance(playlists_resp, dict) else []

    entities: list[UniFiDisplayButton] = []

    for dev in devices:
        model_key = dev.get("model") or dev.get("type", {}).get("name", "")
        if model_key not in ACTION_MAPS:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", model_key)

        # Build buttons per action_name in ACTION_MAPS for this model
        for action_name in ACTION_MAPS[model_key].keys():

            # --- Dynamic PLAY buttons for each playlist (no generic "Play") ---
            if action_name == "play":
                for pl in playlists:
                    pl_id = pl.get("id")
                    pl_name = pl.get("name") or pl_id
                    if not pl_id:
                        continue
                    name = f"Play: {pl_name} ({device_name})"
                    unique_id = f"ucd_{device_id}_play_{pl_id}"
                    btn = UniFiDisplayButton(
                        client=client,
                        device_id=device_id,
                        model=model_key,
                        action_name="play",
                        name=name,
                        unique_id=unique_id,
                    )
                    btn._args = {"playlistId": pl_id}
                    entities.append(btn)
                # Skip adding a generic "Play" button
                continue

            # --- STOP signage button (no args) ---
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

            # --- Extras for switch (arg-specific only) ---
            if action_name == "switch":
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
                # Skip adding a generic "Switch" button
                continue

            # --- Extras for rotate (arg-specific only) ---
            if action_name == "rotate":
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
                # Skip adding a generic "Rotate" button
                continue

            # --- Never create a generic "Volume" button (volume is a Number entity) ---
            if action_name in ("volume", "set_volume"):
                continue

            # --- Default button (no args) for everything else (e.g., display_on/off, reboot, locating) ---
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
        self._args: dict = {}  # optional args (e.g., {"mode":"web"}, {"playlistId": "..."})

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
        _LOGGER.debug(
            "Button press %s on %s (args=%s)", self._action_name, self._device_id, self._args
        )
        await self._client.perform_action(self._device_id, self._action_name, self._args)
