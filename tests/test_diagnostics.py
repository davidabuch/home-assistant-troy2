"""Tests for privacy-safe TRO.Y runtime diagnostics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.troy2.api import Troy2ControllerContext
from custom_components.troy2.const import DOMAIN, INTEGRATION_VERSION
from custom_components.troy2.coordinator import Troy2ControllerRuntime
from custom_components.troy2.diagnostics import async_get_config_entry_diagnostics


def _api(native_id: str, *, wired: bool) -> SimpleNamespace:
    return SimpleNamespace(
        host="private.example",
        node_id="PRIVATE-NODE",
        shade=SimpleNamespace(
            wired=wired,
            label="Private room name",
            native_id=native_id,
        ),
        async_get_position=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_diagnostics_are_observable_and_omit_household_identifiers(hass) -> None:
    now = 100.0
    context = Troy2ControllerContext()
    context.total_successful_requests = 20
    context.total_failed_requests = 3
    context._recent_latencies.extend([0.1, 0.3, 1.1])
    runtime = Troy2ControllerRuntime(
        hass,
        [
            _api("PRIVATE-NATIVE-ID-1", wired=True),
            _api("PRIVATE-NATIVE-ID-2", wired=False),
        ],
        context,
        clock=lambda: now,
    )
    first, second = runtime._states.values()
    first.position = 50
    first.last_success = 98.766
    first.last_attempt = 99.0
    first.poll_lateness = 2.25
    second.last_attempt = 95
    second.failure_started = 96
    second.failure_category = "timeout"
    second.consecutive_failures = 1
    runtime._last_controller_success = 98.766
    runtime._max_poll_lateness = 4.5

    entry = SimpleNamespace(
        entry_id="entry-id",
        data={"host": "private.example", "node_id": "PRIVATE-NODE"},
    )
    hass.data[DOMAIN] = {entry.entry_id: runtime}

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = str(diagnostics)

    assert diagnostics["integration_version"] == INTEGRATION_VERSION
    controller = diagnostics["controller"]
    assert controller["status"] == "degraded"
    assert controller["shade_count"] == 2
    assert controller["scheduler_running"] is False
    assert controller["total_successful_requests"] == 20
    assert controller["total_failed_requests"] == 3
    assert controller["recent_request_latency_average_seconds"] == 0.5
    assert controller["recent_request_latency_max_seconds"] == 1.1
    assert controller["last_success_age_seconds"] == 1.2
    assert controller["maximum_poll_lateness_seconds"] == 4.5
    assert diagnostics["shades"][0]["last_success_age_seconds"] == 1.2
    assert diagnostics["shades"][0]["poll_lateness_seconds"] == 2.2
    assert diagnostics["shades"][1]["failure_episode_age_seconds"] == 4.0
    assert diagnostics["shades"][1]["failure_category"] == "timeout"
    assert "private.example" not in serialized
    assert "Private room name" not in serialized
    assert "PRIVATE-NATIVE-ID" not in serialized
    assert "PRIVATE-NODE" not in serialized
