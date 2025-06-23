# custom_components/unifi_connect_display/media_player.py

import logging
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

from .api import UniFiConnectClient
from .const import DOMAIN, ACTION_MAPS

_LOGGER = logging.getLogger(__name__)


def _is_media_model(model: str) -> bool:
    """Return True if this model supports play + volume actions."""
    return "play" in ACTION_MAPS.get(model, {}) and (
        "volume" in ACTION_MAPS[model] or "set_volume" in ACTION_MAPS[model]
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Connect media_player entities."""
    client: UniFiConnectClient = hass.data[DOMAIN][entry.entry_id]
    devices = await client.list_devices()
    entities = []

    for dev in devices:
        raw_model = dev.get("model") or dev.get("type", {}).get("name", "")
        if not _is_media_model(raw_model):
            _LOGGER.debug("Skipping non-media model %s", raw_model)
            continue

        device_id = dev["id"]
        device_name = dev.get("name", raw_model)
        entities.append(UniFiMediaPlayer(client, device_id, device_name, raw_model))

    async_add_entities(entities, True)


class UniFiMediaPlayer(MediaPlayerEntity):
    """Media player for UniFi Connect Display & Cast devices."""

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

    def __init__(self, client, device_id, device_name, model):
        self._client = client
        self._device_id = device_id
        self._model = model

        # Prefix “Media (… )” so HA doesn’t strip our device_name
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

    async def async_update(self):
        """Fetch current power & brightness (as volume) from the device."""
        try:
            action = ACTION_MAPS[self._model].get("switch", ACTION_MAPS[self._model]["play"])
            data = await self._client.perform_action(self._device_id, action)

            # Power state → IDLE / OFF
            self._attr_state = (
                MediaPlayerState.IDLE if data.get("powerState") == "ON" else MediaPlayerState.OFF
            )

            # Brightness ↔ volume_level
            bri = data.get("brightness")
            if bri is not None:
                self._attr_volume_level = bri / 100.0

        except ClientResponseError as e:
            # some models (e.g. Cast-Pro) don't support switch → ignore 404
            if e.status != 404:
                _LOGGER.warning("Media update failed for %s: %s", self._attr_name, e)
        except Exception as e:
            _LOGGER.warning("Media update failed for %s: %s", self._attr_name, e)

    async def async_turn_on(self) -> None:
        """Turn the display on."""
        action = ACTION_MAPS[self._model].get("display_on", ACTION_MAPS[self._model]["power_on"])
        await self._client.perform_action(self._device_id, action)
        self._attr_state = MediaPlayerState.IDLE

    async def async_turn_off(self) -> None:
        """Turn the display off."""
        action = ACTION_MAPS[self._model].get("display_off", ACTION_MAPS[self._model]["power_off"])
        await self._client.perform_action(self._device_id, action)
        self._attr_state = MediaPlayerState.OFF

    async def async_media_play(self) -> None:
        """Start media playback (cast)."""
        await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["play"])
        self._attr_state = MediaPlayerState.PLAYING

    async def async_media_pause(self) -> None:
        """Pause media (fallback to stop)."""
        await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["stop"])
        self._attr_state = MediaPlayerState.PAUSED

    async def async_media_stop(self) -> None:
        """Stop media."""
        await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["stop"])
        self._attr_state = MediaPlayerState.IDLE

    async def async_set_volume_level(self, volume: float) -> None:
        """Set brightness-as-volume."""
        val = int(volume * 100)
        key = "volume" if "volume" in ACTION_MAPS[self._model] else "set_volume"
        try:
            await self._client.perform_action(
                self._device_id, ACTION_MAPS[self._model][key], f"\"value\":{val}"
            )
        except ClientResponseError as e:
            if e.status != 404:
                _LOGGER.warning("Volume set failed for %s: %s", self._attr_name, e)
        self._attr_volume_level = volume

    async def async_select_source(self, source: str) -> None:
        """Select input source (cast vs website)."""
        self._attr_source = source

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Play a URL (website) or cast default."""
        if media_type == "website" and "load_website" in ACTION_MAPS[self._model]:
            await self._client.perform_action(
                self._device_id,
                ACTION_MAPS[self._model]["load_website"],
                f"\"url\":\"{media_id}\"",
            )
            self._attr_state = MediaPlayerState.PLAYING
            self._attr_source = "Website"
        else:
            await self._client.perform_action(self._device_id, ACTION_MAPS[self._model]["play"])
            self._attr_state = MediaPlayerState.PLAYING
            self._attr_source = "Cast"
