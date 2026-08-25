"""Controller-level runtime for Screen Innovations TRO.Y 2."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Troy2Api,
    Troy2ControllerContext,
    Troy2Error,
    Troy2ShutdownError,
)
from .const import (
    COMMUNICATION_FAILURE_GRACE_SECONDS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_FAILURE_POLL_BACKOFF_SECONDS,
    MOVEMENT_MINIMUM_POLL_SECONDS,
    MOVEMENT_POLL_INTERVAL_SECONDS,
    MOVEMENT_POLL_TIMEOUT_SECONDS,
    MOVEMENT_STABLE_POLLS,
)

_LOGGER = logging.getLogger(__name__)

_MAX_CONSECUTIVE_COMMANDS = 4


@dataclass(slots=True)
class _ShadeRuntimeState:
    """Mutable state owned only by the controller runtime."""

    api: Troy2Api
    order: int
    position: int | None = None
    last_success: float | None = None
    last_attempt: float | None = None
    failure_started: float | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    consecutive_failures: int = 0
    confirmed_unavailable: bool = False
    verification_required: bool = False
    target_position: int | None = None
    movement_direction: str | None = None
    rapid_polling: bool = False
    movement_started: float | None = None
    movement_last_position: int | None = None
    movement_stable_polls: int = 0
    next_poll_due: float = 0.0
    poll_lateness: float = 0.0
    max_poll_lateness: float = 0.0


@dataclass(frozen=True, slots=True)
class Troy2ShadeSnapshot:
    """Immutable privacy-safe view of one shade's runtime state."""

    position: int | None
    position_known: bool
    available: bool
    last_success_age: float | None
    last_attempt_age: float | None
    failure_episode_age: float | None
    failure_category: str | None
    consecutive_failures: int
    target_position: int | None
    movement_direction: str | None
    rapid_polling: bool
    poll_lateness: float
    failure_poll_backoff: float
    verification_required: bool


@dataclass(slots=True)
class _CommandRequest:
    """One real command waiting for the single controller worker."""

    shade_id: str
    operation: Callable[[Troy2Api], Awaitable[None]]
    future: asyncio.Future[None]
    target_position: int | None = None
    direction: str | None = None
    track_movement: bool = False


class Troy2ControllerRuntime(DataUpdateCoordinator[dict[str, int]]):
    """Own scheduling, health, and state for every shade on one controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        apis: list[Troy2Api],
        context: Troy2ControllerContext,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.context = context
        self._clock = clock
        self._states = {
            api.shade.native_id: _ShadeRuntimeState(api=api, order=index)
            for index, api in enumerate(apis)
        }
        self._commands: deque[_CommandRequest] = deque()
        self._active_command: _CommandRequest | None = None
        self._wake = asyncio.Event()
        self._scheduler_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._consecutive_commands = 0
        self._consecutive_movement_polls = 0
        self._controller_failure_started: float | None = None
        self._controller_failure_shades: set[str] = set()
        self._controller_failure_count = 0
        self._controller_failure_category: str | None = None
        self._controller_confirmed_unavailable = False
        self._last_controller_success: float | None = None
        self._max_poll_lateness = 0.0

    @property
    def apis(self) -> tuple[Troy2Api, ...]:
        """Return the fixed collection of shade clients."""
        return tuple(state.api for state in self._states.values())

    @property
    def shade_count(self) -> int:
        return len(self._states)

    @property
    def scheduler_running(self) -> bool:
        return self._scheduler_task is not None and not self._scheduler_task.done()

    @property
    def pending_work_count(self) -> int:
        now = self._clock()
        due = sum(state.next_poll_due <= now for state in self._states.values())
        return len(self._commands) + due

    @property
    def maximum_poll_lateness(self) -> float:
        return self._max_poll_lateness

    @property
    def last_controller_success_age(self) -> float | None:
        return self._age(self._last_controller_success)

    @property
    def controller_failure_episode_age(self) -> float | None:
        return self._age(self._controller_failure_started)

    @property
    def controller_failure_category(self) -> str | None:
        return self._controller_failure_category

    @property
    def controller_confirmed_unavailable(self) -> bool:
        return self._controller_confirmed_unavailable

    def api_for(self, shade_id: str) -> Troy2Api:
        return self._states[shade_id].api

    def shade_snapshot(self, shade_id: str) -> Troy2ShadeSnapshot:
        """Return an immutable view for entities and diagnostics."""
        state = self._states[shade_id]
        established = state.position is not None or state.last_success is not None
        available = (
            established
            and not state.confirmed_unavailable
            and not self._controller_confirmed_unavailable
            and not state.verification_required
        )
        return Troy2ShadeSnapshot(
            position=state.position,
            position_known=state.position is not None,
            available=available,
            last_success_age=self._age(state.last_success),
            last_attempt_age=self._age(state.last_attempt),
            failure_episode_age=self._age(state.failure_started),
            failure_category=state.failure_category,
            consecutive_failures=state.consecutive_failures,
            target_position=state.target_position,
            movement_direction=state.movement_direction,
            rapid_polling=state.rapid_polling,
            poll_lateness=state.poll_lateness,
            failure_poll_backoff=self._failure_poll_backoff(state),
            verification_required=state.verification_required,
        )

    async def async_start(self) -> None:
        """Start background initial acquisition and ongoing scheduling."""
        if self.scheduler_running:
            return
        self._stopping = False
        # A zero due-time means "poll immediately" before the runtime starts,
        # but it is not a timestamp in the monotonic clock's current epoch.
        # Anchor initial work to now so startup uptime is never reported as
        # scheduler poll lateness.
        now = self._clock()
        for state in self._states.values():
            state.next_poll_due = now
        self._scheduler_task = self.hass.async_create_background_task(
            self._async_scheduler_loop(),
            f"{DOMAIN}_controller_scheduler",
        )

    async def async_shutdown(self) -> None:
        """Stop all controller work and settle every waiter."""
        self._stopping = True
        self._wake.set()
        while self._commands:
            command = self._commands.popleft()
            if not command.future.done():
                command.future.set_exception(
                    Troy2ShutdownError("TRO.Y controller runtime is stopping")
                )
        task = self._scheduler_task
        self._scheduler_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._active_command is not None:
            future = self._active_command.future
            if not future.done():
                future.set_exception(
                    Troy2ShutdownError("TRO.Y controller runtime stopped")
                )
            self._active_command = None
        for state in self._states.values():
            self._stop_movement(state)

    async def async_open(self, shade_id: str) -> None:
        await self._async_submit_command(
            shade_id,
            lambda api: api.async_open(),
            target_position=100,
            direction="opening",
            track_movement=True,
        )

    async def async_close(self, shade_id: str) -> None:
        await self._async_submit_command(
            shade_id,
            lambda api: api.async_close(),
            target_position=0,
            direction="closing",
            track_movement=True,
        )

    async def async_stop(self, shade_id: str) -> None:
        await self._async_submit_command(
            shade_id,
            lambda api: api.async_stop(),
            track_movement=True,
        )

    async def async_set_position(self, shade_id: str, position: int) -> None:
        position = max(0, min(100, int(position)))
        current = self._states[shade_id].position
        direction = None
        if current is not None:
            if position > current:
                direction = "opening"
            elif position < current:
                direction = "closing"
        await self._async_submit_command(
            shade_id,
            lambda api: api.async_set_position(position),
            target_position=position,
            direction=direction,
            track_movement=True,
        )

    async def async_set_wired_speeds(
        self,
        shade_id: str,
        up_speed: int,
        down_speed: int,
        slow_speed: int,
    ) -> None:
        await self._async_submit_command(
            shade_id,
            lambda api: api.async_set_wired_speeds(
                up_speed,
                down_speed,
                slow_speed,
            ),
        )

    async def _async_submit_command(
        self,
        shade_id: str,
        operation: Callable[[Troy2Api], Awaitable[None]],
        *,
        target_position: int | None = None,
        direction: str | None = None,
        track_movement: bool = False,
    ) -> None:
        if self._stopping or not self.scheduler_running:
            raise Troy2ShutdownError("TRO.Y controller runtime is not running")
        future = asyncio.get_running_loop().create_future()
        self._commands.append(
            _CommandRequest(
                shade_id=shade_id,
                operation=operation,
                future=future,
                target_position=target_position,
                direction=direction,
                track_movement=track_movement,
            )
        )
        self._wake.set()
        await future

    async def _async_scheduler_loop(self) -> None:
        """Run commands and coalesced polls through one fair worker."""
        try:
            while not self._stopping:
                now = self._clock()
                due_state = self._select_due_state(now)
                command_allowed = self._commands and (
                    due_state is None
                    or self._consecutive_commands < _MAX_CONSECUTIVE_COMMANDS
                )
                if command_allowed:
                    self._active_command = self._commands.popleft()
                    try:
                        await self._async_execute_command(self._active_command)
                    except asyncio.CancelledError:
                        if not self._active_command.future.done():
                            self._active_command.future.set_exception(
                                Troy2ShutdownError(
                                    "TRO.Y controller runtime stopped during command"
                                )
                            )
                        raise
                    finally:
                        self._active_command = None
                    self._consecutive_commands += 1
                    continue
                if due_state is not None:
                    was_movement_poll = due_state.rapid_polling
                    await self._async_poll_state(due_state)
                    self._consecutive_commands = 0
                    self._consecutive_movement_polls = (
                        self._consecutive_movement_polls + 1
                        if was_movement_poll
                        else 0
                    )
                    continue
                await self._async_wait_for_work(now)
        except asyncio.CancelledError:
            return

    def _select_due_state(self, now: float) -> _ShadeRuntimeState | None:
        if self.context.poll_not_before > monotonic():
            return None
        due = [state for state in self._states.values() if state.next_poll_due <= now]
        if not due:
            return None
        moving = [state for state in due if state.rapid_polling]
        idle = [state for state in due if not state.rapid_polling]
        # Give rapid observation priority, but alternate with due idle work so
        # one or many moving shades cannot starve the rest of the controller.
        candidates = (
            moving
            if moving and (not idle or self._consecutive_movement_polls == 0)
            else idle
        )
        return min(candidates, key=lambda state: (state.next_poll_due, state.order))

    async def _async_wait_for_work(self, now: float) -> None:
        next_due = min(
            (state.next_poll_due for state in self._states.values()),
            default=now + DEFAULT_SCAN_INTERVAL_SECONDS,
        )
        delay = max(0.0, next_due - now)
        poll_delay = self.context.poll_not_before - monotonic()
        if poll_delay > 0:
            delay = max(delay, poll_delay)
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except TimeoutError:
            pass

    async def _async_execute_command(self, command: _CommandRequest) -> None:
        state = self._states[command.shade_id]
        state.last_attempt = self._clock()
        try:
            await command.operation(state.api)
        except Troy2Error as err:
            if not err.shutdown:
                self._record_failure(state, err)
            if not command.future.done():
                command.future.set_exception(err)
        except Exception as err:
            if not command.future.done():
                command.future.set_exception(err)
            raise
        else:
            self._record_success(state, verifies_state=False)
            if command.track_movement:
                self._start_movement(
                    state,
                    target_position=command.target_position,
                    direction=command.direction,
                )
            if not command.future.done():
                command.future.set_result(None)

    async def _async_poll_state(self, state: _ShadeRuntimeState) -> None:
        now = self._clock()
        state.poll_lateness = max(0.0, now - state.next_poll_due)
        state.max_poll_lateness = max(state.max_poll_lateness, state.poll_lateness)
        self._max_poll_lateness = max(self._max_poll_lateness, state.poll_lateness)
        state.last_attempt = now
        try:
            position = await state.api.async_get_position()
        except Troy2Error as err:
            if err.shutdown:
                return
            self._record_failure(state, err)
            self._update_movement_after_failure(state)
        else:
            state.position = position
            self._record_success(state)
            self._update_movement_after_position(state, position)
        finally:
            interval = (
                MOVEMENT_POLL_INTERVAL_SECONDS
                if state.rapid_polling
                else DEFAULT_SCAN_INTERVAL_SECONDS
            )
            interval = max(interval, self._failure_poll_backoff(state))
            state.next_poll_due = self._clock() + interval

    def _record_success(
        self,
        state: _ShadeRuntimeState,
        *,
        verifies_state: bool = True,
    ) -> None:
        now = self._clock()
        recovered = state.failure_started is not None
        state.last_success = now
        state.failure_started = None
        state.failure_category = None
        state.failure_reason = None
        state.consecutive_failures = 0
        state.confirmed_unavailable = False
        if verifies_state:
            state.verification_required = False
        self._last_controller_success = now
        controller_recovered = self._controller_confirmed_unavailable
        self._controller_failure_started = None
        self._controller_failure_shades.clear()
        self._controller_failure_count = 0
        self._controller_failure_category = None
        self._controller_confirmed_unavailable = False
        if recovered:
            _LOGGER.debug("TRO.Y shade communication recovered")
        if controller_recovered:
            _LOGGER.info("TRO.Y controller communication recovered")
            for other_state in self._states.values():
                if other_state.verification_required:
                    other_state.next_poll_due = min(other_state.next_poll_due, now)
            self._wake.set()
        self.async_set_updated_data(self._positions())

    def _record_failure(self, state: _ShadeRuntimeState, err: Troy2Error) -> None:
        now = self._clock()
        if state.failure_started is None:
            state.failure_started = now
            state.consecutive_failures = 0
        state.failure_category = err.category
        state.failure_reason = str(err)
        state.consecutive_failures += 1
        failure_age = max(0.0, now - state.failure_started)
        newly_unavailable = (
            not state.confirmed_unavailable
            and state.consecutive_failures >= 2
            and failure_age >= COMMUNICATION_FAILURE_GRACE_SECONDS
        )
        if newly_unavailable:
            state.confirmed_unavailable = True
        else:
            _LOGGER.debug(
                "Preserving TRO.Y shade state after %s failure; failure episode age %.1fs: %s",
                err.category,
                failure_age,
                err,
            )

        if err.controller_relevant:
            if self._controller_failure_started is None:
                self._controller_failure_started = now
            self._controller_failure_shades.add(state.api.shade.native_id)
            self._controller_failure_count += 1
            self._controller_failure_category = err.category
            required_shades = 1 if self.shade_count == 1 else 2
            controller_age = max(0.0, now - self._controller_failure_started)
            if (
                not self._controller_confirmed_unavailable
                and len(self._controller_failure_shades) >= required_shades
                and self._controller_failure_count >= 2
                and controller_age >= COMMUNICATION_FAILURE_GRACE_SECONDS
            ):
                self._controller_confirmed_unavailable = True
                for other_state in self._states.values():
                    other_state.verification_required = True
                self.async_set_update_error(
                    UpdateFailed(
                        "TRO.Y controller unavailable after sustained "
                        f"{err.category} failures"
                    )
                )
                return
        if newly_unavailable:
            _LOGGER.error(
                "TRO.Y shade unavailable after %.1fs of continuous %s failures: %s",
                failure_age,
                err.category,
                err,
            )
        self.async_set_updated_data(self._positions())

    def _start_movement(
        self,
        state: _ShadeRuntimeState,
        *,
        target_position: int | None,
        direction: str | None,
    ) -> None:
        now = self._clock()
        state.target_position = target_position
        state.movement_direction = direction
        state.rapid_polling = True
        state.movement_started = now
        state.movement_last_position = state.position
        state.movement_stable_polls = 0
        state.next_poll_due = now + MOVEMENT_POLL_INTERVAL_SECONDS
        self.async_set_updated_data(self._positions())
        self._wake.set()

    def _update_movement_after_position(
        self,
        state: _ShadeRuntimeState,
        position: int,
    ) -> None:
        if not state.rapid_polling:
            return
        if position == state.movement_last_position:
            state.movement_stable_polls += 1
        else:
            state.movement_stable_polls = 0
            state.movement_last_position = position
        elapsed = self._movement_age(state)
        reached_target = state.target_position is not None and position == state.target_position
        stable = (
            elapsed >= MOVEMENT_MINIMUM_POLL_SECONDS
            and state.movement_stable_polls >= MOVEMENT_STABLE_POLLS
        )
        if reached_target or stable or elapsed >= MOVEMENT_POLL_TIMEOUT_SECONDS:
            self._stop_movement(state)

    def _update_movement_after_failure(self, state: _ShadeRuntimeState) -> None:
        if state.rapid_polling and self._movement_age(state) >= MOVEMENT_POLL_TIMEOUT_SECONDS:
            self._stop_movement(state)

    def _stop_movement(self, state: _ShadeRuntimeState) -> None:
        state.target_position = None
        state.movement_direction = None
        state.rapid_polling = False
        state.movement_started = None
        state.movement_last_position = None
        state.movement_stable_polls = 0

    def _movement_age(self, state: _ShadeRuntimeState) -> float:
        if state.movement_started is None:
            return 0.0
        return max(0.0, self._clock() - state.movement_started)

    @staticmethod
    def _failure_poll_backoff(state: _ShadeRuntimeState) -> float:
        """Back off a repeatedly failing shade without changing HTTP timeout."""
        if state.consecutive_failures < 3:
            return 0.0
        exponent = state.consecutive_failures - 2
        return min(
            DEFAULT_SCAN_INTERVAL_SECONDS * (2**exponent),
            MAX_FAILURE_POLL_BACKOFF_SECONDS,
        )

    def _positions(self) -> dict[str, int]:
        return {
            shade_id: state.position
            for shade_id, state in self._states.items()
            if state.position is not None
        }

    def _age(self, timestamp: float | None) -> float | None:
        if timestamp is None:
            return None
        return max(0.0, self._clock() - timestamp)
