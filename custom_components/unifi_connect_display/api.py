# custom_components/unifi_connect_display/api.py

import asyncio
import json
import logging
import time
from typing import Optional, Dict, List

import aiohttp
from aiohttp import ClientResponseError, TCPConnector
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import ACTION_MAPS, SIGNAL_DEVICE_UPDATE

_LOGGER = logging.getLogger(__name__)


class UniFiConnectClient:
    """Handles authentication, API calls, WebSocket updates, and an optimistic overlay."""

    def __init__(self, hass, host: str, username: str, password: str, site: str | None = None):
        self.hass = hass
        self.host = host
        self.base = f"https://{host}"
        self.username = username
        self.password = password
        self.site = site or "default"
        self._session: aiohttp.ClientSession | None = None
        self._csrf_token: str | None = None

        # Local device cache (id -> device dict)
        self._device_cache: Dict[str, dict] = {}

        # Optimistic shadow overlays (id -> shadow patch) with expiry
        self._optimistic: Dict[str, dict] = {}
        self._optimistic_expiry: Dict[str, float] = {}

        # WebSocket state
        self._ws_task: asyncio.Task | None = None
        self._stop_ws = asyncio.Event()
        self._ws_url = f"{self.base}/api/ws/system"

        # Throttle refreshes triggered by WS bursts
        self._refresh_lock = asyncio.Lock()

    # ─────────────────────────── Auth / Session ───────────────────────────

    async def login(self) -> None:
        """Authenticate and capture CSRF token (reuse cookie jar for WS)."""
        self._session = aiohttp.ClientSession(
            connector=TCPConnector(force_close=True),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        for path, payload in [
            ("/auth", {"Username": self.username, "Password": self.password}),
            ("/api/auth", {"Username": self.username, "Password": self.password}),
            ("/api/auth", {"username": self.username, "password": self.password}),
            ("/api/auth/login", {"username": self.username, "password": self.password}),
        ]:
            url = f"{self.base}{path}"
            _LOGGER.debug("Trying login endpoint %s", url)
            try:
                resp = await self._session.post(url, json=payload, headers=headers, ssl=False)
                if resp.status in (404, 405, 401):
                    _LOGGER.debug("%s returned %s", url, resp.status)
                    continue
                resp.raise_for_status()
                _LOGGER.debug("Logged in via %s", path)

                # CSRF
                token = resp.headers.get("X-Csrf-Token")
                if not token:
                    try:
                        data = await resp.json()
                        token = data.get("csrfToken")
                    except Exception:
                        token = None
                self._csrf_token = token
                _LOGGER.debug("CSRF token set to %s", token)
                return
            except ClientResponseError as e:
                _LOGGER.warning("Login at %s failed: %s", url, e)
            except Exception as e:
                _LOGGER.error("Error contacting %s: %s", url, e)

        raise RuntimeError("All login attempts failed")

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._csrf_token:
            h["X-Csrf-Token"] = self._csrf_token
        return h

    async def _request(self, method: str, url: str, **kwargs):
        return await getattr(self._session, method)(url, headers=self._headers(), ssl=False, **kwargs)

    # ─────────────────────────────── REST ────────────────────────────────

    async def list_sites(self) -> list[dict]:
        url = f"{self.base}/api/sites"
        resp = await self._request("get", url)
        resp.raise_for_status()
        return await resp.json()

    async def perform_action(self, device_id: str, action_name: str, args: dict | None = None):
        """
        Send a Connect action by PATCHing the device's /status endpoint.

        1) Look up device model (e.g., "UC-Cast-Pro")
        2) Resolve action UUID from ACTION_MAPS[model][action_name]
        3) PATCH /proxy/connect/api/v2/devices/{device_id}/status
           body: {"id": "<uuid>", "name": "<action_name>", "args": {...}}
        4) Apply a short-lived optimistic overlay to avoid UI bounce
        """
        if args is None:
            args = {}

        # 1) fetch device (to get model key)
        dev_url = f"{self.base}/proxy/connect/api/v2/devices/{device_id}"
        dev_resp = await self._session.get(dev_url, headers=self._headers(), ssl=False)
        dev_resp.raise_for_status()
        dev_data = await dev_resp.json()

        try:
            model_key = dev_data["data"]["type"]["name"]
        except Exception as e:
            raise ValueError(f"Could not determine device model for {device_id}: {e}")

        # 2) resolve action
        try:
            action_id = ACTION_MAPS[model_key][action_name]
        except KeyError:
            raise ValueError(f"Unsupported action '{action_name}' for model '{model_key}'")

        # 3) send action
        url = f"{self.base}/proxy/connect/api/v2/devices/{device_id}/status"
        payload = {"id": action_id, "name": action_name, "args": args}

        resp = await self._session.patch(url, json=payload, headers=self._headers(), ssl=False)
        resp.raise_for_status()
        result = await resp.json()

        # 4) optimistic overlay (3–5s) to prevent UI bounce
        try:
            patch = self._make_optimistic_patch(action_name, args)
            if patch:
                self._set_optimistic(device_id, patch, ttl=4.0)
        except Exception as e:
            _LOGGER.debug("Optimistic patch failed (non-fatal): %s", e)

        # Schedule a delayed refresh so cache converges to real shadow
        try:
            self.hass.loop.call_later(
                2.0,
                lambda: self.hass.async_create_task(self._refresh_devices_and_notify())
            )
        except Exception as e:
            _LOGGER.debug("Post-action delayed refresh scheduling failed (non-fatal): %s", e)

        return result

    def _make_optimistic_patch(self, action_name: str, args: dict) -> Optional[dict]:
        """Translate an action into a shadow patch."""
        shadow = {}

        # Power / display
        if action_name in ("display_on", "power_on"):
            shadow["display"] = True
        elif action_name in ("display_off", "power_off"):
            shadow["display"] = False

        # Volume
        elif action_name in ("volume", "set_volume"):
            if "value" in args:
                shadow["volume"] = int(args["value"])

        # Rotate
        elif action_name == "rotate":
            scale = args.get("scale")
            if isinstance(scale, str):
                shadow["rotate"] = scale

        # Mode switch
        elif action_name == "switch":
            mode = args.get("mode")
            if isinstance(mode, str):
                shadow["mode"] = mode

        # Website / YouTube loaders imply mode too
        elif action_name == "load_website":
            url = args.get("url")
            if isinstance(url, str):
                shadow["mode"] = "web"
                shadow["currentHomePage"] = url
        elif action_name == "load_youtube":
            url = args.get("url")
            if isinstance(url, str):
                shadow["mode"] = "youtube"
                shadow["currentYouTubePage"] = url

        # Signage play implies digitalSignage + playlistId
        elif action_name == "play":
            pl = args.get("playlistId")
            if isinstance(pl, str):
                shadow["mode"] = "digitalSignage"
                shadow["playlistId"] = pl

        # Stop -> heuristically keep display on; do not change mode
        elif action_name == "stop":
            # no-op: avoid lying about mode; WS/refresh will fix
            pass

        return shadow or None

    async def list_playlists(self) -> dict:
        """Return Connect playlists JSON."""
        url = f"{self.base}/proxy/connect/api/v2/playlists"
        resp = await self._session.get(url, headers=self._headers(), ssl=False)
        resp.raise_for_status()
        return await resp.json()

    async def list_devices(self) -> List[dict]:
        """
        Primary path: /proxy/connect/api/v2/devices?shadow=true
        Falls back to older endpoints if needed.
        Updates local cache before returning (no optimistic merge here).
        """
        # 1) SHADOW endpoint
        shadow_url = f"{self.base}/proxy/connect/api/v2/devices?shadow=true"
        _LOGGER.debug("Trying shadow collection endpoint: %s", shadow_url)
        try:
            resp = await self._session.get(shadow_url, headers=self._headers(), ssl=False)
            if resp.status == 200:
                body = await resp.json()
                if body.get("type") == "collection" and isinstance(body.get("data"), list):
                    devices = body["data"]
                    self._update_cache(devices)
                    _LOGGER.debug("→ Got %d devices from shadow=true", len(devices))
                    return [self._merge_with_optimistic(d) for d in devices]
        except Exception as e:
            _LOGGER.debug("  shadow endpoint failed: %s", e)

        # 2) Proxy list endpoints
        for path in ("/proxy/connect/api/v1/displays", "/proxy/connect/api/v2/displays"):
            url = f"{self.base}{path}"
            _LOGGER.debug("Trying proxy list endpoint: %s", url)
            try:
                resp = await self._session.get(url, headers=self._headers(), ssl=False)
                if resp.status != 200:
                    continue
                data = await resp.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    self._update_cache(data)
                    _LOGGER.debug("→ Got %d display objects", len(data))
                    return [self._merge_with_optimistic(d) for d in data]
                if isinstance(data, list) and all(isinstance(i, str) for i in data):
                    _LOGGER.debug("→ Proxy gave %d IDs", len(data))
                    devices = await self._fetch_settings(data)
                    self._update_cache(devices)
                    return [self._merge_with_optimistic(d) for d in devices]
            except Exception as e:
                _LOGGER.debug("  proxy list %s failed: %s", url, e)

        # 3) Discovered‐POST endpoints
        for path in (
            f"/proxy/connect/api/v2/sites/{self.site}/devices/discovered",
            f"/proxy/connect/api/v1/sites/{self.site}/devices/discovered",
            "/proxy/connect/api/v2/devices/discovered",
            "/proxy/connect/api/v1/devices/discovered",
        ):
            url = f"{self.base}{path}"
            _LOGGER.debug("Trying discovered POST endpoint: %s", url)
            try:
                resp = await self._session.post(url, json={}, headers=self._headers(), ssl=False)
                if resp.status != 200:
                    continue
                payload = await resp.json()
                ids = payload if isinstance(payload, list) else payload.get("data")
                if isinstance(ids, list) and all(isinstance(i, str) for i in ids):
                    _LOGGER.debug("→ Discovered %d IDs", len(ids))
                    devices = await self._fetch_settings(ids)
                    self._update_cache(devices)
                    return [self._merge_with_optimistic(d) for d in devices]
            except Exception as e:
                _LOGGER.debug("  discovery %s failed: %s", url, e)

        # 4) UI JSON “site-settings”
        ui_url = f"{self.base}/connect/displays/devices/all/{self.site}/settings"
        _LOGGER.debug("Trying site-settings endpoint: %s", ui_url)
        try:
            resp = await self._session.get(ui_url, headers=self._headers(), ssl=False)
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    self._update_cache(data)
                    _LOGGER.debug("→ Got %d display settings via UI JSON", len(data))
                    return [self._merge_with_optimistic(d) for d in data]
        except Exception as e:
            _LOGGER.debug("  site-settings %s failed: %s", ui_url, e)

        _LOGGER.warning("No displays found via any endpoint, returning empty list")
        return []

    async def _fetch_settings(self, ids: List[str]) -> List[dict]:
        """Fetch each discovered display’s settings dict."""
        devices: List[dict] = []
        for display_id in ids:
            for candidate in (
                f"/proxy/connect/api/v2/displays/devices/{display_id}/settings",
                f"/proxy/connect/api/v1/displays/devices/{display_id}/settings",
                f"/connect/displays/devices/all/{display_id}/settings",
            ):
                url = f"{self.base}{candidate}"
                _LOGGER.debug("  Fetching settings %s", url)
                try:
                    resp = await self._session.get(url, headers=self._headers(), ssl=False)
                    if resp.status != 200:
                        continue
                    obj = await resp.json()
                    if isinstance(obj, dict):
                        devices.append(obj)
                        break
                except Exception as e:
                    _LOGGER.debug("    settings %s errored: %s", url, e)
        if not devices:
            _LOGGER.warning("No display settings could be fetched")
        return devices

    def _update_cache(self, devices: List[dict]) -> None:
        """Update local cache with a list of device dicts (raw, no optimistic)."""
        for d in devices:
            did = d.get("id")
            if did:
                self._device_cache[did] = d

    # Public helpers for entities (merged with optimistic)
    def get_cached_device(self, device_id: str) -> Optional[dict]:
        dev = self._device_cache.get(device_id)
        if not dev:
            return None
        return self._merge_with_optimistic(dev)

    def get_cached_devices(self) -> List[dict]:
        return [self._merge_with_optimistic(d) for d in self._device_cache.values()]

    # ───────────────────── Optimistic overlay helpers ─────────────────────

    def _set_optimistic(self, device_id: str, shadow_patch: dict, ttl: float = 4.0) -> None:
        """Apply a temporary shadow patch and notify entities immediately."""
        now = time.monotonic()
        self._optimistic[device_id] = shadow_patch
        self._optimistic_expiry[device_id] = now + max(0.5, ttl)
        # Notify subscribers so HA re-reads from cache (now reflecting optimistic state)
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE, device_id)

    def _merge_with_optimistic(self, dev: dict) -> dict:
        """Return a shallow copy of device with optimistic shadow patch applied (if not expired)."""
        did = dev.get("id")
        if not did:
            return dev

        patch = self._optimistic.get(did)
        expiry = self._optimistic_expiry.get(did, 0.0)

        # Expired? drop it.
        if patch and time.monotonic() > expiry:
            self._optimistic.pop(did, None)
            self._optimistic_expiry.pop(did, None)
            patch = None

        if not patch:
            return dev

        # Merge only into the shadow object
        new_dev = dict(dev)
        base_shadow = dict((dev.get("shadow") or {}))
        base_shadow.update(patch)
        new_dev["shadow"] = base_shadow
        return new_dev

    # ─────────────────────────── WebSocket (push) ─────────────────────────

    async def start_ws(self) -> None:
        """Start the WebSocket listener (idempotent)."""
        if self._ws_task:
            return
        self._stop_ws.clear()
        self._ws_task = self.hass.loop.create_task(self._ws_loop())

    async def stop_ws(self) -> None:
        """Stop the WebSocket listener."""
        self._stop_ws.set()
        if self._ws_task:
            try:
                await asyncio.wait_for(self._ws_task, timeout=5)
            except Exception:
                pass
            self._ws_task = None

    async def _ws_loop(self) -> None:
        """Connect to UniFi /api/ws/system and coalesce device-change events."""
        if not self._session:
            _LOGGER.warning("WS not started: no session")
            return

        backoff = 2
        while not self._stop_ws.is_set():
            try:
                async with self._session.ws_connect(
                    self._ws_url,
                    headers={"Origin": self.base},
                    ssl=False,
                ) as ws:
                    _LOGGER.info("Connected to UniFi WS: %s", self._ws_url)
                    backoff = 2
                    async for msg in ws:
                        if self._stop_ws.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except Exception as e:
                if self._stop_ws.is_set():
                    break
                _LOGGER.warning("WS error (%s). Reconnecting in %ss", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

        _LOGGER.info("WS loop stopped")

    async def _handle_ws_message(self, data: str) -> None:
        """Handle WS message: when device state changes, refresh and broadcast."""
        try:
            payload = json.loads(data)
        except Exception:
            return

        ev_type = payload.get("type", "")
        if not ev_type:
            return

        # Heuristic: most device changes contain DEVICE / CHANGED / APPLIED
        if "DEVICE" in ev_type or "CHANGED" in ev_type or "APPLIED" in ev_type:
            await self._schedule_refresh_and_broadcast()

    async def _schedule_refresh_and_broadcast(self) -> None:
        # Coalesce and allow the controller to settle a bit before we read
        async with self._refresh_lock:
            await asyncio.sleep(0.8)  # settle time; adjust 0.5–1.0s if needed
            await self._refresh_devices_and_notify()

    async def _refresh_devices_and_notify(self) -> None:
        """Refresh cache and broadcast per-device updates."""
        devices = await self.list_devices()  # list_devices already merges optimistic
        # If the controller has now published the real shadow, our optimistic
        # patch will expire naturally; just broadcast updates.
        for d in devices:
            did = d.get("id")
            if did:
                async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATE, did)

    # ───────────────────────────── Cleanup ────────────────────────────────

    async def close(self) -> None:
        """Close WS and the aiohttp session."""
        await self.stop_ws()
        if self._session:
            _LOGGER.debug("Closing UniFi Connect HTTP session")
            await self._session.close()
            self._session = None
