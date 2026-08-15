"""Tests for controller startup discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.troy2 import (
    _async_discover_shades,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.troy2.api import Troy2ConnectionError, Troy2ShadeDescription
from custom_components.troy2.const import DOMAIN


def _shade(index: int) -> Troy2ShadeDescription:
    return Troy2ShadeDescription(
        index,
        f"Shade {index}",
        f"{index:06X}",
        "",
        True,
        None,
    )


@pytest.mark.asyncio
async def test_two_sequential_scans_merge_incomplete_results() -> None:
    hub = AsyncMock()
    hub.async_discover_shades.side_effect = [[_shade(1), _shade(2)], [_shade(2), _shade(3)]]

    with patch("custom_components.troy2.asyncio.sleep", new=AsyncMock()) as sleep:
        shades = await _async_discover_shades(hub, "troy.local")

    assert [shade.native_id for shade in shades] == ["000001", "000002", "000003"]
    assert hub.async_discover_shades.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_failed_scan_does_not_block_controller() -> None:
    hub = AsyncMock()
    hub.async_discover_shades.side_effect = [
        Troy2ConnectionError("temporary"),
        [_shade(1)],
    ]

    with patch("custom_components.troy2.asyncio.sleep", new=AsyncMock()):
        assert await _async_discover_shades(hub, "troy.local") == [_shade(1)]


@pytest.mark.asyncio
async def test_ten_shade_startup_remains_complete_and_sequential() -> None:
    hub = AsyncMock()
    first = [_shade(index) for index in range(1, 11)]
    hub.async_discover_shades.side_effect = [first[:7], first[3:]]

    with patch("custom_components.troy2.asyncio.sleep", new=AsyncMock()):
        shades = await _async_discover_shades(hub, "troy.local")

    assert len(shades) == 10
    assert hub.async_discover_shades.await_count == 2


@pytest.mark.asyncio
async def test_controller_temporarily_unavailable_retries_setup() -> None:
    hub = AsyncMock()
    hub.async_discover_shades.side_effect = Troy2ConnectionError("offline")

    with (
        patch("custom_components.troy2.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ConfigEntryNotReady, match="temporarily unavailable"),
    ):
        await _async_discover_shades(hub, "troy.local")


@pytest.mark.asyncio
async def test_setup_creates_one_runtime_and_core_stop_shuts_it_down(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "troy.local"},
        unique_id="troy.local",
        version=2,
    )
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.async_start = AsyncMock()
    runtime.async_shutdown = AsyncMock()

    with (
        patch(
            "custom_components.troy2._async_discover_shades",
            return_value=[_shade(1), _shade(2)],
        ),
        patch(
            "custom_components.troy2.Troy2ControllerRuntime",
            return_value=runtime,
        ) as runtime_class,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry)

    runtime.async_start.assert_awaited_once()
    assert hass.data[DOMAIN][entry.entry_id] is runtime
    apis = runtime_class.call_args.args[1]
    assert len(apis) == 2
    assert apis[0]._context is apis[1]._context

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    runtime.async_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_unload_stops_runtime_and_removes_entry_data(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "troy.local"})
    runtime = MagicMock()
    runtime.async_shutdown = AsyncMock()
    hass.data[DOMAIN] = {entry.entry_id: runtime}

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(hass, entry)

    runtime.async_shutdown.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_platform_setup_failure_cleans_up_runtime(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "troy.local"},
        unique_id="troy.local",
        version=2,
    )
    entry.add_to_hass(hass)
    runtime = MagicMock()
    runtime.async_start = AsyncMock()
    runtime.async_shutdown = AsyncMock()

    with (
        patch(
            "custom_components.troy2._async_discover_shades",
            return_value=[_shade(1)],
        ),
        patch(
            "custom_components.troy2.Troy2ControllerRuntime",
            return_value=runtime,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(side_effect=RuntimeError("platform failed")),
        ),
        pytest.raises(RuntimeError, match="platform failed"),
    ):
        await async_setup_entry(hass, entry)

    runtime.async_shutdown.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]
