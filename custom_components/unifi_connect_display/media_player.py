# custom_components/unifi_connect_display/media_player.py

import logging
from aiohttp import ClientResponseError

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
    # noqa: E402
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

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

    async_add_entities(entities, True)


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
        self._attr_source = None
        self._attr_source_list = ["Cast", "Website"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Ubiquiti",
            model=model,
        )

    async def async_update(self) -> None:
        """Optional: populate state if you later add a GET/status helper."""
        # No reliable read endpoint via perform_action; skip to avoid side effects.
        return

    async def async_turn_on(self) -> None:
        """Turn the display on."""
        action_name = "display_on" if "display_on" in ACTION_MAPS[self._model] else "power_on"
        await self._client.perform_action(self._device_id, action_name)
        self._attr_state = MediaPlayerState.IDLE

    async def async_turn_off(self) -> None:
        """Turn the display off."""
        action_name = "display_off" if "display_off" in ACTION_MAPS[self._model] else "power_off"
        await self._client.perform_action(self._device_id, action_name)
        self._attr_state = MediaPlayerState.OFF

    async def async_media_play(self) -> None:
        """Start media playback (signage/cast) for supported models."""
        await self._client.perform_action(self._device_id, "play")
        self._attr_state = MediaPlayerState.PLAYING

    async def async_media_pause(self) -> None:
        """Pause media (fallback to stop)."""
        # Many models only expose stop; use it as pause.
        await self._client.perform_action(self._device_id, "stop")
        self._attr_state = MediaPlayerState.PAUSED

    async def async_media_stop(self) -> None:
        """Stop media."""
        await self._client.perform_action(self._device_id, "stop")
        self._attr_state = MediaPlayerState.IDLE

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume/brightness as 0..1 -> device scale."""
        # Most displays use 0..100; some connectors use 0..40. Round and clamp optimistically.
        # We’ll send in the device’s expected action by name; mapping to UUID happens in the client.
        cmd_name = "volume" if "volume" in ACTION_MAPS[self._model] else "set_volume"
        # Default to a 0..100 scale for non-Cast-Pro media models.
        val = int(max(0, min(100, round(volume * 100))))
        try:
            await self._client.perform_action(self._device_id, cmd_name, {"value": val})
        except ClientResponseError as e:
            if e.status != 404:
                _LOGGER.warning("Volume set failed for %s: %s", self._attr_name, e)
        self._attr_volume_level = max(0.0, min(1.0, volume))
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Select input source (UI only; actual switch is done in async_play_media for 'website')."""
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
