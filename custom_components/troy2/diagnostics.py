"""Privacy-safe diagnostics for Screen Innovations TRO.Y 2."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import Troy2Coordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return health details without household-specific identifiers."""
    coordinators: list[Troy2Coordinator] = hass.data[DOMAIN][entry.entry_id]
    healthy_count = sum(coordinator.last_update_success for coordinator in coordinators)
    if healthy_count == len(coordinators):
        status = "healthy"
    elif healthy_count:
        status = "degraded"
    else:
        status = "unavailable"

    return {
        "integration_version": INTEGRATION_VERSION,
        "controller": {
            "status": status,
            "shade_count": len(coordinators),
        },
        "shades": [
            {
                "technology": "wired" if coordinator.api.shade.wired else "wireless",
                "coordinator_healthy": coordinator.last_update_success,
                "has_position": coordinator.data is not None,
                "last_success_age_seconds": (
                    round(coordinator.seconds_since_success, 1)
                    if coordinator.seconds_since_success is not None
                    else None
                ),
            }
            for coordinator in coordinators
        ],
    }
