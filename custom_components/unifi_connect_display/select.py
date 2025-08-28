# custom_components/unifi_connect_display/select.py

import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)


def _friendly_playlist_label(pl: dict) -> str:
    """
    Build a human-readable label for a playlist/media entry.
    - MEDIA with one asset -> "Media: <asset name>"
    - PLAYLIST with a distinct name -> "<name>"
    - fallback -> id
    """
    pl_id = pl.get("id") or ""
    pl_type = (pl.get("type") or "").upper()
    name = pl.get("name") or ""
    contents = pl.get("contents") or []

    if pl_type == "MEDIA":
        if contents:
            first = contents[0] or {}
            asset = first.get("asset") or {}
            asset_name = asset.get("name")
            if asset_name:
                return f"Media: {asset_name}"
        return name or pl_id

    if pl_type == "PLAYLIST" and name and name != pl_id:
        return name

    return name or pl_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]

    devices = await client.list_devices()
    playlists_resp = await client.list_playlists()
    playlists = playlists_resp.get("data", []) if isinstance(playlists_resp, dict) else []

    # Precompute display labels in a stable order
    labeled_playlists = []
    for pl in playlists:
        label = _friendly_playlist_label(pl)
        labeled_playlists.append({"label": label, "id": pl.get("id")})

    entities: list[SelectEntity] = []

    for dev in devices:
        model = dev.get("model") or dev.get("type", {}).get("name", "")
        if model not in ACTION_MAPS:
            continue

        device_id = dev["id"]
        device_name = dev.get("name", model)
        actions = ACTION_MAPS[model]
        shadow = dev.get("shadow") or {}
        current_playlist_id = shadow.get("playlistId")

        if "rotate" in actions:
            entities.append(UniFiRotateSelect(client, device_id, device_name, model))

        if "play" in actions and labeled_playlists:
            entities.append(
                UniFiPlaylistSelect(
                    client,
                    device_id,
                    device_name,
                    model,
                    labeled_playlists,
                    current_playlist_id,
                )
            )

        if "switch" in actions:
            entities.append(UniFiSwitchModeSelect(client, device_id, device_name, model))

    # Important: update_before_add so UI shows current values immediately
    async_add_entities(entities, update_before_add=True)


# ───────────────────────── Base with push updates ─────────────────────────

class _BaseUcdSelect(SelectEntity):
    _attr_should_poll = True  # we still implement async_update

    def __init__(self, client: UniFiConnectClient, device_id: str, device_name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._model = model
        self._attr_available = True
        self._unsub_dispatcher = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

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

    def _get_cached(self) -> Optional[dict]:
        return self._client.get_cached_device(self._device_id)


# ───────────────────────── Rotate select ─────────────────────────

class UniFiRotateSelect(_BaseUcdSelect):
    """Select for screen rotation with friendly names."""

    # Friendly -> raw mapping used by UniFi API
    _mapping = {
        "Landscape": "landscapePrim",
        "Portrait": "portraitPrim",
        "Landscape (flipped)": "landscapeSec",
        "Portrait (flipped)": "portraitSec",
    }
    _inv = {v: k for k, v in _mapping.items()}

    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_name = f"Rotate Mode ({name})"
        self._attr_unique_id = f"ucd_{device_id}_rotate_select"
        self._attr_options = list(self._mapping.keys())
        self._attr_current_option = None

    async def async_update(self) -> None:
        dev = self._get_cached()
        if not dev:
            # rare: cache cold, try to warm it
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)
        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}
        raw = shadow.get("rotate")
        label = self._inv.get(raw)
        # Fallback: keep previous selection if raw is unknown
        if label:
            self._attr_current_option = label

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


# ───────────────────────── Playlist select ─────────────────────────

class UniFiPlaylistSelect(_BaseUcdSelect):
    """Select for signage playlists with human-readable labels."""

    def __init__(self, client, device_id, name, model, labeled_playlists, current_playlist_id: str | None):
        super().__init__(client, device_id, name, model)

        # labeled_playlists is a list of {"label": str, "id": str}
        self._label_to_id = {item["label"]: item["id"] for item in labeled_playlists}
        self._id_to_label = {v: k for k, v in self._label_to_id.items()}

        self._attr_options = list(self._label_to_id.keys())
        self._attr_name = f"Playlist ({name})"
        self._attr_unique_id = f"ucd_{device_id}_playlist_select"

        if current_playlist_id and current_playlist_id in self._id_to_label:
            self._attr_current_option = self._id_to_label[current_playlist_id]
        else:
            self._attr_current_option = None

    async def async_update(self) -> None:
        dev = self._get_cached()
        if not dev:
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)
        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        pl_id = (dev.get("shadow") or {}).get("playlistId")
        if pl_id and pl_id in self._id_to_label:
            self._attr_current_option = self._id_to_label[pl_id]

    async def async_select_option(self, option: str) -> None:
        pl_id = self._label_to_id.get(option)
        if not pl_id:
            return
        await self._client.perform_action(
            self._device_id,
            "play",
            {"playlistId": pl_id},
        )
        self._attr_current_option = option


# ───────────────────────── Mode select ─────────────────────────

class UniFiSwitchModeSelect(_BaseUcdSelect):
    """Select for device operating mode (friendly names)."""

    # Friendly -> raw mapping
    _mapping = {
        "Web": "web",
        "Media": "digitalSignage",
        "YouTube": "youtube",
    }
    _inv = {v: k for k, v in _mapping.items()}

    def __init__(self, client, device_id, name, model):
        super().__init__(client, device_id, name, model)
        self._attr_name = f"Switch Mode ({name})"
        self._attr_unique_id = f"ucd_{device_id}_switch_mode_select"
        self._attr_options = list(self._mapping.keys())
        self._attr_current_option = None

    async def async_update(self) -> None:
        dev = self._get_cached()
        if not dev:
            devices = await self._client.list_devices()
            dev = next((d for d in devices if d.get("id") == self._device_id), None)
        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}
        raw = (shadow.get("mode") or "").strip()
        label = self._inv.get(raw)
        if label:
            self._attr_current_option = label

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
