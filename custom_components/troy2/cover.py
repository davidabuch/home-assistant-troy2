"""Cover entity for Screen Innovations TRO.Y 2."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Troy2ControllerRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime: Troy2ControllerRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [Troy2Shade(runtime, entry, api.shade.native_id) for api in runtime.apis]
    )


class Troy2Shade(CoordinatorEntity[Troy2ControllerRuntime], CoverEntity):
    """A single TRO.Y 2 shade."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_has_entity_name = True
    _attr_name = None
    # Home Assistant applies this only when a registry entry is first created;
    # existing users' explicit enabled/disabled choices remain untouched.
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        runtime: Troy2ControllerRuntime,
        entry: ConfigEntry,
        shade_id: str,
    ) -> None:
        super().__init__(runtime)
        self._entry = entry
        self._shade_id = shade_id
        self._api = runtime.api_for(shade_id)
        shade = self._api.shade
        legacy_node = str(entry.data.get("node_id", "")).upper().removeprefix("0X")
        if shade.node_id == legacy_node:
            # Preserve the legacy-configured entity and HomeKit identity.
            self._attr_unique_id = f"{self._api.host}_{legacy_node}".lower()
        else:
            self._attr_unique_id = f"{self._api.host}_{shade.native_id}".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=shade.label,
            manufacturer="Screen Innovations",
            model="TRO.Y 2 Wired Shade" if shade.wired else "TRO.Y 2 Wireless Shade",
            configuration_url=f"http://{self._api.host}/",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.shade_snapshot(self._shade_id).available

    @property
    def current_cover_position(self) -> int | None:
        return self.coordinator.shade_snapshot(self._shade_id).position

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool:
        return (
            self.coordinator.shade_snapshot(self._shade_id).movement_direction
            == "opening"
        )

    @property
    def is_closing(self) -> bool:
        return (
            self.coordinator.shade_snapshot(self._shade_id).movement_direction
            == "closing"
        )

    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.async_open(self._shade_id)

    async def async_close_cover(self, **kwargs) -> None:
        await self.coordinator.async_close(self._shade_id)

    async def async_stop_cover(self, **kwargs) -> None:
        await self.coordinator.async_stop(self._shade_id)

    async def async_set_cover_position(self, **kwargs) -> None:
        position = int(kwargs[ATTR_POSITION])
        await self.coordinator.async_set_position(self._shade_id, position)

    async def async_set_wired_speeds(
        self,
        up_speed: int,
        down_speed: int,
        slow_speed: int,
    ) -> None:
        """Set all rolling speeds for this RS485 motor."""
        if not self._api.shade.wired:
            raise HomeAssistantError(
                "Motor speed settings are only supported for wired shades"
            )
        await self.coordinator.async_set_wired_speeds(
            self._shade_id,
            up_speed,
            down_speed,
            slow_speed,
        )
