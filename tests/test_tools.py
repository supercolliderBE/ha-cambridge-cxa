"""Tests for the developer tools themselves (probe CLI, mock amplifier)."""

from __future__ import annotations

import argparse
import socket

import pytest

from tools import probe
from tools.mock_amplifier import MockAmplifier, MockState

from .conftest import HOST

pytestmark = pytest.mark.usefixtures("socket_enabled")


def _args(port: int, **overrides: object) -> argparse.Namespace:
    base = {
        "host": HOST,
        "port": port,
        "group_format": "unpadded",
        "timeout": 0.3,
        "quiet": 0.05,
        "listen": 0,
        "jsonl": None,
        "allow_writes": False,
        "set_power": None,
        "set_mute": None,
        "set_source": None,
        "write_group_format": "unpadded",
        "power_timeout": 0.3,
    }
    return argparse.Namespace(**{**base, **overrides})


async def test_probe_is_read_only_by_default(amp: MockAmplifier, tmp_path) -> None:
    amp.state = MockState(power=False, muted=True, source="03")
    log = tmp_path / "t.jsonl"
    assert await probe.run(_args(amp.port, group_format="both", jsonl=str(log))) == 0  # type: ignore[attr-defined]
    allowed = {b"#1,01", b"#1,03", b"#3,01", b"#13,01", b"#13,02", b"#01,01", b"#01,03", b"#03,01"}
    assert set(amp.received) <= allowed
    assert amp.state == MockState(power=False, muted=True, source="03")
    assert '"kind": "FRAME"' in log.read_text()


async def test_probe_reports_silent_amplifier(amp: MockAmplifier) -> None:
    amp.behaviour.unresponsive = True
    assert await probe.run(_args(amp.port)) == 1  # type: ignore[attr-defined]


async def test_probe_reports_unreachable_bridge() -> None:
    with socket.socket() as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    assert await probe.run(_args(port)) == 2


async def test_probe_writes_only_with_opt_in(amp: MockAmplifier) -> None:
    args = _args(amp.port, allow_writes=True, set_mute="on", set_source="05")  # type: ignore[attr-defined]
    assert await probe.run(args) == 0
    assert amp.state.muted is True
    assert amp.state.source == "05"


def test_probe_cli_refuses_writes_without_opt_in(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["probe.py", HOST, "1", "--set-power", "on"])
    with pytest.raises(SystemExit):
        probe.main()
    assert "--allow-writes" in capsys.readouterr().err


async def test_mock_reports_documented_errors(amp: MockAmplifier) -> None:
    proc = amp._process
    assert proc(b"#7,01") == ["#00,01"]  # unknown group
    assert proc(b"#1,09") == ["#00,02"]  # unknown number
    assert proc(b"#1,02,5") == ["#00,03"]  # bad data
    assert proc(b"#3,04,10") == ["#00,03"]  # MP3 is not a CXA81 source
