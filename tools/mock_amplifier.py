#!/usr/bin/env python3
"""Simulated Cambridge CXA61/CXA81 behind a transparent TCP serial bridge.

Written from Cambridge document AP36646/2 only. It intentionally does NOT
import the integration's protocol module: an independent implementation
cross-checks the client instead of sharing its bugs.

Everything this mock does where the spec is silent (standby behaviour,
setter replies, timing, duplicate notifications) is a configurable
*assumption*. Passing tests against it proves nothing about real hardware;
see docs/hardware-validation.md.

Run standalone:
    python tools/mock_amplifier.py --port 8899
then type ``help`` for front-panel simulation commands.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Literal

_LOGGER = logging.getLogger("mock_amplifier")

SOURCE_CODES = {
    "CXA61": ["00", "01", "02", "03", "04", "05", "06", "10", "14", "16"],
    "CXA81": ["00", "01", "02", "03", "04", "05", "06", "14", "16", "20"],
}

GroupAcceptance = Literal["both", "unpadded", "padded"]
# How the unit treats non-power commands while in standby. Undocumented.
StandbyMode = Literal["queries_ok", "reject_all_but_power", "silent"]


@dataclass
class MockBehaviour:
    """Knobs for spec-silent or fault behaviour."""

    accept_group_format: GroupAcceptance = "both"
    standby_mode: StandbyMode = "queries_ok"
    reply_delay: float = 0.0
    power_on_delay: float = 0.0
    fragment_size: int | None = None  # split each reply into n-byte TCP writes
    line_ending: bytes = b"\r"  # b"\r\n" simulates a bridge adding LF
    duplicate_notifications: bool = False  # setter reply + separate change event
    unresponsive: bool = False  # TCP up but serial dead (bad cable, wrong baud)
    protocol_version: str = "1.0"
    firmware_version: str = "SYNTHETIC-0.0"  # deliberately not a real version


@dataclass
class MockState:
    """Simulated amplifier state."""

    power: bool = True
    muted: bool = False
    source: str = "20"


@dataclass
class MockAmplifier:
    """Asyncio TCP server that behaves like the bridge + amplifier."""

    model: str = "CXA81"
    state: MockState = field(default_factory=MockState)
    behaviour: MockBehaviour = field(default_factory=MockBehaviour)
    received: list[bytes] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    # -- lifecycle --

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        """Start listening; returns the bound port."""
        self._server = await asyncio.start_server(self._on_client, host, port)
        bound = self._server.sockets[0].getsockname()[1]
        _LOGGER.info("Mock %s listening on %s:%s", self.model, host, bound)
        return bound

    async def stop(self) -> None:
        """Stop listening and drop all clients."""
        if self._server is not None:
            self._server.close()
        await self.drop_clients()
        if self._server is not None:
            await self._server.wait_closed()
            self._server = None

    async def drop_clients(self) -> None:
        """Abruptly close every client connection (simulates a bridge reboot)."""
        for writer in list(self._writers):
            writer.close()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._writers.clear()

    @property
    def client_count(self) -> int:
        """Number of connected TCP clients."""
        return len(self._writers)

    # -- simulated physical interaction (remote control / front panel) --

    async def front_panel(
        self, *, power: bool | None = None, muted: bool | None = None, source: str | None = None
    ) -> None:
        """Change state as if by IR remote or front panel; push the documented reply."""
        if power is not None:
            self.state.power = power
            await self.broadcast(f"#02,01,{int(power)}")
        if muted is not None:
            self.state.muted = muted
            await self.broadcast(f"#02,03,{int(muted)}")
        if source is not None:
            self.state.source = source
            await self.broadcast(f"#04,01,{source}")

    async def send_raw(self, data: bytes) -> None:
        """Push arbitrary bytes to every client (noise, coalesced frames...)."""
        await self._write_all(data)

    async def broadcast(self, frame: str) -> None:
        """Send one frame, honouring fragmentation and line-ending settings."""
        await self._write_all(frame.encode("ascii") + self.behaviour.line_ending)

    # -- internals --

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        self._writers.add(writer)
        buffer = bytearray()
        try:
            while data := await reader.read(256):
                for byte in data:
                    if byte == 0x0D:
                        line = bytes(buffer).strip(b"\n")
                        buffer.clear()
                        if line:
                            self.received.append(line)
                            await self._handle(line)
                    else:
                        buffer.append(byte)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._writers.discard(writer)
            self._tasks.discard(task)
            writer.close()

    async def _write_all(self, payload: bytes) -> None:
        size = self.behaviour.fragment_size
        chunks = (
            [payload] if not size else [payload[i : i + size] for i in range(0, len(payload), size)]
        )
        for writer in list(self._writers):
            try:
                for chunk in chunks:
                    writer.write(chunk)
                    await writer.drain()
                    if size:
                        await asyncio.sleep(0.002)
            except ConnectionError:
                self._writers.discard(writer)

    async def _handle(self, line: bytes) -> None:
        if self.behaviour.unresponsive:
            return
        waking = not self.state.power
        reply = self._process(line)
        if reply is None:
            return
        if self.behaviour.reply_delay:
            await asyncio.sleep(self.behaviour.reply_delay)
        if waking and self.state.power and self.behaviour.power_on_delay:
            await asyncio.sleep(self.behaviour.power_on_delay)
        for frame in reply:
            await self.broadcast(frame)

    def _process(self, line: bytes) -> list[str] | None:  # noqa: PLR0911, PLR0912
        """Return reply frames for one received line, or None for silence."""
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError:
            return ["#00,01"]
        if not text.startswith("#"):
            return ["#00,01"]
        parts = text[1:].split(",")
        group_text = parts[0]
        number_text = parts[1] if len(parts) > 1 else ""
        data = parts[2] if len(parts) > 2 else None
        if not group_text.isdigit() or not self._group_format_ok(group_text):
            return ["#00,01"]
        group = int(group_text)
        if group not in (1, 3, 13):
            return ["#00,01"]
        if not number_text.isdigit():
            return ["#00,02"]
        number = int(number_text)

        standby = not self.state.power
        is_power_cmd = group == 1 and number in (1, 2)
        if standby and not is_power_cmd:
            if self.behaviour.standby_mode == "silent":
                return None
            if self.behaviour.standby_mode == "reject_all_but_power":
                return ["#00,04"]

        if group == 1:
            if number == 1:
                return [f"#02,01,{int(self.state.power)}"]
            if number == 2:
                if data not in ("0", "1"):
                    return ["#00,03"]
                self.state.power = data == "1"
                return self._setter_reply(f"#02,01,{data}")
            if number == 3:
                return [f"#02,03,{int(self.state.muted)}"]
            if number == 4:
                if data not in ("0", "1"):
                    return ["#00,03"]
                if standby:
                    return ["#00,04"]
                self.state.muted = data == "1"
                return self._setter_reply(f"#02,03,{data}")
            return ["#00,02"]

        if group == 3:
            codes = SOURCE_CODES[self.model]
            if number == 1:
                return [f"#04,01,{self.state.source}"]
            if number in (2, 3, 4):
                if standby:
                    return ["#00,04"]
                if number == 4:
                    if data not in codes:
                        return ["#00,03"]
                    self.state.source = data
                else:
                    index = codes.index(self.state.source) if self.state.source in codes else 0
                    step = 1 if number == 2 else -1
                    self.state.source = codes[(index + step) % len(codes)]
                return self._setter_reply(f"#04,01,{self.state.source}")
            return ["#00,02"]

        # group 13
        if number == 1:
            return [f"#14,01,{self.behaviour.protocol_version}"]
        if number == 2:
            return [f"#14,02,{self.behaviour.firmware_version}"]
        return ["#00,02"]

    def _setter_reply(self, frame: str) -> list[str]:
        if self.behaviour.duplicate_notifications:
            return [frame, frame]
        return [frame]

    def _group_format_ok(self, group_text: str) -> bool:
        mode = self.behaviour.accept_group_format
        padded = len(group_text) == 2 and group_text.startswith("0")
        unpadded = len(group_text) == 1
        if mode == "padded":
            return not unpadded
        if mode == "unpadded":
            return not padded
        return True


# --- CLI ------------------------------------------------------------------------

HELP = """Commands:
  power on|off     mute on|off     source <code>
  raw <text>       send text + CR as-is      drop   disconnect all clients
  state            show state                quit"""


async def _console(amp: MockAmplifier) -> None:
    loop = asyncio.get_running_loop()
    print(HELP)
    while True:
        line = (await loop.run_in_executor(None, input, "mock> ")).strip()
        words = line.split()
        if not words:
            continue
        cmd, args = words[0], words[1:]
        if cmd == "quit":
            return
        if cmd == "state":
            print(amp.state, f"clients={amp.client_count}")
        elif cmd == "drop":
            await amp.drop_clients()
        elif cmd == "raw" and args:
            await amp.send_raw(" ".join(args).encode() + b"\r")
        elif cmd in ("power", "mute") and args and args[0] in ("on", "off"):
            value = args[0] == "on"
            await amp.front_panel(**{"power" if cmd == "power" else "muted": value})
        elif cmd == "source" and args and args[0] in SOURCE_CODES[amp.model]:
            await amp.front_panel(source=args[0])
        else:
            print(HELP)


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--model", choices=sorted(SOURCE_CODES), default="CXA81")
    parser.add_argument("--standby", action="store_true", help="start in standby")
    parser.add_argument(
        "--standby-mode",
        choices=["queries_ok", "reject_all_but_power", "silent"],
        default="queries_ok",
    )
    parser.add_argument(
        "--accept-group-format", choices=["both", "unpadded", "padded"], default="both"
    )
    parser.add_argument("--reply-delay", type=float, default=0.0)
    parser.add_argument(
        "--fragment", type=int, default=None, help="split replies into N-byte writes"
    )
    parser.add_argument("--crlf", action="store_true", help="terminate replies with CR LF")
    parser.add_argument(
        "--no-console", action="store_true", help="run without the interactive prompt"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    amp = MockAmplifier(
        model=args.model,
        state=MockState(power=not args.standby, source="20" if args.model == "CXA81" else "00"),
        behaviour=MockBehaviour(
            accept_group_format=args.accept_group_format,
            standby_mode=args.standby_mode,
            reply_delay=args.reply_delay,
            fragment_size=args.fragment,
            line_ending=b"\r\n" if args.crlf else b"\r",
        ),
    )
    await amp.start(args.host, args.port)
    try:
        if args.no_console:
            await asyncio.Event().wait()
        else:
            await _console(amp)
    finally:
        await amp.stop()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, EOFError):
        asyncio.run(_main())
