# custom_components/unifi_connect_display/api.py

import logging
import aiohttp
from aiohttp import ClientResponseError

_LOGGER = logging.getLogger(__name__)

class UniFiConnectClient:
    """Handles authentication and API calls to UniFi Connect."""

    def __init__(self, hass, host: str, username: str, password: str, site: str | None = None):
        self.hass = hass
        self.host = host
        self.base = f"https://{host}"
        self.username = username
        self.password = password
        self.site = site or "default"
        self._session: aiohttp.ClientSession | None = None
        self._csrf_token: str | None = None

    async def login(self) -> None:
        """Authenticate like the Groovy driver and capture CSRF token."""
        self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
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

                # Grab CSRF
                token = resp.headers.get("X-Csrf-Token")
                if not token:
                    data = await resp.json()
                    token = data.get("csrfToken")
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

    async def list_sites(self) -> list[dict]:
        url = f"{self.base}/api/sites"
        resp = await self._request("get", url)
        resp.raise_for_status()
        return await resp.json()

    async def perform_action(self, device_id: str, action_id: str, args: str | None = None) -> dict:
        url = f"{self.base}/proxy/connect/api/v2/actions?deviceId={device_id}"
        payload = {"actionId": action_id}
        if args:
            payload["args"] = args
        resp = await self._request("post", url, json=payload)
        resp.raise_for_status()
        return await resp.json()

    async def list_devices(self) -> list[dict]:
        """
        Discover and fetch each display’s settings via:
          1) the new /devices?shadow=true endpoint
          2) proxy list endpoints
          3) discovered‐POST endpoints
          4) UI JSON site‐settings
        """
        # ─── 1) SHADOW endpoint ──────────────────────────────────────────────────────
        shadow_url = f"{self.base}/proxy/connect/api/v2/devices?shadow=true"
        _LOGGER.debug("Trying shadow collection endpoint: %s", shadow_url)
        try:
            resp = await self._session.get(shadow_url, headers=self._headers(), ssl=False)
            if resp.status == 200:
                body = await resp.json()
                if body.get("type") == "collection" and isinstance(body.get("data"), list):
                    _LOGGER.debug("→ Got %d devices from shadow=true", len(body["data"]))
                    return body["data"]
        except Exception as e:
            _LOGGER.debug("  shadow endpoint failed: %s", e)

        # ─── 2) Proxy list endpoints ─────────────────────────────────────────────────
        for path in ("/proxy/connect/api/v1/displays", "/proxy/connect/api/v2/displays"):
            url = f"{self.base}{path}"
            _LOGGER.debug("Trying proxy list endpoint: %s", url)
            try:
                resp = await self._session.get(url, headers=self._headers(), ssl=False)
                if resp.status != 200:
                    continue
                data = await resp.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    _LOGGER.debug("→ Got %d display objects", len(data))
                    return data
                if isinstance(data, list) and all(isinstance(i, str) for i in data):
                    _LOGGER.debug("→ Proxy gave %d IDs", len(data))
                    return await self._fetch_settings(data)
            except Exception as e:
                _LOGGER.debug("  proxy list %s failed: %s", url, e)

        # ─── 3) Discovered‐POST endpoints ────────────────────────────────────────────
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
                    return await self._fetch_settings(ids)
            except Exception as e:
                _LOGGER.debug("  discovery %s failed: %s", url, e)

        # ─── 4) UI JSON “site‐settings” ─────────────────────────────────────────────
        ui_url = f"{self.base}/connect/displays/devices/all/{self.site}/settings"
        _LOGGER.debug("Trying site‐settings endpoint: %s", ui_url)
        try:
            resp = await self._session.get(ui_url, headers=self._headers(), ssl=False)
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    _LOGGER.debug("→ Got %d display settings via UI JSON", len(data))
                    return data
        except Exception as e:
            _LOGGER.debug("  site-settings %s failed: %s", ui_url, e)

        _LOGGER.warning("No displays found via any endpoint, returning empty list")
        return []

    async def _fetch_settings(self, ids: list[str]) -> list[dict]:
        """Fetch each discovered display’s settings dict."""
        devices: list[dict] = []
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

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None
