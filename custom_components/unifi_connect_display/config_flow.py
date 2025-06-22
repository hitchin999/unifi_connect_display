"""Config flow for UniFi Connect Display integration."""
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import voluptuous as vol
from aiohttp import ClientResponseError
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_SITE
from .api import UniFiConnectClient

_LOGGER = logging.getLogger(__name__)

class UniFiConnectFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Connect Display."""

    VERSION = 6
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self._client: Optional[UniFiConnectClient] = None
        self._sites: Dict[str, str] = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Step 1: Ask for host, username & password, then fetch sites."""
        errors: Dict[str, str] = {}

        if user_input:
            raw = user_input[CONF_HOST].strip()
            parsed = urlparse(raw if "://" in raw else f"//{raw}", scheme="https")
            host = parsed.netloc or parsed.path

            _LOGGER.debug("Config flow: Logging in to host %s", host)
            self._client = UniFiConnectClient(
                self.hass,
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                # site set later
            )
            try:
                await self._client.login()
            except Exception as ex:
                _LOGGER.error("UniFi auth failed: %s", ex)
                errors["base"] = "auth"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._user_schema(),
                    errors=errors,
                )

            # Attempt to list sites via the API
            try:
                sites = await self._client.list_sites()
            except ClientResponseError:
                sites = []

            if sites:
                # Build dropdown
                self._sites = {site["id"]: site.get("name", site["id"]) for site in sites}
                return await self.async_step_site()

            # No sites listed: fall back to manual site entry
            return await self.async_step_site_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(),
            errors=errors,
        )

    def _user_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    description={"suggested_value": "https://your-controller:8443"},
                ): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

    async def async_step_site(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Step 2a: Let the user pick from the API-returned sites."""
        if user_input:
            site_id = user_input[CONF_SITE]
            site_name = self._sites[site_id]
            return self.async_create_entry(
                title=f"{site_name} @ {self._client.host}",
                data={
                    CONF_HOST: self._client.host,
                    CONF_USERNAME: self._client.username,
                    CONF_PASSWORD: self._client.password,
                    CONF_SITE: site_id,
                },
            )

        schema = vol.Schema({vol.Required(CONF_SITE): vol.In(self._sites)})
        return self.async_show_form(step_id="site", data_schema=schema)

    async def async_step_site_manual(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 2b: Fallback when no sites exposed by API.
        Ask user to type the site ID (e.g. 'default').
        """
        errors: Dict[str, str] = {}

        if user_input:
            site = user_input[CONF_SITE].strip()
            return self.async_create_entry(
                title=f"{site} @ {self._client.host}",
                data={
                    CONF_HOST: self._client.host,
                    CONF_USERNAME: self._client.username,
                    CONF_PASSWORD: self._client.password,
                    CONF_SITE: site,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SITE,
                    description={"suggested_value": "default"},
                ): str,
            }
        )
        return self.async_show_form(
            step_id="site_manual",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "info": "Your UniFi Connect site ID (often 'default')."
            },
        )
