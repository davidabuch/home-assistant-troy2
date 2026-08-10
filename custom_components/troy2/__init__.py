"""Screen Innovations TRO.Y 2 integration."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import (
    Troy2Api,
    Troy2ControllerContext,
    Troy2Error,
    Troy2HubApi,
    Troy2ShadeDescription,
)
from .const import (
    ATTR_DOWN_SPEED,
    ATTR_SLOW_SPEED,
    ATTR_UP_SPEED,
    CONF_NODE_ID,
    CONF_SHADE_NAME,
    DOMAIN,
    MAX_WIRED_SPEED,
    MIN_WIRED_SPEED,
    PLATFORMS,
    SERVICE_SET_WIRED_SPEEDS,
)
from .coordinator import Troy2Coordinator

SETUP_DISCOVERY_SCAN_DELAY_SECONDS = 2


async def _async_discover_shades(
    hub_api: Troy2HubApi,
    host: str,
) -> list[Troy2ShadeDescription]:
    """Run and merge two discovery scans, tolerating one failed scan."""
    discovered: dict[str, Troy2ShadeDescription] = {}
    last_error: Troy2Error | None = None

    for scan_number in range(2):
        if scan_number:
            await asyncio.sleep(SETUP_DISCOVERY_SCAN_DELAY_SECONDS)
        try:
            shades = await hub_api.async_discover_shades()
        except Troy2Error as err:
            last_error = err
            continue

        for shade in shades:
            discovered[shade.native_id] = shade

    if discovered:
        return list(discovered.values())

    raise ConfigEntryNotReady(
        f"TRO.Y 2 at {host} is temporarily unavailable"
    ) from last_error


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register TRO.Y 2 actions."""
    speed_value = vol.All(
        vol.Coerce(int),
        vol.Range(min=MIN_WIRED_SPEED, max=MAX_WIRED_SPEED),
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_WIRED_SPEEDS,
        entity_domain=COVER_DOMAIN,
        schema={
            vol.Required(ATTR_UP_SPEED): speed_value,
            vol.Required(ATTR_DOWN_SPEED): speed_value,
            vol.Required(ATTR_SLOW_SPEED): speed_value,
        },
        func="async_set_wired_speeds",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TRO.Y 2 from a config entry."""
    session = async_get_clientsession(hass)
    host = entry.data[CONF_HOST]
    hub_api = Troy2HubApi(session, host)
    # TRO.Y can occasionally return an incomplete device index during startup.
    # Merge two scans so a shade omitted from either response is still loaded.
    # A failed scan is harmless when the other scan finds shades; if neither
    # succeeds, ConfigEntryNotReady lets Home Assistant retry automatically.
    shades = await _async_discover_shades(hub_api, host)
    controller_context = Troy2ControllerContext()

    # If discovery ever omits the previously configured shade, keep it working.
    legacy_node = str(entry.data.get(CONF_NODE_ID, "")).upper().removeprefix("0X")
    if legacy_node and not any(shade.node_id == legacy_node for shade in shades):
        shades.append(
            Troy2ShadeDescription(
                vadr_entry=0,
                label=entry.data.get(CONF_SHADE_NAME, "TRO.Y Shade"),
                native_id=f"LEGACY-{legacy_node}",
                assigned_id="",
                wired=False,
                node_id=legacy_node,
            )
        )

    coordinators: list[Troy2Coordinator] = []
    for shade in shades:
        coordinator = Troy2Coordinator(
            hass,
            Troy2Api(session, host, shade, controller_context),
        )
        if shade.node_id == legacy_node:
            await coordinator.async_config_entry_first_refresh()
        else:
            # A single sleeping/offline shade must not block the whole hub.
            await coordinator.async_refresh()
        coordinators.append(coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a TRO.Y 2 config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinators: list[Troy2Coordinator] = hass.data[DOMAIN].pop(entry.entry_id)
        for coordinator in coordinators:
            await coordinator.async_shutdown()
    return unloaded
