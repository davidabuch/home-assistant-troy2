"""Local HTTP client for Screen Innovations TRO.Y 2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientSession


class Troy2Error(Exception):
    """Base TRO.Y 2 communication error."""


class Troy2TransientPositionError(Troy2Error):
    """A temporary empty or incomplete position response."""


class Troy2ControllerContext:
    """Coordinate all traffic sent to one TRO.Y controller."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.poll_not_before = 0.0

    def defer_position_polls(self, seconds: float = 2.0) -> None:
        """Keep background polling away from a just-issued command."""
        self.poll_not_before = max(self.poll_not_before, monotonic() + seconds)

    async def wait_until_poll_allowed(self) -> None:
        """Wait until the controller has had time to process commands."""
        delay = self.poll_not_before - monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass(frozen=True, slots=True)
class Troy2ShadeDescription:
    """A motor discovered in the TRO.Y Device Integration Table."""

    vadr_entry: int
    label: str
    native_id: str
    assigned_id: str
    wired: bool
    node_id: str | None


class Troy2HubApi:
    """Controller-level client used for discovery."""

    def __init__(self, session: ClientSession, host: str) -> None:
        self._session = session
        self._host = _normalize_host(host)
        self._url = f"http://{self._host}/troy.cgi"

    @property
    def host(self) -> str:
        return self._host

    async def async_discover_shades(self) -> list[Troy2ShadeDescription]:
        """Discover all user-created motor records."""
        index_data = await self._async_request({"cmd": "32"})
        indexes = index_data.get("indexes")
        max_user = index_data.get("maxUser", 480)
        if not isinstance(indexes, list):
            raise Troy2Error(f"Unexpected device index response: {index_data}")

        shades: list[Troy2ShadeDescription] = []
        for raw_index in indexes:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if index > int(max_user):
                continue

            record = await self._async_request(
                {"cmd": "2", "int1": str(index)}
            )
            if record.get("type") != 1 or record.get("deviceFunction") != "motor":
                continue

            native_id = str(record.get("nativeID", "")).strip().upper()
            if not native_id:
                continue
            wired = len(native_id) == 6
            node_id = None
            if not wired:
                node_id = await self.async_lookup_node(native_id)

            shades.append(
                Troy2ShadeDescription(
                    vadr_entry=index,
                    label=str(record.get("label") or f"TRO.Y Shade {index}"),
                    native_id=native_id,
                    assigned_id=str(record.get("assignedID", "")),
                    wired=wired,
                    node_id=node_id,
                )
            )
        return shades

    async def async_lookup_node(self, native_id: str) -> str:
        """Translate a permanent wireless IEEE ID into its current NWK ID."""
        data = await self._async_request(
            {"cmd": "71", "int1": "31", "str1": native_id}
        )
        node = data.get("node")
        if not isinstance(node, str) or not node:
            raise Troy2Error(f"Unable to resolve wireless node for {native_id}: {data}")
        return node.upper().removeprefix("0X")

    async def _async_request(self, params: dict[str, str]) -> dict[str, Any]:
        return await _async_request(self._session, self._url, self._host, params)


class Troy2Api:
    """Client for one discovered TRO.Y shade."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        shade: Troy2ShadeDescription,
        context: Troy2ControllerContext,
    ) -> None:
        self._session = session
        self._host = _normalize_host(host)
        self._shade = shade
        self._context = context
        self._node_id = shade.node_id
        self._url = f"http://{self._host}/troy.cgi"

    @property
    def host(self) -> str:
        return self._host

    @property
    def node_id(self) -> str:
        return self._node_id or self._shade.native_id

    @property
    def shade(self) -> Troy2ShadeDescription:
        return self._shade

    async def async_get_position(self) -> int:
        """Return position using Home Assistant's 0-closed/100-open scale."""
        while True:
            await self._context.wait_until_poll_allowed()
            async with self._context.lock:
                # A command may have deferred polling while this poll was
                # waiting for the lock. Recheck before touching TRO.Y.
                if self._context.poll_not_before > monotonic():
                    continue
                if self._shade.wired:
                    troy_position = await self._async_get_wired_position()
                else:
                    troy_position = await self._async_get_wireless_position()
                break
        return 100 - troy_position

    async def async_open(self) -> None:
        async with self._context.lock:
            if self._shade.wired:
                await self._async_wired_command("UP")
            else:
                await self._async_wireless_command("UP")
            self._context.defer_position_polls()

    async def async_close(self) -> None:
        async with self._context.lock:
            if self._shade.wired:
                await self._async_wired_command("DOWN")
            else:
                await self._async_wireless_command("DOWN")
            self._context.defer_position_polls()

    async def async_stop(self) -> None:
        async with self._context.lock:
            if self._shade.wired:
                await self._async_wired_command("STOP")
            else:
                await self._async_wireless_command("STOP")
            self._context.defer_position_polls()

    async def async_set_position(self, position: int) -> None:
        """Set a Home Assistant position after converting to TRO.Y's scale."""
        position = max(0, min(100, int(position)))
        troy_position = 100 - position
        async with self._context.lock:
            if self._shade.wired:
                # Somfy SDN exact-position commands support intermediate values.
                # The two travel limits use the dedicated UP/DOWN commands.
                if position == 100:
                    await self._async_wired_command("UP")
                elif position == 0:
                    await self._async_wired_command("DOWN")
                else:
                    await self._async_set_wired_position(troy_position)
            else:
                params = {
                    "cmd": "71",
                    "int1": "18",
                    "str1": self._wireless_node(),
                    "str2": "GOTO",
                    "str3": str(troy_position),
                }
                data = await self._async_request(params)
                if data.get("result") is not True:
                    raise Troy2Error(f"TRO.Y rejected GOTO command: {data}")
            self._context.defer_position_polls()

    async def async_set_wired_speeds(
        self,
        up_speed: int,
        down_speed: int,
        slow_speed: int,
    ) -> None:
        """Set the three persistent rolling speeds of an RS485 motor."""
        if not self._shade.wired:
            raise Troy2Error(
                f"Speed settings are only supported for wired shades; "
                f"{self._shade.label} is wireless"
            )

        speeds = (up_speed, down_speed, slow_speed)
        if any(not 0 <= speed <= 0xFF for speed in speeds):
            raise Troy2Error("Wired motor speeds must fit in one byte")

        async with self._context.lock:
            address = self._wired_address()

            # Change rolling speeds only. Motor direction is an independent
            # persistent setting and must remain untouched.
            await self._async_wired_request(
                f"130E00010000{address}"
                f"{up_speed:02X}{down_speed:02X}{slow_speed:02X}0000"
            )
            self._context.defer_position_polls()

    async def _async_get_wireless_position(self) -> int:
        params = {
            "cmd": "71",
            "int1": "18",
            "int2": "1000",
            "str1": f"0x{self._wireless_node()}",
            "str2": "LEVEL_RD",
        }
        data = await self._async_request(params)
        try:
            value = int(data["ATTR"]["attrValue"])
        except (KeyError, TypeError, ValueError) as err:
            raise Troy2Error(f"Unexpected position response: {data}") from err
        return max(0, min(100, value))

    async def _async_get_wired_position(self) -> int:
        """Read the motor's live physical position."""
        address = self._wired_address()
        packet = f"0C0B00010000{address}0000"
        data = await self._async_request(
            {"cmd": "49", "str1": packet, "str2": "0D"}
        )
        if data.get("msg") == "file empty":
            raise Troy2TransientPositionError("TRO.Y position response not ready")
        raw_sdn = data.get("rawSDN")
        if not isinstance(raw_sdn, str):
            raise Troy2TransientPositionError(
                f"Incomplete wired position response: {data}"
            )
        try:
            raw = bytes.fromhex(raw_sdn)
            if raw[0] != 0x0D:
                raise ValueError(f"Expected POST_MOTOR_POSITION, got {raw[0]:02X}")
            value = raw[11]
        except (ValueError, IndexError) as err:
            raise Troy2TransientPositionError(
                f"Incomplete wired position packet: {raw_sdn}"
            ) from err
        return max(0, min(100, value))

    async def _async_get_wired_intermediate_position(self) -> None:
        """Run TRO.Y's IP-slot query used by its wired GO sequence."""
        address = self._wired_address()
        packet = f"250C00010000{address}090000"
        await self._async_request(
            {"cmd": "49", "str1": packet, "str2": "35"}
        )

    async def _async_set_wired_position(self, troy_position: int) -> None:
        """Reproduce TRO.Y's complete SDN go-to-position sequence."""
        address = self._wired_address()

        # TRO.Y prepares its wired/SDN routing context before each of the first
        # three transactions. The captured selector is the constant int1=5;
        # it is not the motor's Device Integration Table index.
        await self._async_select_wired_device()
        await self._async_get_wired_intermediate_position()

        await self._async_select_wired_device()
        await self._async_wired_request(
            f"150F00010000{address}0309{troy_position:02X}000000"
        )

        await self._async_select_wired_device()
        await self._async_get_wired_intermediate_position()

        # Execute the move-to-programmed-position command, then complete the
        # same register sequence used by the TRO.Y Device Integration Table.
        await self._async_wired_request(
            f"030F00010000{address}020900000000"
        )
        await self._async_wired_request(
            f"150F00010000{address}000900000000"
        )

    async def _async_select_wired_device(self) -> None:
        """Prepare the wired interface exactly as the TRO.Y UI does."""
        await self._async_request({"cmd": "37", "int1": "5"})

    async def _async_wireless_command(self, command: str) -> None:
        params = {
            "cmd": "71",
            "int1": "18",
            "str1": f"0x{self._wireless_node()}",
            "str2": command,
        }
        data = await self._async_request(params)
        if data.get("result") is not True:
            raise Troy2Error(f"TRO.Y rejected {command} command: {data}")

    async def _async_wired_command(self, command: str) -> None:
        address = self._wired_address()
        if command == "UP":
            packet = f"030F00010000{address}010000000000"
        elif command == "DOWN":
            packet = f"030F00010000{address}000000000000"
        else:
            packet = f"020C00010000{address}000000"
        await self._async_wired_request(packet)

    async def _async_wired_request(self, packet: str) -> None:
        data = await self._async_request({"cmd": "49", "str1": packet})
        # SDN command responses are not uniform. Some return {"result": true},
        # while others return a different successful JSON payload. An HTTP 200
        # response is accepted unless TRO.Y explicitly reports result=false.
        if data.get("result") is False:
            raise Troy2Error(f"TRO.Y rejected wired command: {data}")

    def _wireless_node(self) -> str:
        if not self._node_id:
            raise Troy2Error(f"No wireless node address for {self._shade.label}")
        return self._node_id

    def _wired_address(self) -> str:
        try:
            raw = bytes.fromhex(self._shade.native_id)
        except ValueError as err:
            raise Troy2Error(f"Invalid wired native ID: {self._shade.native_id}") from err
        if len(raw) != 3:
            raise Troy2Error(f"Invalid wired native ID: {self._shade.native_id}")
        return raw[::-1].hex().upper()

    async def _async_request(self, params: dict[str, str]) -> dict[str, Any]:
        return await _async_request(self._session, self._url, self._host, params)


def _normalize_host(host: str) -> str:
    return host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")


async def _async_request(
    session: ClientSession,
    url: str,
    host: str,
    params: dict[str, str],
) -> dict[str, Any]:
    try:
        async with session.get(url, params=params, timeout=10) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        raise Troy2Error(f"Unable to communicate with TRO.Y 2 at {host}: {err}") from err
    if not isinstance(data, dict):
        raise Troy2Error(f"Unexpected response type: {type(data).__name__}")
    return data
