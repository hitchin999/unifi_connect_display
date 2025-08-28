# custom_components/unifi_connect_display/media_player.py

import logging
from typing import Optional

from aiohttp import ClientResponseError

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)


def _is_media_model(model: str) -> bool:
    """Return True if this model should expose a media_player (exclude Cast Pro)."""
    if model == "UC-Cast-Pro":
        return False
    actions = ACTION_MAPS.get(model, {})
    return "play" in actions and ("volume" in actions or "set_volume" in actions)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Connect media_player entities."""
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities: list[UniFiMediaPlayer] = []

    for dev in devices:
        model_key = dev.get("model") or dev.get("type", {}).get("name", "")
        if model_key == "UC-Cast-Pro":
            _LOGGER.debug("Skipping media_player for UC-Cast-Pro")
            continue
        if not _is_media_model(model_key):
            _LOGGER.debug("Skipping non-media model %s", model_key)
            continue

        device_id = dev["id"]
        device_name = dev.get("name", model_key)
        entities.append(UniFiMediaPlayer(client, device_id, device_name, model_key))

    async_add_entities(entities, update_before_add=True)


class UniFiMediaPlayer(MediaPlayerEntity):
    """Media player for UniFi Connect Display & (non-Pro) Cast devices."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    def __init__(self, client: UniFiConnectClient, device_id: str, device_name: str, model: str):
        self._client = client
        self._device_id = device_id
        self._model = model

        self._attr_name = f"Media ({device_name})"
        self._attr_unique_id = f"ucd_{device_id}_media"
        self._attr_state = MediaPlayerState.OFF
        self._attr_volume_level = 0.0
        self._attr_source: Optional[str] = None
        self._attr_source_list = ["Cast", "Website"]
        self._attr_available = True

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

        self._unsub_dispatcher = None

    # ─────────── Live push updates from UniFi WS via dispatcher ───────────

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
            # Re-poll from the client's cache and write state immediately
            self.async_schedule_update_ha_state(True)

    # ─────────────────────────── Reading state ────────────────────────────

    def _max_volume_for(self, dev: dict) -> int:
        """Device-reported max volume (featureFlags.volume.max or extraInfo.maxVolume) or default 100."""
        ff = (dev or {}).get("featureFlags") or {}
        vol = ff.get("volume") or {}
        if isinstance(vol, dict) and isinstance(vol.get("max"), int):
            return max(1, vol["max"])
        extra = (dev or {}).get("extraInfo") or {}
        if isinstance(extra.get("maxVolume"), int):
            return max(1, extra["maxVolume"])
        return 100

    async def async_update(self) -> None:
        """Populate HA state from the client's cached device snapshot."""
        dev = self._client.get_cached_device(self._device_id)
        if not dev:
            # Fall back (rare): refresh the cache once
            devices = await self._client.list_devices()
            for d in devices:
                if d.get("id") == self._device_id:
                    dev = d
                    break

        if not dev:
            self._attr_available = False
            return

        self._attr_available = bool(dev.get("online", True))
        shadow = dev.get("shadow") or {}

        # Power state derived from shadow.display (bool)
        display_on = shadow.get("display", True)
        mode = (shadow.get("mode") or "").lower()

        if not display_on:
            self._attr_state = MediaPlayerState.OFF
        else:
            # Heuristic: if the panel is on, consider it "playing" when in any app mode.
            if mode in ("digitalsignage", "web", "youtube", "layout"):
                self._attr_state = MediaPlayerState.PLAYING
            else:
                self._attr_state = MediaPlayerState.IDLE

        # Source mapping (keep your list: Cast / Website)
        if mode == "web":
            self._attr_source = "Website"
        else:
            # treat signage/youtube/other as "Cast"
            self._attr_source = "Cast"

        # Volume normalization
        raw_vol = shadow.get("volume")
        max_vol = self._max_volume_for(dev)
        if isinstance(raw_vol, (int, float)):
            self._attr_volume_level = max(0.0, min(1.0, float(raw_vol) / float(max_vol)))

    # ─────────────────────────── Controls ────────────────────────────────

    async def async_turn_on(self) -> None:
        """Turn the display on."""
        action_name = "display_on" if "display_on" in ACTION_MAPS[self._model] else "power_on"
        await self._client.perform_action(self._device_id, action_name)
        # Post-action: optimistic local state; WS will correct quickly
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn the display off."""
        action_name = "display_off" if "display_off" in ACTION_MAPS[self._model] else "power_off"
        await self._client.perform_action(self._device_id, action_name)
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Start media playback (signage/cast) for supported models."""
        await self._client.perform_action(self._device_id, "play")
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Pause media (fallback to stop)."""
        # Many models only expose stop; use it as pause.
        await self._client.perform_action(self._device_id, "stop")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop media."""
        await self._client.perform_action(self._device_id, "stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume as 0..1 normalized to device scale."""
        cmd_name = "volume" if "volume" in ACTION_MAPS[self._model] else "set_volume"

        # Normalize to device max (featureFlags.volume.max or extraInfo.maxVolume)
        dev = self._client.get_cached_device(self._device_id) or {}
        max_vol = self._max_volume_for(dev)
        val = int(max(0, min(max_vol, round(volume * max_vol))))

        try:
            await self._client.perform_action(self._device_id, cmd_name, {"value": val})
        except ClientResponseError as e:
            if e.status != 404:
                _LOGGER.warning("Volume set failed for %s: %s", self._attr_name, e)
        self._attr_volume_level = max(0.0, min(1.0, volume))
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Select input source (UI only; actual switch happens when you call play/website)."""
        self._attr_source = source
        self.async_write_ha_state()

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Play a URL (website) if supported; otherwise trigger generic play."""
        if media_type == "website" and "load_website" in ACTION_MAPS.get(self._model, {}):
            await self._client.perform_action(
                self._device_id, "load_website", {"url": media_id}
            )
            self._attr_state = MediaPlayerState.PLAYING
            self._attr_source = "Website"
        else:
            await self._client.perform_action(self._device_id, "play")
            self._attr_state = MediaPlayerState.PLAYING
            self._attr_source = "Cast"
        self.async_write_ha_state()
