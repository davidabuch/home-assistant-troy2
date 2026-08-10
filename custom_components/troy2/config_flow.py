"""Config flow for Screen Innovations TRO.Y 2."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import Troy2Error, Troy2HubApi
from .const import CONF_NODE_ID, CONF_SHADE_NAME, DEFAULT_NAME, DEFAULT_NODE_ID, DOMAIN


class Troy2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle TRO.Y 2 setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip().removeprefix("http://").removeprefix("https://").rstrip("/")
            node_id = user_input[CONF_NODE_ID].strip().upper().removeprefix("0X")
            api = Troy2HubApi(async_get_clientsession(self.hass), host)

            try:
                shades = await api.async_discover_shades()
            except Troy2Error:
                errors["base"] = "cannot_connect"
            else:
                if not any(shade.node_id == node_id for shade in shades):
                    errors["base"] = "cannot_connect"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=self._schema(user_input),
                        errors=errors,
                    )
                unique_id = f"{host}_{node_id}".lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_SHADE_NAME],
                    data={
                        CONF_HOST: host,
                        CONF_NODE_ID: node_id,
                        CONF_SHADE_NAME: user_input[CONF_SHADE_NAME],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(user_input),
            errors=errors,
        )

    @staticmethod
    def _schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Return the temporary legacy-compatible setup schema."""
        defaults = user_input or {}
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_NODE_ID, default=defaults.get(CONF_NODE_ID, DEFAULT_NODE_ID)): str,
                vol.Required(CONF_SHADE_NAME, default=defaults.get(CONF_SHADE_NAME, DEFAULT_NAME)): str,
            }
        )
