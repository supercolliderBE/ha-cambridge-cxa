"""Client tests against the independent mock amplifier over real loopback TCP.

These prove the client handles the behaviours we *model*; they do not prove
the real CXA81 behaves the same way. See docs/hardware-validation.md.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import pytest

from custom_components.cambridge_cxa_home import protocol as p
from custom_components.cambridge_cxa_home.client import (
    AmplifierState,
    CXAClient,
    CXAConnectError,
    CXAConnection,
    CXAConnectionLostError,
    CXANotConfirmedError,
    CXANotConnectedError,
    CXARejectedError,
    CXATimeoutError,
    fetch_device_info,
)
from tools.mock_amplifier import MockAmplifier, MockState

from .conftest import HOST, wait_for

# Real loopback TCP is the point of these tests; the HA plugin still restricts
# connections to 127.0.0.1.
pytestmark = pytest.mark.usefixtures("socket_enabled")

FAST = {
    "connect_timeout": 1.0,
    "request_timeout": 0.3,
    "power_timeout": 0.5,
    "backoff_initial": 0.02,
    "backoff_max": 0.1,
}


def _client(amp: MockAmplifier, **kwargs: object) -> CXAClient:
    return CXAClient(HOST, amp.port, **{**FAST, **kwargs})  # type: ignore[arg-type,attr-defined]


@pytest.fixture
async def client(amp: MockAmplifier) -> AsyncIterator[CXAClient]:
    c = _client(amp)
    await c.start()
    yield c
    await c.stop()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


WRITE_PREFIXES = (b"#1,02", b"#1,04", b"#3,02", b"#3,03", b"#3,04")


def _writes(amp: MockAmplifier) -> list[bytes]:
    return [line for line in amp.received if line.startswith(WRITE_PREFIXES)]


def _our_tasks() -> list[asyncio.Task[object]]:
    return [
        t for t in asyncio.all_tasks() if t.get_name().startswith("cambridge_cxa") and not t.done()
    ]


# --- read-only connection test (config flow validation) --------------------------


async def test_fetch_device_info_is_read_only(amp: MockAmplifier) -> None:
    amp.state = MockState(power=False, muted=True, source="03")
    info = await fetch_device_info(HOST, amp.port)  # type: ignore[attr-defined]
    assert info.power is False
    assert info.protocol_version == "1.0"
    assert info.firmware_version == "SYNTHETIC-0.0"
    assert amp.received == [b"#1,01", b"#13,01", b"#13,02"]
    assert amp.state == MockState(power=False, muted=True, source="03")
    await wait_for(lambda: amp.client_count == 0)


async def test_fetch_device_info_unreachable() -> None:
    with pytest.raises(CXAConnectError):
        await fetch_device_info(HOST, _free_port(), connect_timeout=0.5)


async def test_fetch_device_info_bridge_up_amplifier_silent(amp: MockAmplifier) -> None:
    amp.behaviour.unresponsive = True
    with pytest.raises(CXATimeoutError):
        await fetch_device_info(HOST, amp.port, request_timeout=0.2)  # type: ignore[attr-defined]


async def test_group_format_rejected_is_reported(amp: MockAmplifier) -> None:
    """If firmware only accepts padded groups, the unpadded probe gets 00,01."""
    amp.behaviour.accept_group_format = "padded"
    with pytest.raises(CXARejectedError) as err:
        await fetch_device_info(HOST, amp.port)  # type: ignore[attr-defined]
    assert err.value.error.code is p.ErrorCode.GROUP_UNKNOWN
    info = await fetch_device_info(
        HOST,
        amp.port,  # type: ignore[attr-defined]
        group_format=p.GroupFormat.PADDED,
    )
    assert info.power is True
    assert amp.received[-3:] == [b"#01,01", b"#13,01", b"#13,02"]


async def test_version_queries_optional(amp: MockAmplifier) -> None:
    """Some firmware might reject version queries; that must not fail setup."""
    original = amp._process

    def no_versions(line: bytes) -> list[str] | None:
        return ["#00,02"] if line.startswith(b"#13") else original(line)

    amp._process = no_versions  # type: ignore[method-assign]
    info = await fetch_device_info(HOST, amp.port)  # type: ignore[attr-defined]
    assert info.protocol_version is None
    assert info.firmware_version is None


# --- startup and sync -----------------------------------------------------------------


async def test_start_syncs_state(client: CXAClient) -> None:
    assert client.state == AmplifierState(
        available=True,
        power=True,
        muted=False,
        source="20",
        protocol_version="1.0",
        firmware_version="SYNTHETIC-0.0",
    )


async def test_startup_never_writes(amp: MockAmplifier, client: CXAClient) -> None:
    assert _writes(amp) == []


async def test_start_failure_leaves_nothing_running() -> None:
    c = CXAClient(HOST, _free_port(), **FAST)  # type: ignore[arg-type]
    with pytest.raises(CXAConnectError):
        await c.start()
    assert _our_tasks() == []
    assert c.state.available is False


async def test_start_in_standby_with_silent_queries(amp: MockAmplifier) -> None:
    """Unknown stays unknown: no invented mute/source defaults."""
    amp.state.power = False
    amp.behaviour.standby_mode = "silent"
    c = _client(amp)
    await c.start()
    try:
        assert c.state.available is True
        assert c.state.power is False
        assert c.state.muted is None
        assert c.state.source is None
    finally:
        await c.stop()


async def test_start_in_standby_with_rejected_queries(amp: MockAmplifier) -> None:
    amp.state.power = False
    amp.behaviour.standby_mode = "reject_all_but_power"
    c = _client(amp)
    await c.start()
    try:
        assert (c.state.available, c.state.power, c.state.muted, c.state.source) == (
            True,
            False,
            None,
            None,
        )
    finally:
        await c.stop()


async def test_double_start_rejected(client: CXAClient) -> None:
    with pytest.raises(RuntimeError):
        await client.start()


# --- commands ------------------------------------------------------------------------


async def test_set_power(amp: MockAmplifier, client: CXAClient) -> None:
    await client.async_set_power(False)
    assert client.state.power is False
    assert amp.state.power is False
    await client.async_set_power(True)
    assert client.state.power is True
    assert _writes(amp) == [b"#1,02,0", b"#1,02,1"]


async def test_power_on_refreshes_mute_and_source(amp: MockAmplifier) -> None:
    amp.state = MockState(power=False, muted=False, source="20")
    amp.behaviour.standby_mode = "silent"
    c = _client(amp)
    await c.start()
    try:
        assert c.state.source is None
        await c.async_set_power(True)
        assert c.state.source == "20"
        assert c.state.muted is False
    finally:
        await c.stop()


async def test_slow_wake_uses_power_timeout(amp: MockAmplifier, client: CXAClient) -> None:
    """Waking may take longer than a normal request; power has its own timeout."""
    await client.async_set_power(False)
    amp.behaviour.power_on_delay = 0.4  # > request_timeout 0.3, < power_timeout 0.5
    await client.async_set_power(True)
    assert client.state.power is True


async def test_wake_slower_than_power_timeout(amp: MockAmplifier, client: CXAClient) -> None:
    await client.async_set_power(False)
    amp.behaviour.power_on_delay = 0.8
    with pytest.raises(CXATimeoutError):
        await client.async_set_power(True)
    await wait_for(lambda: client.state.power is True)  # late reply still counts


async def test_set_mute(amp: MockAmplifier, client: CXAClient) -> None:
    await client.async_set_mute(True)
    assert client.state.muted is True
    assert amp.state.muted is True
    await client.async_set_mute(False)
    assert client.state.muted is False


@pytest.mark.parametrize("code", ["00", "20", "14", "16", "2"])
async def test_set_source(amp: MockAmplifier, client: CXAClient, code: str) -> None:
    await client.async_set_source(code)
    expected = p.normalize_source_code(code)
    assert client.state.source == expected
    assert amp.state.source == expected
    assert _writes(amp) == [f"#3,04,{expected}".encode()]


async def test_set_undocumented_source_refused_locally(
    amp: MockAmplifier, client: CXAClient
) -> None:
    with pytest.raises(ValueError):
        await client.async_set_source("10")  # MP3 exists on CXA61 only
    assert _writes(amp) == []


async def test_next_previous_source(amp: MockAmplifier, client: CXAClient) -> None:
    await client.async_next_source()
    assert client.state.source == "00"  # 20 is last in the mock's order; wraps
    await client.async_previous_source()
    assert client.state.source == "20"


async def test_device_error_rejects_command(amp: MockAmplifier, client: CXAClient) -> None:
    await client.async_set_power(False)
    with pytest.raises(CXARejectedError) as err:
        await client.async_set_mute(True)  # mock rejects mute in standby
    assert err.value.error.code is p.ErrorCode.NOT_AVAILABLE
    assert client.state.muted is False
    assert client.state.available is True


async def test_not_confirmed_when_reply_disagrees(amp: MockAmplifier, client: CXAClient) -> None:
    original = amp._process

    def stuck_mute(line: bytes) -> list[str] | None:
        return ["#02,03,0"] if line.startswith(b"#1,04") else original(line)

    amp._process = stuck_mute  # type: ignore[method-assign]
    with pytest.raises(CXANotConfirmedError):
        await client.async_set_mute(True)
    assert client.state.muted is False  # we believe the amplifier, not the request


async def test_command_timeout_and_late_reply(amp: MockAmplifier, client: CXAClient) -> None:
    amp.behaviour.reply_delay = 0.5
    with pytest.raises(CXATimeoutError):
        await client.async_set_mute(True)
    # The late reply is still authoritative state.
    await wait_for(lambda: client.state.muted is True)
    assert client.state.available is True


async def test_commands_are_serialized(amp: MockAmplifier, client: CXAClient) -> None:
    amp.behaviour.reply_delay = 0.02
    await asyncio.gather(
        client.async_set_mute(True),
        client.async_set_source("01"),
        client.async_refresh(),
        client.async_set_mute(False),
    )
    assert client.state.muted is False
    assert client.state.source == "01"


async def test_command_when_unavailable_is_not_sent(amp: MockAmplifier) -> None:
    c = _client(amp)
    with pytest.raises(CXANotConnectedError):
        await c.async_set_power(True)
    assert amp.received == []


# --- unsolicited events and stream robustness --------------------------------------------


async def test_unsolicited_front_panel_changes(amp: MockAmplifier, client: CXAClient) -> None:
    seen: list[AmplifierState] = []
    remove = client.add_listener(seen.append)
    await amp.front_panel(source="04")
    await amp.front_panel(muted=True)
    await amp.front_panel(power=False)
    await wait_for(lambda: client.state.power is False)
    assert client.state.source == "04"
    assert client.state.muted is True
    assert [s.source for s in seen][:1] == ["04"]
    remove()
    await amp.front_panel(power=True)
    await wait_for(lambda: client.state.power is True)
    assert seen[-1].power is False  # removed listener no longer called


async def test_unsolicited_event_during_request(amp: MockAmplifier, client: CXAClient) -> None:
    """An unrelated push arriving mid-request must not satisfy the request."""
    original = amp._process

    def push_then_reply(line: bytes) -> list[str] | None:
        if line.startswith(b"#3,04"):
            return ["#02,03,1", "#04,01,05"]
        return original(line)

    amp._process = push_then_reply  # type: ignore[method-assign]
    await client.async_set_source("05")
    assert client.state.muted is True
    assert client.state.source == "05"


async def test_fragmented_replies_and_crlf(amp: MockAmplifier) -> None:
    amp.behaviour.fragment_size = 1
    amp.behaviour.line_ending = b"\r\n"
    c = _client(amp, request_timeout=1.0)
    await c.start()
    try:
        assert c.state.source == "20"
        await c.async_set_source("02")
        assert c.state.source == "02"
    finally:
        await c.stop()


async def test_coalesced_and_noisy_stream(amp: MockAmplifier, client: CXAClient) -> None:
    await amp.send_raw(b"junk\r\x00#02,03,1\r#04,01,05\r#99,01,1\r#04,01,77\r")
    await wait_for(lambda: client.state.source == "77")
    assert client.state.muted is True
    assert client.state.available is True
    await client.async_set_mute(False)  # stream still in sync afterwards


async def test_duplicate_notifications(amp: MockAmplifier, client: CXAClient) -> None:
    amp.behaviour.duplicate_notifications = True
    await client.async_set_source("01")
    await client.async_set_mute(True)
    await client.async_set_source("02")
    assert client.state.source == "02"
    assert client.state.muted is True


async def test_unsolicited_error_is_ignored(amp: MockAmplifier, client: CXAClient) -> None:
    await amp.send_raw(b"#00,04\r")
    await asyncio.sleep(0.05)
    assert client.state.available is True
    await client.async_set_mute(True)


async def test_listener_exception_does_not_break_client(
    amp: MockAmplifier, client: CXAClient
) -> None:
    def broken(_: AmplifierState) -> None:
        raise RuntimeError("boom")

    client.add_listener(broken)
    await client.async_set_mute(True)
    assert client.state.muted is True


# --- disconnects and reconnection -------------------------------------------------------


async def test_disconnect_marks_unavailable_then_resyncs(
    amp: MockAmplifier, client: CXAClient
) -> None:
    availability: list[bool] = []
    client.add_listener(lambda s: availability.append(s.available))
    await amp.drop_clients()
    await wait_for(lambda: client.state.available is False)
    amp.state.source = "05"  # changed while we were disconnected
    await wait_for(lambda: client.state.available is True)
    assert client.state.source == "05"
    assert False in availability
    assert client.reconnect_count == 1


async def test_in_flight_command_fails_on_disconnect(amp: MockAmplifier, client: CXAClient) -> None:
    amp.behaviour.unresponsive = True
    task = asyncio.create_task(client.async_set_mute(True))
    await wait_for(lambda: any(line.startswith(b"#1,04") for line in amp.received))
    await amp.drop_clients()
    with pytest.raises(CXAConnectionLostError):
        await task


async def test_no_write_replay_after_reconnect(amp: MockAmplifier, client: CXAClient) -> None:
    amp.behaviour.unresponsive = True
    task = asyncio.create_task(client.async_set_power(False))
    await wait_for(lambda: len(_writes(amp)) == 1)
    await amp.drop_clients()
    with pytest.raises(CXAConnectionLostError):
        await task
    amp.behaviour.unresponsive = False
    await wait_for(lambda: client.state.available is True)
    await asyncio.sleep(0.1)
    assert _writes(amp) == [b"#1,02,0"]


async def test_command_during_outage_fails_fast(amp: MockAmplifier, client: CXAClient) -> None:
    await amp.stop()
    await wait_for(lambda: client.state.available is False)
    with pytest.raises(CXANotConnectedError):
        await client.async_set_power(True)


async def test_reconnects_after_bridge_restart(amp: MockAmplifier, client: CXAClient) -> None:
    port = amp.port  # type: ignore[attr-defined]
    await amp.stop()
    await wait_for(lambda: client.state.available is False)
    await asyncio.sleep(0.3)  # a few failed attempts with backoff
    assert client.state.available is False
    assert client.last_error
    amp.state.muted = True
    await amp.start(HOST, port)
    await wait_for(lambda: client.state.available is True, timeout=3)
    assert client.state.muted is True


async def test_liveness_poll_detects_dead_link(amp: MockAmplifier) -> None:
    """Half-open TCP: socket stays up but nothing answers."""
    c = _client(amp, poll_interval=0.1, request_timeout=0.1)
    await c.start()
    try:
        amp.behaviour.unresponsive = True
        await wait_for(lambda: c.state.available is False, timeout=3)
        amp.behaviour.unresponsive = False
        await wait_for(lambda: c.state.available is True, timeout=3)
    finally:
        await c.stop()


async def test_liveness_poll_tolerates_single_miss(amp: MockAmplifier) -> None:
    c = _client(amp, poll_interval=0.1, request_timeout=0.1)
    await c.start()
    try:
        original = amp._process
        dropped: list[bytes] = []

        def drop_one(line: bytes) -> list[str] | None:
            if line == b"#1,01" and not dropped:
                dropped.append(line)
                return None
            return original(line)

        amp._process = drop_one  # type: ignore[method-assign]
        await wait_for(lambda: len(dropped) == 1)
        await asyncio.sleep(0.4)
        assert c.state.available is True
        assert c.reconnect_count == 0
    finally:
        await c.stop()


# --- teardown ---------------------------------------------------------------------------


async def test_stop_cleans_up(amp: MockAmplifier) -> None:
    c = _client(amp)
    await c.start()
    assert _our_tasks()
    await c.stop()
    assert _our_tasks() == []
    assert c.state.available is False
    await wait_for(lambda: amp.client_count == 0)
    await c.stop()  # idempotent


async def test_stop_during_reconnect(amp: MockAmplifier, client: CXAClient) -> None:
    await amp.stop()
    await wait_for(lambda: client.state.available is False)
    await client.stop()
    assert _our_tasks() == []


async def test_connection_close_is_idempotent(amp: MockAmplifier) -> None:
    conn = await CXAConnection.open(HOST, amp.port)  # type: ignore[attr-defined]
    await conn.close()
    await conn.close()
    with pytest.raises(CXANotConnectedError):
        await conn.request(p.GET_POWER, 0.1)


async def test_reader_crash_triggers_reconnect(
    amp: MockAmplifier, client: CXAClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected bug in frame handling must not leave a zombie 'available' client."""
    conn = client._conn
    assert conn is not None

    def explode(_: object) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(conn, "_dispatch", explode)
    await amp.front_panel(muted=True)
    await wait_for(lambda: client.state.available is False)
    await wait_for(lambda: client.state.available is True)
    assert client.state.muted is True
