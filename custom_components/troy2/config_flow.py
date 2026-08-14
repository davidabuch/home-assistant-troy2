"""Config flow for Screen Innovations TRO.Y 2."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    Troy2ConnectionError,
    Troy2DiscoveryError,
    Troy2Error,
    Troy2HubApi,
    normalize_host,
)
from .const import CONTROLLER_TITLE, DOMAIN


class Troy2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle TRO.Y 2 setup."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            if any(
                normalize_host(str(entry.data.get(CONF_HOST, ""))) == host
                for entry in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")

            api = Troy2HubApi(async_get_clientsession(self.hass), host)

            try:
                shades = await api.async_discover_shades()
            except Troy2ConnectionError:
                errors["base"] = "cannot_connect"
            except (Troy2DiscoveryError, Troy2Error):
                errors["base"] = "discovery_failed"
            else:
                if not shades:
                    errors["base"] = "no_shades"
                else:
                    return self.async_create_entry(
                        title=CONTROLLER_TITLE,
                        data={CONF_HOST: host},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(user_input),
            errors=errors,
        )

    @staticmethod
    def _schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Return the controller-only setup schema."""
        defaults = user_input or {}
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            }
        )
