"""Asynchronous TCP client for a CXA amplifier behind a transparent serial bridge.

Pure asyncio with no Home Assistant imports. Two layers:

* ``CXAConnection``: one TCP connection. It owns the only reader task, decodes
  frames, and serializes requests so at most one is in flight.
* ``CXAClient``: long-lived supervisor. It holds amplifier state, reconnects
  with capped exponential backoff, resyncs after every (re)connect, polls
  conservatively for liveness, and notifies listeners.

Correlation limits: the protocol has no transaction IDs. A reply is matched
to the in-flight request only by (group, number), and an error frame is
attributed to whatever request is in flight. A reply that arrives after its
request timed out can therefore be taken as the answer to a later request
with the same key. Every reply updates state regardless, so state stays
correct; only the success/failure verdict of a single command can be wrong,
and setters check the reported value to narrow that window.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import socket
from collections.abc import Callable
from dataclasses import dataclass, replace

from .protocol import (
    DEFAULT_GROUP_FORMAT,
    GET_FIRMWARE_VERSION,
    GET_MUTE,
    GET_POWER,
    GET_PROTOCOL_VERSION,
    GET_SOURCE,
    NEXT_SOURCE,
    PREVIOUS_SOURCE,
    SOURCES,
    Command,
    DeviceError,
    Event,
    FirmwareVersion,
    Frame,
    FrameDecoder,
    GroupFormat,
    MalformedFrame,
    Model,
    MuteState,
    PowerState,
    ProtocolVersion,
    SourceState,
    UnknownMessage,
    interpret,
    normalize_source_code,
    set_mute,
    set_power,
    set_source,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_REQUEST_TIMEOUT = 3.0
# Waking from standby may take longer than a plain query. Unmeasured; tune on hardware.
DEFAULT_POWER_TIMEOUT = 10.0
DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_BACKOFF_INITIAL = 1.0
DEFAULT_BACKOFF_MAX = 60.0
# Consecutive failed liveness polls before the connection is treated as dead.
POLL_FAILURES_BEFORE_RECONNECT = 2


# --- Errors -------------------------------------------------------------------


class CXAError(Exception):
    """Base class for client errors."""


class CXAConnectError(CXAError):
    """The TCP connection to the bridge could not be established."""


class CXANotConnectedError(CXAError):
    """A command was issued while no synced connection exists."""


class CXAConnectionLostError(CXAError):
    """The connection dropped while a request was in flight."""


class CXATimeoutError(CXAError):
    """No matching reply arrived in time."""


class CXARejectedError(CXAError):
    """The amplifier answered with a group 00 error frame."""

    def __init__(self, error: DeviceError) -> None:
        super().__init__(error.description)
        self.error = error


class CXANotConfirmedError(CXAError):
    """The amplifier replied, but reported a different value than requested."""


# --- Connection -----------------------------------------------------------------


@dataclass(slots=True)
class _Pending:
    reply_key: tuple[int, int]
    future: asyncio.Future[Event]


EventCallback = Callable[[Event], None]
LostCallback = Callable[[Exception | None], None]


class CXAConnection:
    """A single TCP connection. Not reusable after it closes."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        on_event: EventCallback | None = None,
        on_lost: LostCallback | None = None,
        group_format: GroupFormat = DEFAULT_GROUP_FORMAT,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._on_event = on_event
        self._on_lost = on_lost
        self._group_format = group_format
        self._decoder = FrameDecoder()
        self._lock = asyncio.Lock()
        self._pending: _Pending | None = None
        self._closed = False
        self.malformed_count = 0
        self.unknown_count = 0
        self._reader_task = asyncio.get_running_loop().create_task(
            self._read_loop(), name="cambridge_cxa_reader"
        )

    @classmethod
    async def open(
        cls,
        host: str,
        port: int,
        *,
        timeout: float = DEFAULT_CONNECT_TIMEOUT,
        on_event: EventCallback | None = None,
        on_lost: LostCallback | None = None,
        group_format: GroupFormat = DEFAULT_GROUP_FORMAT,
    ) -> CXAConnection:
        """Connect to the bridge's TCP server."""
        try:
            async with asyncio.timeout(timeout):
                reader, writer = await asyncio.open_connection(host, port)
        except (OSError, TimeoutError) as err:
            raise CXAConnectError(f"cannot connect to {host}:{port}: {err}") from err
        _enable_keepalive(writer)
        return cls(reader, writer, on_event=on_event, on_lost=on_lost, group_format=group_format)

    @property
    def closed(self) -> bool:
        """True once the connection is closed or lost."""
        return self._closed

    async def request(self, command: Command, timeout: float) -> Event:
        """Send a command and wait for its reply or a device error."""
        async with self._lock:
            if self._closed:
                raise CXANotConnectedError("connection is closed")
            future: asyncio.Future[Event] = asyncio.get_running_loop().create_future()
            # Register before writing: the reply may beat drain() back.
            self._pending = _Pending(command.reply, future)
            try:
                payload = command.encode(self._group_format)
                _LOGGER.debug("TX %r", payload)
                self._writer.write(payload)
                await self._writer.drain()
                async with asyncio.timeout(timeout):
                    return await future
            except TimeoutError as err:
                raise CXATimeoutError(f"no reply to {payload!r} within {timeout:.1f}s") from err
            except (OSError, RuntimeError) as err:
                # RuntimeError covers writes on a transport that is closing.
                self._handle_lost(err)
                raise CXAConnectionLostError(str(err)) from err
            finally:
                self._pending = None
                if future.done() and not future.cancelled():
                    future.exception()  # mark retrieved; avoids asyncio warnings

    async def close(self) -> None:
        """Close deliberately. Does not invoke ``on_lost``."""
        self._on_lost = None
        self._shutdown(CXAConnectionLostError("connection closed"))
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        with contextlib.suppress(OSError, TimeoutError):
            async with asyncio.timeout(1):
                await self._writer.wait_closed()

    async def _read_loop(self) -> None:
        error: Exception | None = None
        try:
            while True:
                data = await self._reader.read(1024)
                if not data:
                    _LOGGER.debug("Bridge closed the connection (EOF)")
                    break
                _LOGGER.debug("RX %r", data)
                for item in self._decoder.feed(data):
                    self._dispatch(item)
        except OSError as err:
            error = err
        except Exception as err:  # never die silently: drop and let the client reconnect
            _LOGGER.exception("Unexpected error in reader")
            error = err
        self._handle_lost(error)

    def _dispatch(self, item: Frame | MalformedFrame) -> None:
        if isinstance(item, MalformedFrame):
            self.malformed_count += 1
            _LOGGER.warning("Ignoring malformed data %r: %s", item.raw, item.reason)
            return
        event = interpret(item)
        if isinstance(event, UnknownMessage):
            self.unknown_count += 1
            _LOGGER.info("Ignoring %r: %s", event.frame.raw, event.reason)
            return
        # State first: replies are authoritative even if nobody asked.
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                _LOGGER.exception("Event callback failed")
        pending = self._pending
        if pending is None or pending.future.done():
            if isinstance(event, DeviceError):
                _LOGGER.warning("Unsolicited device error: %s", event.description)
            return
        if isinstance(event, DeviceError):
            pending.future.set_exception(CXARejectedError(event))
        elif item.key == pending.reply_key:
            pending.future.set_result(event)

    def _handle_lost(self, error: Exception | None) -> None:
        if self._closed:
            return
        self._shutdown(CXAConnectionLostError(str(error) if error else "connection lost"))
        callback, self._on_lost = self._on_lost, None
        if callback is not None:
            callback(error)

    def _shutdown(self, reason: Exception) -> None:
        self._closed = True
        pending = self._pending
        if pending is not None and not pending.future.done():
            pending.future.set_exception(reason)
        self._writer.close()


def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    """Best-effort TCP keepalive so a silently dead Wi-Fi link is noticed."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    with contextlib.suppress(OSError, AttributeError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        idle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
        if idle is not None:
            sock.setsockopt(socket.IPPROTO_TCP, idle, 30)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)


# --- Read-only probe for config validation ---------------------------------------


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """What a read-only connection test learned."""

    power: bool
    protocol_version: str | None
    firmware_version: str | None


async def fetch_device_info(
    host: str,
    port: int,
    *,
    group_format: GroupFormat = DEFAULT_GROUP_FORMAT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> DeviceInfo:
    """Connect, run read-only queries, disconnect. Never changes amplifier state.

    Raises CXAConnectError if the bridge is unreachable, CXATimeoutError if the
    bridge accepts TCP but the amplifier never answers (cable, serial settings
    or amplifier power), and CXARejectedError if the amplifier rejects the
    power query.
    """
    conn = await CXAConnection.open(host, port, timeout=connect_timeout, group_format=group_format)
    try:
        power = await conn.request(GET_POWER, request_timeout)
        if not isinstance(power, PowerState):  # cannot happen given reply-key matching
            raise CXAError(f"unexpected reply to power query: {power!r}")
        protocol = await _optional_query(conn, GET_PROTOCOL_VERSION, request_timeout)
        firmware = await _optional_query(conn, GET_FIRMWARE_VERSION, request_timeout)
    finally:
        await conn.close()
    return DeviceInfo(
        power=power.on,
        protocol_version=protocol.version if isinstance(protocol, ProtocolVersion) else None,
        firmware_version=firmware.version if isinstance(firmware, FirmwareVersion) else None,
    )


async def _optional_query(conn: CXAConnection, command: Command, timeout: float) -> Event | None:
    try:
        return await conn.request(command, timeout)
    except (CXATimeoutError, CXARejectedError) as err:
        _LOGGER.debug("Optional query %s,%s failed: %s", command.group, command.number, err)
        return None


# --- Long-lived client ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AmplifierState:
    """Last known amplifier state. ``None`` means unknown, never a default."""

    available: bool = False
    power: bool | None = None
    muted: bool | None = None
    source: str | None = None  # two-digit source code
    protocol_version: str | None = None
    firmware_version: str | None = None


StateListener = Callable[[AmplifierState], None]


class CXAClient:
    """Supervised connection with state tracking and automatic reconnect."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        model: Model = Model.CXA81,
        group_format: GroupFormat = DEFAULT_GROUP_FORMAT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        power_timeout: float = DEFAULT_POWER_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        backoff_initial: float = DEFAULT_BACKOFF_INITIAL,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
    ) -> None:
        self.host = host
        self.port = port
        self.model = model
        self._group_format = group_format
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._power_timeout = power_timeout
        self._poll_interval = poll_interval
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._state = AmplifierState()
        self._listeners: list[StateListener] = []
        self._conn: CXAConnection | None = None
        self._lost = asyncio.Event()
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = False
        self.reconnect_count = 0
        self.last_error: str | None = None

    # -- public API --

    @property
    def state(self) -> AmplifierState:
        """Current state snapshot (immutable)."""
        return self._state

    @property
    def sources(self) -> dict[str, str]:
        """Documented source codes and names for the configured model."""
        return SOURCES[self.model]

    def add_listener(self, listener: StateListener) -> Callable[[], None]:
        """Register a state listener; returns a function that removes it."""
        self._listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return remove

    async def start(self) -> None:
        """Connect and sync once (raising on failure), then supervise.

        If the first connection fails nothing is left running, so the caller
        (e.g. Home Assistant setup) can retry on its own schedule.
        """
        if self._supervisor is not None:
            raise RuntimeError("client already started")
        self._stopping = False
        await self._connect_and_sync()
        self._supervisor = asyncio.get_running_loop().create_task(
            self._supervise(), name="cambridge_cxa_supervisor"
        )

    async def stop(self) -> None:
        """Stop supervising and close the connection. Safe to call twice."""
        self._stopping = True
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        await self._drop_connection()
        self._set_state(available=False)

    async def async_set_power(self, on: bool) -> None:
        """Switch on or to standby, then confirm from the reply."""
        event = await self._command(set_power(on), self._power_timeout)
        if not isinstance(event, PowerState) or event.on != on:
            raise CXANotConfirmedError(f"amplifier reported {event!r} after set power {on}")
        if on:
            # Source/mute may not be pushed on wake-up; refresh them (read-only).
            await self._refresh_optional(GET_MUTE, GET_SOURCE)

    async def async_set_mute(self, muted: bool) -> None:
        """Mute or unmute, then confirm from the reply."""
        event = await self._command(set_mute(muted), self._request_timeout)
        if not isinstance(event, MuteState) or event.muted != muted:
            raise CXANotConfirmedError(f"amplifier reported {event!r} after set mute {muted}")

    async def async_set_source(self, code: str) -> None:
        """Select a documented source for this model, then confirm."""
        code = normalize_source_code(code)
        if code not in self.sources:
            raise ValueError(f"source {code} is not documented for {self.model.value}")
        event = await self._command(set_source(code), self._request_timeout)
        if not isinstance(event, SourceState) or event.code != code:
            raise CXANotConfirmedError(f"amplifier reported {event!r} after set source {code}")

    async def async_next_source(self) -> None:
        """Documented 03,02: select next source."""
        await self._command(NEXT_SOURCE, self._request_timeout)

    async def async_previous_source(self) -> None:
        """Documented 03,03: select previous source."""
        await self._command(PREVIOUS_SOURCE, self._request_timeout)

    async def async_refresh(self) -> None:
        """Re-read power, mute and source (read-only)."""
        await self._query(GET_POWER, self._request_timeout)
        await self._refresh_optional(GET_MUTE, GET_SOURCE)

    # -- internals --

    async def _command(self, command: Command, timeout: float) -> Event:
        # Commands are never queued or retried: no false success while offline
        # and no surprise replay after a reconnect.
        if not self._state.available:
            raise CXANotConnectedError("amplifier is not available")
        return await self._query(command, timeout)

    async def _query(self, command: Command, timeout: float) -> Event:
        conn = self._conn
        if conn is None or conn.closed:
            raise CXANotConnectedError("not connected")
        return await conn.request(command, timeout)

    async def _refresh_optional(self, *commands: Command) -> None:
        for command in commands:
            try:
                await self._query(command, self._request_timeout)
            except (CXATimeoutError, CXARejectedError) as err:
                _LOGGER.debug("Refresh %s,%s failed: %s", command.group, command.number, err)

    async def _connect_and_sync(self) -> None:
        await self._drop_connection()
        self._lost.clear()
        try:
            self._conn = await CXAConnection.open(
                self.host,
                self.port,
                timeout=self._connect_timeout,
                on_event=self._handle_event,
                on_lost=self._handle_lost,
                group_format=self._group_format,
            )
            # Forget per-connection state; unknown beats stale.
            self._set_state(power=None, muted=None, source=None)
            # The power query is the proof of life: it must succeed.
            await self._query(GET_POWER, self._request_timeout)
            await self._refresh_optional(
                GET_MUTE, GET_SOURCE, GET_PROTOCOL_VERSION, GET_FIRMWARE_VERSION
            )
        except CXAError as err:
            self.last_error = str(err)
            await self._drop_connection()
            raise
        self.last_error = None
        self._set_state(available=True)
        _LOGGER.debug("Connected and synced: %s", self._state)

    async def _supervise(self) -> None:
        failures = 0
        while True:
            try:
                async with asyncio.timeout(self._poll_interval):
                    await self._lost.wait()
            except TimeoutError:
                try:
                    await self._query(GET_POWER, self._request_timeout)
                    failures = 0
                except CXAError as err:
                    failures += 1
                    _LOGGER.debug("Liveness poll failed (%d): %s", failures, err)
                    if failures < POLL_FAILURES_BEFORE_RECONNECT:
                        continue
                    _LOGGER.warning("Amplifier stopped answering; reconnecting")
                    await self._drop_connection()
                else:
                    continue
            failures = 0
            self._set_state(available=False)
            await self._reconnect()

    async def _reconnect(self) -> None:
        delay = self._backoff_initial
        while True:
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))
            try:
                await self._connect_and_sync()
            except CXAError as err:
                _LOGGER.debug("Reconnect failed, next try in ~%.0fs: %s", delay, err)
                delay = min(delay * 2, self._backoff_max)
            else:
                self.reconnect_count += 1
                _LOGGER.info("Reconnected to %s:%s", self.host, self.port)
                return

    async def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await conn.close()

    def _handle_lost(self, error: Exception | None) -> None:
        if self._stopping:
            return
        self.last_error = str(error) if error else "connection lost"
        _LOGGER.warning("Lost connection to %s:%s: %s", self.host, self.port, self.last_error)
        self._set_state(available=False)
        self._lost.set()

    def _handle_event(self, event: Event) -> None:
        if isinstance(event, PowerState):
            self._set_state(power=event.on)
        elif isinstance(event, MuteState):
            self._set_state(muted=event.muted)
        elif isinstance(event, SourceState):
            if event.code not in self.sources:
                _LOGGER.warning("Amplifier reported undocumented source code %s", event.code)
            self._set_state(source=event.code)
        elif isinstance(event, ProtocolVersion):
            self._set_state(protocol_version=event.version)
        elif isinstance(event, FirmwareVersion):
            self._set_state(firmware_version=event.version)

    def _set_state(self, **changes: object) -> None:
        new = replace(self._state, **changes)  # type: ignore[arg-type]
        if new == self._state:
            return
        self._state = new
        for listener in list(self._listeners):
            try:
                listener(new)
            except Exception:
                _LOGGER.exception("State listener failed")
