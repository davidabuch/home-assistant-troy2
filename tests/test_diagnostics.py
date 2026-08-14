"""Tests for privacy-safe TRO.Y diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.troy2.const import DOMAIN, INTEGRATION_VERSION
from custom_components.troy2.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.asyncio
async def test_diagnostics_omit_household_identifiers(hass) -> None:
    coordinators = [
        SimpleNamespace(
            api=SimpleNamespace(
                host="private.example",
                shade=SimpleNamespace(
                    wired=wired,
                    label="Private room name",
                    native_id="PRIVATE-NATIVE-ID",
                ),
                node_id="PRIVATE-NODE",
            ),
            last_update_success=healthy,
            data=position,
            seconds_since_success=age,
        )
        for wired, healthy, position, age in (
            (True, True, 50, 1.234),
            (False, False, None, None),
        )
    ]
    entry = SimpleNamespace(
        entry_id="entry-id",
        data={"host": "private.example", "node_id": "PRIVATE-NODE"},
    )
    hass.data[DOMAIN] = {entry.entry_id: coordinators}

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = str(diagnostics)

    assert diagnostics["integration_version"] == INTEGRATION_VERSION
    assert diagnostics["controller"] == {"status": "degraded", "shade_count": 2}
    assert diagnostics["shades"][0]["last_success_age_seconds"] == 1.2
    assert "private.example" not in serialized
    assert "Private room name" not in serialized
    assert "PRIVATE-NATIVE-ID" not in serialized
    assert "PRIVATE-NODE" not in serialized
