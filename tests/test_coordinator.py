"""Tests for the controller-level TRO.Y runtime."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.troy2.api import (
    Troy2ControllerContext,
    Troy2Error,
    Troy2ShutdownError,
    Troy2TimeoutError,
    Troy2TransientPositionError,
)
from custom_components.troy2.coordinator import Troy2ControllerRuntime


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _api(index: int) -> SimpleNamespace:
    native_id = f"{index:06X}"
    return SimpleNamespace(
        host="troy.local",
        node_id=native_id,
        shade=SimpleNamespace(
            native_id=native_id,
            node_id=native_id,
            label=f"Shade {index}",
            wired=True,
        ),
        async_get_position=AsyncMock(return_value=50),
        async_open=AsyncMock(),
        async_close=AsyncMock(),
        async_stop=AsyncMock(),
        async_set_position=AsyncMock(),
        async_set_wired_speeds=AsyncMock(),
    )


def _runtime(hass, count: int, clock: _Clock | None = None):
    clock = clock or _Clock()
    apis = [_api(index) for index in range(count)]
    runtime = Troy2ControllerRuntime(
        hass,
        apis,
        Troy2ControllerContext(),
        clock=clock,
    )
    return runtime, apis, clock


def _state(runtime: Troy2ControllerRuntime, index: int):
    return runtime._states[f"{index:06X}"]


@pytest.mark.asyncio
async def test_alexis_old_success_first_new_failure_never_unavailable(
    hass,
    caplog,
) -> None:
    """An old successful poll must not pre-age a new failure episode."""
    runtime, apis, clock = _runtime(hass, 1)
    state = _state(runtime, 0)
    await runtime._async_poll_state(state)

    clock.now = 300
    apis[0].async_get_position.side_effect = Troy2TimeoutError(
        "TRO.Y request timed out after 10 seconds"
    )
    with caplog.at_level(logging.DEBUG):
        await runtime._async_poll_state(state)

    failed = runtime.shade_snapshot("000000")
    assert failed.last_success_age == 300
    assert failed.failure_episode_age == 0
    assert failed.consecutive_failures == 1
    assert failed.position == 50
    assert failed.available
    assert runtime.last_update_success
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]

    clock.now = 301
    apis[0].async_get_position.side_effect = None
    apis[0].async_get_position.return_value = 75
    await runtime._async_poll_state(state)

    recovered = runtime.shade_snapshot("000000")
    assert recovered.position == 75
    assert recovered.failure_episode_age is None
    assert recovered.consecutive_failures == 0
    assert recovered.available


@pytest.mark.asyncio
async def test_sustained_failure_becomes_unavailable_then_recovers(hass) -> None:
    runtime, apis, clock = _runtime(hass, 1)
    state = _state(runtime, 0)
    await runtime._async_poll_state(state)
    apis[0].async_get_position.side_effect = Troy2TimeoutError("timeout")

    clock.now = 100
    await runtime._async_poll_state(state)
    assert runtime.shade_snapshot("000000").available

    clock.now = 160
    await runtime._async_poll_state(state)
    assert not runtime.shade_snapshot("000000").available
    assert runtime.controller_confirmed_unavailable
    assert not runtime.last_update_success

    clock.now = 161
    apis[0].async_get_position.side_effect = None
    apis[0].async_get_position.return_value = 25
    await runtime._async_poll_state(state)
    snapshot = runtime.shade_snapshot("000000")
    assert snapshot.available
    assert snapshot.position == 25
    assert snapshot.failure_category is None
    assert runtime.last_update_success


@pytest.mark.asyncio
async def test_one_dead_shade_does_not_poison_healthy_twelve(hass) -> None:
    runtime, apis, clock = _runtime(hass, 13)
    for state in runtime._states.values():
        await runtime._async_poll_state(state)

    dead = _state(runtime, 0)
    apis[0].async_get_position.side_effect = Troy2TimeoutError("timeout")
    clock.now = 100
    await runtime._async_poll_state(dead)

    clock.now = 101
    await runtime._async_poll_state(_state(runtime, 1))

    clock.now = 161
    await runtime._async_poll_state(dead)

    assert not runtime.shade_snapshot("000000").available
    assert all(
        runtime.shade_snapshot(f"{index:06X}").available
        for index in range(1, 13)
    )
    assert not runtime.controller_confirmed_unavailable
    assert runtime.last_update_success


@pytest.mark.asyncio
async def test_multi_shade_controller_outage_and_clean_recovery(hass) -> None:
    runtime, apis, clock = _runtime(hass, 13)
    for state in runtime._states.values():
        await runtime._async_poll_state(state)
    for api in apis:
        api.async_get_position.side_effect = Troy2TimeoutError("timeout")

    clock.now = 100
    await runtime._async_poll_state(_state(runtime, 0))
    clock.now = 160
    await runtime._async_poll_state(_state(runtime, 1))

    assert runtime.controller_confirmed_unavailable
    assert all(
        not runtime.shade_snapshot(f"{index:06X}").available
        for index in range(13)
    )

    clock.now = 160.5
    runtime._record_success(_state(runtime, 2), verifies_state=False)
    assert not runtime.controller_confirmed_unavailable
    assert all(
        not runtime.shade_snapshot(f"{index:06X}").available
        for index in range(13)
    )

    clock.now = 161
    apis[2].async_get_position.side_effect = None
    await runtime._async_poll_state(_state(runtime, 2))
    assert not runtime.controller_confirmed_unavailable
    assert runtime.shade_snapshot("000002").available
    assert all(
        not runtime.shade_snapshot(f"{index:06X}").available
        for index in range(13)
        if index != 2
    )
    assert all(
        runtime.shade_snapshot(f"{index:06X}").verification_required
        for index in range(13)
        if index != 2
    )

    for index in (3, 4, 5):
        clock.now += 1
        apis[index].async_get_position.side_effect = None
        await runtime._async_poll_state(_state(runtime, index))
        assert runtime.shade_snapshot(f"{index:06X}").available
        assert not runtime.shade_snapshot(f"{index:06X}").verification_required

    assert not runtime.shade_snapshot("000000").available
    assert not runtime.shade_snapshot("000001").available


@pytest.mark.asyncio
@pytest.mark.parametrize("shade_count", [1, 2, 5, 10, 13])
async def test_all_idle_shades_receive_one_fair_round(hass, shade_count: int) -> None:
    runtime, apis, clock = _runtime(hass, shade_count)

    order = []
    for _ in range(shade_count):
        selected = runtime._select_due_state(clock.now)
        assert selected is not None
        order.append(selected.api.shade.native_id)
        await runtime._async_poll_state(selected)

    assert order == [f"{index:06X}" for index in range(shade_count)]
    assert all(api.async_get_position.await_count == 1 for api in apis)
    assert runtime._select_due_state(clock.now) is None


@pytest.mark.asyncio
async def test_movement_priority_alternates_with_overdue_idle_poll(hass) -> None:
    runtime, _, clock = _runtime(hass, 2)
    clock.now = 100
    moving = _state(runtime, 0)
    idle = _state(runtime, 1)
    moving.rapid_polling = True
    moving.next_poll_due = 99
    idle.next_poll_due = 80

    assert runtime._select_due_state(clock.now) is moving
    runtime._consecutive_movement_polls = 1
    assert runtime._select_due_state(clock.now) is idle


@pytest.mark.asyncio
async def test_several_moving_shades_all_receive_service(hass) -> None:
    runtime, apis, clock = _runtime(hass, 5)
    clock.now = 10
    for state in runtime._states.values():
        runtime._start_movement(state, target_position=100, direction="opening")
    clock.now = 11

    served = []
    for _ in range(5):
        state = runtime._select_due_state(clock.now)
        assert state is not None
        served.append(state.api.shade.native_id)
        await runtime._async_poll_state(state)

    assert served == [f"{index:06X}" for index in range(5)]
    assert all(api.async_get_position.await_count == 1 for api in apis)


@pytest.mark.asyncio
async def test_permanently_dead_shade_does_not_starve_poll_round(hass) -> None:
    runtime, apis, clock = _runtime(hass, 5)
    apis[0].async_get_position.side_effect = Troy2TimeoutError("timeout")

    served = []
    for _ in range(5):
        state = runtime._select_due_state(clock.now)
        assert state is not None
        served.append(state.api.shade.native_id)
        await runtime._async_poll_state(state)

    assert served == [f"{index:06X}" for index in range(5)]
    assert all(api.async_get_position.await_count == 1 for api in apis)


def test_poll_work_is_coalesced_and_bounded(hass) -> None:
    runtime, _, clock = _runtime(hass, 13)
    clock.now = 10_000

    assert runtime.pending_work_count == 13
    assert len(runtime._commands) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_count", [1, 2, 5])
async def test_real_timeout_capacity_backoff_and_healthy_lateness(
    hass,
    dead_count: int,
) -> None:
    """Each failed request consumes 10 seconds without monopolizing service."""
    runtime, apis, clock = _runtime(hass, 13)
    healthy_lateness: list[float] = []

    for index, state in enumerate(runtime._states.values()):
        state.position = 50
        state.last_success = 0
        state.next_poll_due = 20

        if index < dead_count:
            async def timeout() -> int:
                await asyncio.sleep(0)
                clock.now += 10
                raise Troy2TimeoutError("TRO.Y request timed out after 10 seconds")

            apis[index].async_get_position.side_effect = timeout
        else:
            async def success() -> int:
                await asyncio.sleep(0)
                return 50

            apis[index].async_get_position.side_effect = success

    clock.now = 20
    while clock.now < 900:
        selected = runtime._select_due_state(clock.now)
        if selected is None:
            clock.now = min(state.next_poll_due for state in runtime._states.values())
            continue
        await runtime._async_poll_state(selected)
        if selected.order >= dead_count:
            healthy_lateness.append(selected.poll_lateness)

    dead_attempts = [apis[index].async_get_position.await_count for index in range(dead_count)]
    healthy_attempts = [
        apis[index].async_get_position.await_count for index in range(dead_count, 13)
    ]
    assert max(healthy_lateness) == {1: 10, 2: 20, 5: 50}[dead_count]
    assert min(healthy_attempts) == {1: 41, 2: 40, 5: 35}[dead_count]
    assert dead_attempts == [7] * dead_count
    assert all(
        runtime.shade_snapshot(f"{index:06X}").failure_poll_backoff == 300
        for index in range(dead_count)
    )


@pytest.mark.asyncio
async def test_command_wait_is_limited_to_current_ten_second_request(hass) -> None:
    runtime, apis, clock = _runtime(hass, 13)
    entered = asyncio.Event()
    release = asyncio.Event()
    command_times: list[float] = []
    events: list[str] = []

    for state in runtime._states.values():
        state.position = 50
        state.last_success = 0
        state.next_poll_due = 100
    for index in range(5):
        _state(runtime, index).next_poll_due = 0

    async def timeout() -> int:
        entered.set()
        await release.wait()
        clock.now += 10
        events.append("active-timeout")
        raise Troy2TimeoutError("TRO.Y request timed out after 10 seconds")

    async def command() -> None:
        command_times.append(clock.now)
        events.append("command")

    def later_timeout(index: int):
        async def run() -> int:
            events.append(f"later-timeout-{index}")
            raise Troy2TimeoutError("timeout")

        return run

    apis[0].async_get_position.side_effect = timeout
    for index in range(1, 5):
        apis[index].async_get_position.side_effect = later_timeout(index)
    apis[12].async_open.side_effect = command
    await runtime.async_start()
    await entered.wait()
    submitted_at = clock.now
    command_task = asyncio.create_task(runtime.async_open("00000C"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(command_task, timeout=2)
    await runtime.async_shutdown()

    assert command_times == [submitted_at + 10]
    assert events[:2] == ["active-timeout", "command"]
    assert apis[0].async_get_position.await_count == 1


@pytest.mark.asyncio
async def test_async_start_does_not_wait_for_initial_position_timeout(hass) -> None:
    runtime, apis, _ = _runtime(hass, 13)
    entered = asyncio.Event()

    async def blocked_poll() -> int:
        entered.set()
        await asyncio.Event().wait()
        return 50

    for api in apis:
        api.async_get_position.side_effect = blocked_poll

    await asyncio.wait_for(runtime.async_start(), timeout=0.1)
    await entered.wait()

    assert runtime.scheduler_running
    assert sum(api.async_get_position.await_count for api in apis) == 1
    assert all(
        not runtime.shade_snapshot(f"{index:06X}").available
        for index in range(13)
    )
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_simultaneous_commands_are_serialized(hass) -> None:
    runtime, apis, _ = _runtime(hass, 13)
    active = 0
    maximum_active = 0
    order: list[str] = []

    async def command(label: str) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        order.append(label)
        await asyncio.sleep(0)
        active -= 1

    def command_for(index: int):
        async def run() -> None:
            await command(f"open-{index}")

        return run

    for index, api in enumerate(apis):
        api.async_open.side_effect = command_for(index)

    await runtime.async_start()
    await asyncio.wait_for(
        asyncio.gather(
            *(runtime.async_open(api.shade.native_id) for api in apis)
        ),
        timeout=2,
    )

    await runtime.async_shutdown()
    assert maximum_active == 1
    assert order == [f"open-{index}" for index in range(13)]


@pytest.mark.asyncio
async def test_command_runs_immediately_after_active_poll(hass) -> None:
    runtime, apis, clock = _runtime(hass, 2)
    await runtime.async_start()
    events: list[str] = []
    poll_entered = asyncio.Event()
    release_poll = asyncio.Event()

    async def slow_poll() -> int:
        events.append("poll-start")
        poll_entered.set()
        await release_poll.wait()
        events.append("poll-end")
        return 50

    async def close() -> None:
        events.append("command")

    apis[0].async_get_position.side_effect = slow_poll
    apis[1].async_close.side_effect = close
    clock.now = 20
    _state(runtime, 0).next_poll_due = 20
    _state(runtime, 1).next_poll_due = 40
    runtime._wake.set()
    await poll_entered.wait()
    command_task = asyncio.create_task(runtime.async_close("000001"))
    await asyncio.sleep(0)
    release_poll.set()
    await asyncio.wait_for(command_task, timeout=2)

    assert events == ["poll-start", "poll-end", "command"]
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_command_burst_cannot_starve_due_poll(hass) -> None:
    runtime, apis, clock = _runtime(hass, 2)
    events: list[str] = []
    await runtime.async_start()
    for api in apis:
        api.async_open.side_effect = lambda: events.append("command")
    apis[0].async_get_position.side_effect = lambda: events.append("poll") or 50
    clock.now = 20
    _state(runtime, 0).next_poll_due = 20
    _state(runtime, 1).next_poll_due = 40

    commands = [asyncio.create_task(runtime.async_open("000001")) for _ in range(6)]
    await asyncio.wait_for(asyncio.gather(*commands), timeout=2)

    assert events.index("poll") == 4
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_rapid_reversal_replaces_only_commanded_shade(hass) -> None:
    runtime, _, _ = _runtime(hass, 2)
    await runtime.async_start()
    await runtime.async_open("000000")
    await runtime.async_open("000001")
    await runtime.async_close("000000")

    first = runtime.shade_snapshot("000000")
    second = runtime.shade_snapshot("000001")
    assert first.target_position == 0
    assert first.movement_direction == "closing"
    assert second.target_position == 100
    assert second.movement_direction == "opening"
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_failed_command_does_not_create_movement_state(hass) -> None:
    runtime, apis, _ = _runtime(hass, 1)
    await runtime.async_start()
    apis[0].async_open.side_effect = Troy2Error("rejected")

    with pytest.raises(Troy2Error, match="rejected"):
        await runtime.async_open("000000")

    snapshot = runtime.shade_snapshot("000000")
    assert not snapshot.rapid_polling
    assert snapshot.movement_direction is None
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_stop_and_target_completion_end_movement_correctly(hass) -> None:
    runtime, apis, clock = _runtime(hass, 1)
    await runtime.async_start()
    await runtime.async_stop("000000")
    stopped = runtime.shade_snapshot("000000")
    assert stopped.rapid_polling
    assert stopped.movement_direction is None

    await runtime.async_set_position("000000", 75)
    apis[0].async_get_position.return_value = 75
    clock.now = 1
    await runtime._async_poll_state(_state(runtime, 0))
    completed = runtime.shade_snapshot("000000")
    assert not completed.rapid_polling
    assert completed.target_position is None
    await runtime.async_shutdown()


@pytest.mark.asyncio
async def test_stable_position_and_timeout_end_rapid_tracking(hass) -> None:
    runtime, apis, clock = _runtime(hass, 2)
    for state in runtime._states.values():
        await runtime._async_poll_state(state)
    first = _state(runtime, 0)
    second = _state(runtime, 1)
    runtime._start_movement(first, target_position=None, direction=None)
    runtime._start_movement(second, target_position=100, direction="opening")

    for now in (4, 5, 6):
        clock.now = now
        await runtime._async_poll_state(first)
    assert not runtime.shade_snapshot("000000").rapid_polling

    clock.now = 91
    apis[1].async_get_position.side_effect = Troy2TransientPositionError("file empty")
    await runtime._async_poll_state(second)
    assert not runtime.shade_snapshot("000001").rapid_polling


@pytest.mark.asyncio
async def test_transient_and_malformed_responses_have_distinct_categories(hass) -> None:
    runtime, apis, clock = _runtime(hass, 2)
    for state in runtime._states.values():
        await runtime._async_poll_state(state)

    clock.now = 20
    apis[0].async_get_position.side_effect = Troy2TransientPositionError("file empty")
    apis[1].async_get_position.side_effect = Troy2Error("malformed response")
    await runtime._async_poll_state(_state(runtime, 0))
    await runtime._async_poll_state(_state(runtime, 1))

    assert runtime.shade_snapshot("000000").failure_category == "transient_position"
    assert runtime.shade_snapshot("000001").failure_category == "protocol"
    assert runtime.shade_snapshot("000000").available
    assert runtime.shade_snapshot("000001").available


@pytest.mark.asyncio
async def test_shutdown_clears_movement_and_waiting_scheduler(hass) -> None:
    runtime, _, _ = _runtime(hass, 2)
    await runtime.async_start()
    await runtime.async_open("000000")
    await runtime.async_shutdown()

    assert not runtime.scheduler_running
    assert not runtime.shade_snapshot("000000").rapid_polling


@pytest.mark.asyncio
async def test_shutdown_during_command_settles_waiter_without_traceback(hass) -> None:
    runtime, apis, _ = _runtime(hass, 1)
    await runtime.async_start()
    entered = asyncio.Event()

    async def blocked_command() -> None:
        entered.set()
        await asyncio.Event().wait()

    apis[0].async_open.side_effect = blocked_command
    command = asyncio.create_task(runtime.async_open("000000"))
    await entered.wait()
    await runtime.async_shutdown()

    with pytest.raises(Troy2ShutdownError, match="stopped during command"):
        await command
    assert not runtime.scheduler_running


@pytest.mark.asyncio
async def test_shutdown_session_closure_is_silent(hass, caplog) -> None:
    runtime, apis, _ = _runtime(hass, 1)
    apis[0].async_get_position.side_effect = Troy2ShutdownError("session closed")

    with caplog.at_level(logging.DEBUG):
        await runtime._async_poll_state(_state(runtime, 0))

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_runtime_can_reload_after_shutdown(hass) -> None:
    first, _, _ = _runtime(hass, 1)
    await first.async_start()
    await first.async_shutdown()
    second, _, _ = _runtime(hass, 1)
    await second.async_start()

    assert second.scheduler_running
    assert second.shade_snapshot("000000").available
    await second.async_shutdown()
