"""Tests for the serialized TRO.Y HTTP client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, call

import pytest

from custom_components.troy2.api import (
    Troy2Api,
    Troy2ConnectionError,
    Troy2ControllerContext,
    Troy2DiscoveryError,
    Troy2Error,
    Troy2HubApi,
    Troy2ShadeDescription,
    Troy2TransientPositionError,
    _async_request,
    normalize_host,
)


def _shade(
    native_id: str = "A1B2C3",
    *,
    wired: bool = True,
    node_id: str | None = None,
    label: str = "Test shade",
) -> Troy2ShadeDescription:
    return Troy2ShadeDescription(1, label, native_id, "", wired, node_id)


def _api(
    shade: Troy2ShadeDescription | None = None,
    context: Troy2ControllerContext | None = None,
) -> Troy2Api:
    return Troy2Api(None, "TROY.LOCAL", shade or _shade(), context or Troy2ControllerContext())


def test_normalize_host() -> None:
    assert normalize_host(" HTTPS://TROY.Local/// ") == "troy.local"
    assert normalize_host("192.0.2.10/") == "192.0.2.10"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [(100, 0), (0, 100), (37, 63)],
)
async def test_wired_position_scale(raw_value: int, expected: int) -> None:
    api = _api()
    api._async_request = AsyncMock(
        return_value={"rawSDN": "0D" + "00" * 10 + f"{raw_value:02X}"}
    )

    assert await api.async_get_position() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"msg": "file empty"},
        {},
        {"rawSDN": ""},
        {"rawSDN": "0E" + "00" * 11},
        {"rawSDN": "not-hex"},
    ],
)
async def test_wired_transient_position_responses(response: dict) -> None:
    api = _api()
    api._async_request = AsyncMock(return_value=response)

    with pytest.raises(Troy2TransientPositionError):
        await api.async_get_position()


@pytest.mark.asyncio
async def test_wireless_file_empty_does_not_trigger_node_lookup() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id="1234"))
    api._async_request = AsyncMock(
        return_value={"msg": "file empty"}
    )

    with pytest.raises(Troy2TransientPositionError):
        await api.async_get_position()

    assert api.node_id == "1234"
    assert api._async_request.await_count == 1


@pytest.mark.asyncio
async def test_wireless_node_address_re_resolution_recovers() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id="1234"))
    api._async_request = AsyncMock(
        side_effect=[
            {"result": False},
            {"node": "0x5678"},
            {"ATTR": {"attrValue": "25"}},
        ]
    )

    assert await api.async_get_position() == 75
    assert api.node_id == "5678"
    assert api._async_request.await_args_list[-1].args[0]["str1"] == "0x5678"


@pytest.mark.asyncio
async def test_wireless_timeout_does_not_monopolize_with_lookup_and_retry() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id="1234"))
    api._async_request = AsyncMock(
        side_effect=Troy2ConnectionError("TRO.Y request timed out after 10 seconds")
    )

    with pytest.raises(Troy2ConnectionError, match="timed out after 10 seconds"):
        await api.async_get_position()

    assert api._async_request.await_count == 1
    assert api.node_id == "1234"


@pytest.mark.asyncio
async def test_missing_wireless_node_is_resolved_once_then_polled() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id=None))
    api._async_request = AsyncMock(
        side_effect=[
            {"node": "0x5678"},
            {"ATTR": {"attrValue": "25"}},
        ]
    )

    assert await api.async_get_position() == 75
    assert api.node_id == "5678"
    assert api._async_request.await_count == 2


@pytest.mark.asyncio
async def test_malformed_wireless_position_stays_a_real_failure() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id="1234"))
    api._async_request = AsyncMock(
        side_effect=[{}, {"node": "5678"}, {"ATTR": {"attrValue": "bad"}}]
    )

    with pytest.raises(Troy2Error, match="Unexpected position response"):
        await api.async_get_position()


@pytest.mark.asyncio
async def test_wireless_command_re_resolves_after_rejection() -> None:
    api = _api(_shade("00124B0000000001", wired=False, node_id="1234"))
    api._async_request = AsyncMock(
        side_effect=[{"result": False}, {"node": "ABCD"}, {"result": True}]
    )

    await api.async_open()

    assert api.node_id == "ABCD"


@pytest.mark.asyncio
async def test_result_false_rejects_wired_command() -> None:
    api = _api()
    api._async_request = AsyncMock(return_value={"result": False})

    with pytest.raises(Troy2Error, match="rejected wired command"):
        await api.async_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "packet"),
    [
        ("async_open", "030F00010000C3B2A1010000000000"),
        ("async_close", "030F00010000C3B2A1000000000000"),
        ("async_stop", "020C00010000C3B2A1000000"),
    ],
)
async def test_wired_open_close_stop_packets_are_unchanged(
    method: str,
    packet: str,
) -> None:
    api = _api()
    api._async_request = AsyncMock(return_value={"result": True})

    await getattr(api, method)()

    assert api._async_request.await_args_list == [
        call({"cmd": "49", "str1": packet})
    ]


@pytest.mark.asyncio
async def test_wired_speed_uses_only_direction_safe_packet() -> None:
    api = _api()
    api._async_request = AsyncMock(return_value={"result": True})

    await api.async_set_wired_speeds(25, 10, 15)

    packets = [call.args[0]["str1"] for call in api._async_request.await_args_list]
    assert packets == ["130E00010000C3B2A1190A0F0000"]
    assert all(not packet.startswith("120C") for packet in packets)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("position", "expected_fragment"),
    [(100, "030F"), (0, "030F"), (50, "150F")],
)
async def test_wired_position_commands(position: int, expected_fragment: str) -> None:
    api = _api()
    api._async_request = AsyncMock(return_value={"result": True})

    await api.async_set_position(position)

    packets = [
        call.args[0].get("str1", "") for call in api._async_request.await_args_list
    ]
    assert any(packet.startswith(expected_fragment) for packet in packets)


@pytest.mark.asyncio
async def test_wired_intermediate_position_sequence_is_unchanged() -> None:
    api = _api()
    api._async_request = AsyncMock(return_value={"result": True})

    await api.async_set_position(50)

    assert [call.args[0] for call in api._async_request.await_args_list] == [
        {"cmd": "37", "int1": "5"},
        {
            "cmd": "49",
            "str1": "250C00010000C3B2A1090000",
            "str2": "35",
        },
        {"cmd": "37", "int1": "5"},
        {"cmd": "49", "str1": "150F00010000C3B2A1030932000000"},
        {"cmd": "37", "int1": "5"},
        {
            "cmd": "49",
            "str1": "250C00010000C3B2A1090000",
            "str2": "35",
        },
        {"cmd": "49", "str1": "030F00010000C3B2A1020900000000"},
        {"cmd": "49", "str1": "150F00010000C3B2A1000900000000"},
    ]


@pytest.mark.asyncio
async def test_eight_shade_commands_are_serialized() -> None:
    context = Troy2ControllerContext()
    active = 0
    maximum_active = 0
    calls: list[str] = []

    async def request(packet: str) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        calls.append(packet)
        active -= 1

    apis = [_api(_shade(f"{index:06X}"), context) for index in range(1, 9)]
    for api in apis:
        api._async_wired_request = request

    await asyncio.wait_for(
        asyncio.gather(*(api.async_open() for api in apis)),
        timeout=2,
    )

    assert maximum_active == 1
    assert len(calls) == 8


@pytest.mark.asyncio
async def test_multiple_shade_position_polls_are_serialized() -> None:
    context = Troy2ControllerContext()
    active = 0
    maximum_active = 0

    async def position() -> int:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return 50

    apis = [_api(_shade(f"{index:06X}"), context) for index in range(1, 7)]
    for api in apis:
        api._async_get_wired_position = position

    results = await asyncio.wait_for(
        asyncio.gather(*(api.async_get_position() for api in apis)),
        timeout=2,
    )

    assert maximum_active == 1
    assert results == [50] * 6


@pytest.mark.asyncio
async def test_repeated_and_rapid_direction_commands_are_serialized() -> None:
    api = _api()
    active = 0
    maximum_active = 0
    calls: list[str] = []

    async def request(packet: str) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        calls.append(packet)
        active -= 1

    api._async_wired_request = request
    commands = [
        command()
        for _ in range(5)
        for command in (api.async_open, api.async_close, api.async_stop)
    ]

    await asyncio.wait_for(asyncio.gather(*commands), timeout=2)

    assert maximum_active == 1
    assert len(calls) == 15


@pytest.mark.asyncio
async def test_command_waits_for_position_poll_without_deadlock() -> None:
    context = Troy2ControllerContext()
    api = _api(context=context)
    poll_entered = asyncio.Event()
    release_poll = asyncio.Event()
    events: list[str] = []

    async def get_position() -> int:
        events.append("poll-start")
        poll_entered.set()
        await release_poll.wait()
        events.append("poll-end")
        return 50

    async def command(packet: str) -> None:
        events.append(f"command-{packet[:4]}")

    api._async_get_wired_position = get_position
    api._async_wired_request = command
    poll_task = asyncio.create_task(api.async_get_position())
    await poll_entered.wait()
    command_task = asyncio.create_task(api.async_close())
    await asyncio.sleep(0)
    release_poll.set()

    await asyncio.wait_for(asyncio.gather(poll_task, command_task), timeout=2)

    assert events == ["poll-start", "poll-end", "command-030F"]


@pytest.mark.asyncio
async def test_discovery_skips_bad_duplicates_and_failed_node_lookup() -> None:
    hub = Troy2HubApi(None, "troy.local")

    async def request(params: dict[str, str]) -> dict:
        if params["cmd"] == "32":
            return {"indexes": [1, "bad", 2, 3, 4, 5], "maxUser": 480}
        if params["cmd"] == "2":
            if params["int1"] == "5":
                raise Troy2ConnectionError("one record temporarily unavailable")
            records = {
                "1": {
                    "type": 1,
                    "deviceFunction": "motor",
                    "nativeID": "A1B2C3",
                    "label": "Wired",
                },
                "2": {"type": 1, "deviceFunction": "motor"},
                "3": {
                    "type": 1,
                    "deviceFunction": "motor",
                    "nativeID": "A1B2C3",
                },
                "4": {
                    "type": 1,
                    "deviceFunction": "motor",
                    "nativeID": "00124B0000000001",
                    "label": "Wireless",
                },
            }
            return records[params["int1"]]
        return {"node": None}

    hub._async_request = request
    shades = await hub.async_discover_shades()

    assert [shade.native_id for shade in shades] == ["A1B2C3", "00124B0000000001"]
    assert shades[1].node_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [{}, {"indexes": "bad"}, {"indexes": [], "maxUser": "bad"}],
)
async def test_malformed_discovery_response(response: dict) -> None:
    hub = Troy2HubApi(None, "troy.local")
    hub._async_request = AsyncMock(return_value=response)

    with pytest.raises(Troy2DiscoveryError):
        await hub.async_discover_shades()


class _RuntimeSession:
    def __init__(self, *, closed: bool, message: str) -> None:
        self.closed = closed
        self.message = message

    def get(self, *args, **kwargs):
        raise RuntimeError(self.message)


class _Response:
    def __init__(self, value=None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self, **kwargs):
        if self.error:
            raise self.error
        return self.value


class _ResponseSession:
    closed = False

    def __init__(self, response: _Response) -> None:
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


class _TimeoutSession:
    closed = False

    def get(self, *args, **kwargs):
        raise TimeoutError("timed out")


@pytest.mark.asyncio
async def test_closed_session_is_normalized() -> None:
    session = _RuntimeSession(closed=True, message="Session is closed")

    with pytest.raises(Troy2ConnectionError, match="session closed"):
        await _async_request(session, "http://troy/troy.cgi", "troy", {})


@pytest.mark.asyncio
async def test_unrelated_runtime_error_is_not_suppressed() -> None:
    session = _RuntimeSession(closed=False, message="programming bug")

    with pytest.raises(RuntimeError, match="programming bug"):
        await _async_request(session, "http://troy/troy.cgi", "troy", {})


@pytest.mark.asyncio
async def test_invalid_json_is_communication_error() -> None:
    session = _ResponseSession(_Response(error=ValueError("invalid JSON")))

    with pytest.raises(Troy2Error, match="Invalid JSON response"):
        await _async_request(session, "http://troy/troy.cgi", "troy", {})


@pytest.mark.asyncio
async def test_http_timeout_is_communication_error() -> None:
    with pytest.raises(Troy2ConnectionError, match="timed out"):
        await _async_request(
            _TimeoutSession(),
            "http://troy/troy.cgi",
            "troy",
            {},
        )


@pytest.mark.asyncio
async def test_blank_timeout_has_meaningful_text_and_failed_counter() -> None:
    context = Troy2ControllerContext()

    with pytest.raises(
        Troy2ConnectionError,
        match="TRO.Y request timed out after 10 seconds",
    ):
        await _async_request(
            _TimeoutSession(),
            "http://troy/troy.cgi",
            "troy",
            {},
            context,
        )

    assert context.total_successful_requests == 0
    assert context.total_failed_requests == 1
    assert context.request_in_progress is False


@pytest.mark.asyncio
async def test_unexpected_json_type_is_protocol_error() -> None:
    session = _ResponseSession(_Response(value=[]))

    with pytest.raises(Troy2Error, match="Unexpected response type: list"):
        await _async_request(session, "http://troy/troy.cgi", "troy", {})
