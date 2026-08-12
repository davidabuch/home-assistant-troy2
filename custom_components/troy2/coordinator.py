"""Data coordinator for Screen Innovations TRO.Y 2."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Troy2Api, Troy2Error, Troy2TransientPositionError
from .const import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MOVEMENT_MINIMUM_POLL_SECONDS,
    MOVEMENT_POLL_INTERVAL_SECONDS,
    MOVEMENT_POLL_TIMEOUT_SECONDS,
    MOVEMENT_STABLE_POLLS,
)

_LOGGER = logging.getLogger(__name__)


class Troy2Coordinator(DataUpdateCoordinator[int]):
    """Poll the authoritative shade position from TRO.Y 2."""

    def __init__(self, hass: HomeAssistant, api: Troy2Api) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.api = api
        self.target_position: int | None = None
        self.movement_direction: str | None = None
        self._movement_task: asyncio.Task[None] | None = None
        self._movement_generation = 0
        self._consecutive_update_failures = 0

    async def _async_update_data(self) -> int:
        try:
            position = await self.api.async_get_position()
            self._consecutive_update_failures = 0
            return position
        except Troy2TransientPositionError as err:
            # TRO.Y occasionally reports a successful request with no position
            # data ("file empty"). This is a controller timing condition rather
            # than evidence that the shade or controller is unavailable.
            if self.data is not None:
                _LOGGER.debug(
                    "Preserving last known position for %s after transient "
                    "TRO.Y position miss: %s",
                    self.api.shade.label,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err
        except Troy2Error as err:
            self._consecutive_update_failures += 1
            # Preserve the previous state briefly for genuine communication
            # failures, but still expose a sustained controller outage.
            if self.data is not None and self._consecutive_update_failures <= 3:
                _LOGGER.debug(
                    "Preserving last known position for %s after missed poll "
                    "(%s/3): %s",
                    self.api.shade.label,
                    self._consecutive_update_failures,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err

    def start_movement_polling(
        self,
        *,
        target_position: int | None,
        direction: str | None,
    ) -> None:
        """Poll rapidly until the shade reaches its target or stops moving."""
        self.cancel_movement_polling()
        self._movement_generation += 1
        generation = self._movement_generation
        self.target_position = target_position
        self.movement_direction = direction
        self.async_update_listeners()
        self._movement_task = self.hass.async_create_task(
            self._async_poll_movement(generation),
            f"{DOMAIN}_movement_{self.api.node_id}",
        )

    def cancel_movement_polling(self) -> None:
        """Cancel an active rapid-polling task."""
        if self._movement_task is not None and not self._movement_task.done():
            self._movement_task.cancel()
        self._movement_task = None

    async def async_shutdown(self) -> None:
        """Stop background work when the config entry unloads."""
        self.cancel_movement_polling()
        self._movement_generation += 1
        self.target_position = None
        self.movement_direction = None

    async def _async_poll_movement(self, generation: int) -> None:
        """Refresh once per second while a commanded movement is active."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_position = self.data
        stable_polls = 0

        try:
            while loop.time() - started < MOVEMENT_POLL_TIMEOUT_SECONDS:
                await asyncio.sleep(MOVEMENT_POLL_INTERVAL_SECONDS)

                try:
                    await self.async_refresh()
                except Exception:  # Coordinator records and exposes refresh failure.
                    _LOGGER.debug(
                        "Rapid TRO.Y movement refresh failed",
                        exc_info=True,
                    )
                    continue

                current = self.data
                if current is None:
                    continue

                if current == last_position:
                    stable_polls += 1
                else:
                    stable_polls = 0
                    last_position = current

                elapsed = loop.time() - started
                reached_target = (
                    self.target_position is not None
                    and current == self.target_position
                )
                stopped = (
                    elapsed >= MOVEMENT_MINIMUM_POLL_SECONDS
                    and stable_polls >= MOVEMENT_STABLE_POLLS
                )
                if reached_target or stopped:
                    break
        except asyncio.CancelledError:
            return
        finally:
            # A newer command may already have started a replacement task.
            if generation == self._movement_generation:
                self.target_position = None
                self.movement_direction = None
                self._movement_task = None
                self.async_update_listeners()
