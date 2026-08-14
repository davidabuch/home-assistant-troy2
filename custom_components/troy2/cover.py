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
from .coordinator import Troy2Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinators: list[Troy2Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Troy2Shade(coordinator, entry) for coordinator in coordinators])


class Troy2Shade(CoordinatorEntity[Troy2Coordinator], CoverEntity):
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

    def __init__(self, coordinator: Troy2Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        shade = coordinator.api.shade
        legacy_node = str(entry.data.get("node_id", "")).upper().removeprefix("0X")
        if shade.node_id == legacy_node:
            # Preserve the legacy-configured entity and HomeKit identity.
            self._attr_unique_id = f"{coordinator.api.host}_{legacy_node}".lower()
        else:
            self._attr_unique_id = f"{coordinator.api.host}_{shade.native_id}".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=shade.label,
            manufacturer="Screen Innovations",
            model="TRO.Y 2 Wired Shade" if shade.wired else "TRO.Y 2 Wireless Shade",
            configuration_url=f"http://{coordinator.api.host}/",
        )

    @property
    def current_cover_position(self) -> int | None:
        return self.coordinator.data

    @property
    def is_closed(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data == 0

    @property
    def is_opening(self) -> bool:
        return self.coordinator.movement_direction == "opening"

    @property
    def is_closing(self) -> bool:
        return self.coordinator.movement_direction == "closing"

    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.api.async_open()
        self.coordinator.start_movement_polling(
            target_position=100,
            direction="opening",
        )

    async def async_close_cover(self, **kwargs) -> None:
        await self.coordinator.api.async_close()
        self.coordinator.start_movement_polling(
            target_position=0,
            direction="closing",
        )

    async def async_stop_cover(self, **kwargs) -> None:
        await self.coordinator.api.async_stop()
        self.coordinator.start_movement_polling(
            target_position=None,
            direction=None,
        )

    async def async_set_cover_position(self, **kwargs) -> None:
        position = int(kwargs[ATTR_POSITION])
        await self.coordinator.api.async_set_position(position)
        current = self.coordinator.data
        direction = None
        if current is not None:
            if position > current:
                direction = "opening"
            elif position < current:
                direction = "closing"
        self.coordinator.start_movement_polling(
            target_position=position,
            direction=direction,
        )

    async def async_set_wired_speeds(
        self,
        up_speed: int,
        down_speed: int,
        slow_speed: int,
    ) -> None:
        """Set all rolling speeds for this RS485 motor."""
        if not self.coordinator.api.shade.wired:
            raise HomeAssistantError(
                "Motor speed settings are only supported for wired shades"
            )
        await self.coordinator.api.async_set_wired_speeds(
            up_speed,
            down_speed,
            slow_speed,
        )
