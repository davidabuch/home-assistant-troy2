"""Tests for TRO.Y coordinator availability and movement tracking."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.troy2.api import Troy2Error, Troy2TransientPositionError
from custom_components.troy2.coordinator import Troy2Coordinator


def _api() -> SimpleNamespace:
    return SimpleNamespace(
        async_get_position=AsyncMock(),
        host="troy.local",
        node_id="A1B2C3",
        shade=SimpleNamespace(label="Shade", wired=True),
    )


@pytest.mark.asyncio
async def test_communication_grace_and_recovery(hass) -> None:
    api = _api()
    coordinator = Troy2Coordinator(hass, api)
    api.async_get_position.return_value = 40

    with patch("custom_components.troy2.coordinator.monotonic", return_value=100):
        assert await coordinator._async_update_data() == 40
    coordinator.data = 40

    api.async_get_position.side_effect = Troy2Error("miss")
    for now in (101, 120, 159.9):
        with patch("custom_components.troy2.coordinator.monotonic", return_value=now):
            assert await coordinator._async_update_data() == 40

    with (
        patch("custom_components.troy2.coordinator.monotonic", return_value=160),
        pytest.raises(UpdateFailed, match="miss"),
    ):
        await coordinator._async_update_data()

    api.async_get_position.side_effect = None
    api.async_get_position.return_value = 75
    with patch("custom_components.troy2.coordinator.monotonic", return_value=161):
        assert await coordinator._async_update_data() == 75
        assert coordinator.seconds_since_success == 0


@pytest.mark.asyncio
async def test_transient_misses_preserve_state_without_error_spam(hass, caplog) -> None:
    api = _api()
    coordinator = Troy2Coordinator(hass, api)
    coordinator.data = 30
    coordinator._last_success_monotonic = 100
    api.async_get_position.side_effect = Troy2TransientPositionError("file empty")

    with (
        patch("custom_components.troy2.coordinator.monotonic", return_value=110),
        caplog.at_level(logging.DEBUG),
    ):
        assert await coordinator._async_update_data() == 30
        assert await coordinator._async_update_data() == 30

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_movement_replacement_is_per_shade(hass) -> None:
    first = Troy2Coordinator(hass, _api())
    second = Troy2Coordinator(hass, _api())
    hold = asyncio.Event()

    async def wait_forever(generation: int) -> None:
        await hold.wait()

    first._async_poll_movement = wait_forever
    second._async_poll_movement = wait_forever
    first.start_movement_polling(target_position=100, direction="opening")
    first_task = first._movement_task
    second.start_movement_polling(target_position=0, direction="closing")
    other_task = second._movement_task
    await asyncio.sleep(0)

    first.start_movement_polling(target_position=0, direction="closing")
    replacement_task = first._movement_task
    await asyncio.sleep(0)

    assert first_task is not replacement_task
    assert first_task.done()
    assert other_task is second._movement_task
    assert not other_task.done()
    assert first.target_position == 0
    assert second.target_position == 0

    await first.async_shutdown()
    await second.async_shutdown()


@pytest.mark.asyncio
async def test_movement_poll_stops_at_target(hass) -> None:
    coordinator = Troy2Coordinator(hass, _api())
    coordinator.data = 10
    coordinator.target_position = 100
    coordinator.movement_direction = "opening"
    coordinator._movement_generation = 1

    async def refresh() -> None:
        coordinator.data = 100

    coordinator.async_refresh = refresh
    with patch("custom_components.troy2.coordinator.asyncio.sleep", new=AsyncMock()):
        await asyncio.wait_for(coordinator._async_poll_movement(1), timeout=1)

    assert coordinator.target_position is None
    assert coordinator.movement_direction is None
    assert coordinator._movement_task is None


@pytest.mark.asyncio
async def test_movement_poll_timeout_clears_tracking(hass) -> None:
    coordinator = Troy2Coordinator(hass, _api())
    coordinator.data = 10
    coordinator.target_position = 100
    coordinator.movement_direction = "opening"
    coordinator._movement_generation = 1

    with patch(
        "custom_components.troy2.coordinator.MOVEMENT_POLL_TIMEOUT_SECONDS",
        0,
    ):
        await coordinator._async_poll_movement(1)

    assert coordinator.target_position is None
    assert coordinator.movement_direction is None
