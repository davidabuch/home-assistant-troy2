"""Privacy-safe diagnostics for Screen Innovations TRO.Y 2."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import Troy2ControllerRuntime


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return health details without household-specific identifiers."""
    runtime: Troy2ControllerRuntime = hass.data[DOMAIN][entry.entry_id]
    snapshots = [
        runtime.shade_snapshot(api.shade.native_id) for api in runtime.apis
    ]
    healthy_count = sum(snapshot.available for snapshot in snapshots)
    if runtime.controller_confirmed_unavailable:
        status = "unavailable"
    elif healthy_count == runtime.shade_count:
        status = "healthy"
    elif healthy_count:
        status = "degraded"
    else:
        status = "unavailable"

    latencies = runtime.context.recent_latencies

    return {
        "integration_version": INTEGRATION_VERSION,
        "controller": {
            "status": status,
            "shade_count": runtime.shade_count,
            "scheduler_running": runtime.scheduler_running,
            "request_in_progress": runtime.context.request_in_progress,
            "total_successful_requests": runtime.context.total_successful_requests,
            "total_failed_requests": runtime.context.total_failed_requests,
            "recent_request_latency_average_seconds": (
                round(sum(latencies) / len(latencies), 3) if latencies else None
            ),
            "recent_request_latency_max_seconds": (
                round(max(latencies), 3) if latencies else None
            ),
            "last_success_age_seconds": _rounded(
                runtime.last_controller_success_age
            ),
            "failure_episode_age_seconds": _rounded(
                runtime.controller_failure_episode_age
            ),
            "failure_category": runtime.controller_failure_category,
            "pending_work_count": runtime.pending_work_count,
            "maximum_poll_lateness_seconds": round(
                runtime.maximum_poll_lateness,
                1,
            ),
        },
        "shades": [
            {
                "technology": "wired" if api.shade.wired else "wireless",
                "available": snapshot.available,
                "has_position": snapshot.position_known,
                "last_success_age_seconds": _rounded(snapshot.last_success_age),
                "last_attempt_age_seconds": _rounded(snapshot.last_attempt_age),
                "failure_episode_age_seconds": _rounded(
                    snapshot.failure_episode_age
                ),
                "failure_category": snapshot.failure_category,
                "consecutive_failures": snapshot.consecutive_failures,
                "moving": snapshot.rapid_polling,
                "poll_lateness_seconds": round(snapshot.poll_lateness, 1),
            }
            for api, snapshot in zip(runtime.apis, snapshots, strict=True)
        ],
    }


def _rounded(value: float | None) -> float | None:
    """Round a diagnostic age without exposing an internal clock."""
    return round(value, 1) if value is not None else None
