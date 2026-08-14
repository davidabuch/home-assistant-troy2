"""Tests for controller startup discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.troy2 import _async_discover_shades
from custom_components.troy2.api import Troy2ConnectionError, Troy2ShadeDescription


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
