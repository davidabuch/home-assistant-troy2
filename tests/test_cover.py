"""Tests for TRO.Y cover identity and command behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.troy2.api import Troy2Error
from custom_components.troy2.cover import Troy2Shade


def _entity(*, node_id: str | None = "1234", legacy_node: str = "1234"):
    api = SimpleNamespace(
        host="troy.local",
        node_id=node_id or "00124B0000000001",
        shade=SimpleNamespace(
            node_id=node_id,
            native_id="00124B0000000001",
            label="Living room",
            wired=False,
        ),
        async_open=AsyncMock(),
        async_close=AsyncMock(),
        async_stop=AsyncMock(),
        async_set_position=AsyncMock(),
        async_set_wired_speeds=AsyncMock(),
    )
    coordinator = MagicMock()
    coordinator.api = api
    coordinator.data = 50
    coordinator.movement_direction = None
    coordinator.start_movement_polling = MagicMock()
    entry = SimpleNamespace(data={"node_id": legacy_node})
    return Troy2Shade(coordinator, entry), coordinator


def test_legacy_seed_entity_unique_id_is_stable() -> None:
    entity, _ = _entity()

    assert entity.unique_id == "troy.local_1234"


def test_non_seed_entity_uses_permanent_native_id() -> None:
    entity, _ = _entity(node_id="5678")

    assert entity.unique_id == "troy.local_00124b0000000001"


def test_new_entities_default_enabled() -> None:
    entity, _ = _entity()

    assert entity.entity_registry_enabled_default is True


@pytest.mark.asyncio
async def test_failed_command_does_not_start_movement_polling() -> None:
    entity, coordinator = _entity()
    coordinator.api.async_open.side_effect = Troy2Error("rejected")

    with pytest.raises(Troy2Error, match="rejected"):
        await entity.async_open_cover()

    coordinator.start_movement_polling.assert_not_called()


@pytest.mark.asyncio
async def test_stop_replaces_only_this_shades_tracker() -> None:
    entity, coordinator = _entity()

    await entity.async_stop_cover()

    coordinator.start_movement_polling.assert_called_once_with(
        target_position=None,
        direction=None,
    )
