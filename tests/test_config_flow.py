"""Tests for controller-only setup and v1 migration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.troy2 import async_migrate_entry
from custom_components.troy2.api import (
    Troy2ConnectionError,
    Troy2DiscoveryError,
    Troy2ShadeDescription,
)
from custom_components.troy2.const import (
    CONF_NODE_ID,
    CONF_SHADE_NAME,
    CONTROLLER_TITLE,
    DOMAIN,
)


def _discovered_shade() -> Troy2ShadeDescription:
    return Troy2ShadeDescription(1, "Shade", "A1B2C3", "", True, None)


@pytest.mark.asyncio
async def test_fresh_install_is_controller_only_and_normalized(hass) -> None:
    with (
        patch(
            "custom_components.troy2.config_flow.Troy2HubApi.async_discover_shades",
            return_value=[_discovered_shade()],
        ),
        patch("custom_components.troy2.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: " HTTPS://TROY.Local/// "},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == CONTROLLER_TITLE
    assert result["data"] == {CONF_HOST: "troy.local"}
    assert result["result"].unique_id == "troy.local"
    assert result["result"].version == 2


@pytest.mark.asyncio
async def test_duplicate_controller_is_prevented_by_normalized_data(hass) -> None:
    legacy = MockConfigEntry(
        domain=DOMAIN,
        title="Old shade",
        data={CONF_HOST: "TROY.LOCAL", CONF_NODE_ID: "1234"},
        unique_id="troy.local_1234",
        version=1,
    )
    legacy.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_HOST: "http://troy.local/"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (Troy2ConnectionError("offline"), "cannot_connect"),
        (Troy2DiscoveryError("malformed"), "discovery_failed"),
    ],
)
async def test_setup_error_classification(hass, error: Exception, expected: str) -> None:
    with patch(
        "custom_components.troy2.config_flow.Troy2HubApi.async_discover_shades",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "troy.local"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


@pytest.mark.asyncio
async def test_setup_rejects_controller_with_no_shades(hass) -> None:
    with patch(
        "custom_components.troy2.config_flow.Troy2HubApi.async_discover_shades",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "troy.local"},
        )

    assert result["errors"] == {"base": "no_shades"}


@pytest.mark.asyncio
async def test_lone_v1_entry_migrates_without_entity_identity_change(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Living room",
        data={
            CONF_HOST: "TROY.LOCAL",
            CONF_NODE_ID: "1234",
            CONF_SHADE_NAME: "Living room",
        },
        unique_id="troy.local_1234",
        version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry_entry = registry.async_get_or_create(
        COVER_DOMAIN,
        DOMAIN,
        "troy.local_1234",
        config_entry=entry,
        suggested_object_id="living_room",
        disabled_by=RegistryEntryDisabler.USER,
    )

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 2
    assert entry.title == CONTROLLER_TITLE
    assert entry.unique_id == "troy.local"
    assert entry.data[CONF_NODE_ID] == "1234"
    assert entry.data[CONF_SHADE_NAME] == "Living room"
    assert registry.async_get(registry_entry.entity_id) is registry_entry
    assert registry_entry.unique_id == "troy.local_1234"
    assert registry_entry.disabled_by is RegistryEntryDisabler.USER


@pytest.mark.asyncio
async def test_duplicate_legacy_entries_keep_collision_safe_unique_ids(hass) -> None:
    entries = [
        MockConfigEntry(
            domain=DOMAIN,
            title=f"Shade {node}",
            data={CONF_HOST: "troy.local", CONF_NODE_ID: node},
            unique_id=f"troy.local_{node}",
            version=1,
        )
        for node in ("1234", "5678")
    ]
    for entry in entries:
        entry.add_to_hass(hass)

    for entry in entries:
        assert await async_migrate_entry(hass, entry)

    assert [entry.unique_id for entry in entries] == [
        "troy.local_1234",
        "troy.local_5678",
    ]
    assert all(entry.version == 2 for entry in entries)
    assert all(entry.title == CONTROLLER_TITLE for entry in entries)
