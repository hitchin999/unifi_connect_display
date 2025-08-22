# custom_components/unifi_connect_display/select.py

import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    playlists_resp = await client.list_playlists()
    playlists = playlists_resp.get("data", []) if isinstance(playlists_resp, dict) else []

    entities: list[SelectEntity] = []

    for dev in devices:
        model = dev.get("model") or dev.get("type", {}).get("name", "")
        if model not in ACTION_MAPS:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", model)
        actions = ACTION_MAPS[model]

        # Rotate Mode select (if supported)
        if "rotate" in actions:
            entities.append(
                UniFiRotateSelect(client, device_id, device_name, model)
            )

        # Playlist select (Signage) (if supported and playlists exist)
        if "play" in actions and playlists:
            entities.append(
                UniFiPlaylistSelect(client, device_id, device_name, model, playlists)
            )

        # Switch Mode select (if supported)
        if "switch" in actions:
            entities.append(
                UniFiSwitchModeSelect(client, device_id, device_name, model)
            )

    async_add_entities(entities)


class UniFiRotateSelect(SelectEntity):
    """Select for screen rotation with friendly names."""

    # Friendly -> raw mapping used by UniFi API
    _mapping = {
        "Landscape": "landscapePrim",
        "Portrait": "portraitPrim",
        "Landscape (flipped)": "landscapeSec",
        "Portrait (flipped)": "portraitSec",
    }

    def __init__(self, client, device_id, name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_name = f"Rotate Mode ({name})"
        self._attr_unique_id = f"ucd_{device_id}_rotate_select"
        self._attr_options = list(self._mapping.keys())
        self._attr_current_option = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Ubiquiti",
            model=model,
        )

    async def async_select_option(self, option: str) -> None:
        raw = self._mapping.get(option)
        if not raw:
            return
        await self._client.perform_action(
            self._device_id,
            "rotate",
            {"scale": raw},
        )
        self._attr_current_option = option


class UniFiPlaylistSelect(SelectEntity):
    """Select for signage playlists."""

    def __init__(self, client, device_id, name, model, playlists):
        self._client = client
        self._device_id = device_id
        self._model = model
        # map display name -> id
        self._playlists = {pl.get("name") or pl.get("id"): pl.get("id") for pl in playlists}
        self._attr_options = list(self._playlists.keys())
        self._attr_name = f"Playlist ({name})"
        self._attr_unique_id = f"ucd_{device_id}_playlist_select"
        self._attr_current_option = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Ubiquiti",
            model=model,
        )

    async def async_select_option(self, option: str) -> None:
        pl_id = self._playlists.get(option)
        if not pl_id:
            return
        await self._client.perform_action(
            self._device_id,
            "play",
            {"playlistId": pl_id},
        )
        self._attr_current_option = option


class UniFiSwitchModeSelect(SelectEntity):
    """Select for device operating mode (friendly names)."""

    # Friendly -> raw mapping
    _mapping = {
        "Web": "web",
        "Media": "digitalSignage",
        "YouTube": "youtube",
    }

    def __init__(self, client, device_id, name, model):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_name = f"Switch Mode ({name})"
        self._attr_unique_id = f"ucd_{device_id}_switch_mode_select"
        self._attr_options = list(self._mapping.keys())
        self._attr_current_option = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Ubiquiti",
            model=model,
        )

    async def async_select_option(self, option: str) -> None:
        raw = self._mapping.get(option)
        if not raw:
            return
        await self._client.perform_action(
            self._device_id,
            "switch",
            {"mode": raw},
        )
        self._attr_current_option = option
