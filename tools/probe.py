#!/usr/bin/env python3
"""Hardware probe: show exactly what a CXA amplifier sends back over the bridge.

Read-only by default. It sends only the documented query commands, records
raw bytes and timing, and can listen for unsolicited pushes (press buttons on
the remote while it runs). Writes require --allow-writes.

Examples:
    python tools/probe.py 192.168.1.50 8899
    python tools/probe.py 192.168.1.50 8899 --group-format both --listen 60
    python tools/probe.py 192.168.1.50 8899 --jsonl evidence.jsonl
    python tools/probe.py 192.168.1.50 8899 --allow-writes --set-mute on

Needs only the Python standard library (Python 3.11+); Home Assistant is not required.

"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
import types
from pathlib import Path
from typing import Any

INTEGRATION_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "cambridge_cxa_home"
)


def _load_protocol() -> types.ModuleType:
    """Import protocol.py without executing the integration's __init__ (which needs HA)."""
    spec = importlib.util.spec_from_file_location("cxa_protocol", INTEGRATION_DIR / "protocol.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


p = _load_protocol()


class Probe:
    """One raw TCP session that logs everything."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, jsonl: Any):
        self.reader = reader
        self.writer = writer
        self.decoder = p.FrameDecoder()
        self.jsonl = jsonl
        self.t0 = time.monotonic()

    def log(self, kind: str, **fields: Any) -> None:
        """Print a timestamped line and append it to the JSONL transcript."""
        elapsed = time.monotonic() - self.t0
        record = {"t": round(elapsed, 4), "kind": kind, **fields}
        if self.jsonl:
            self.jsonl.write(json.dumps(record) + "\n")
            self.jsonl.flush()
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        print(f"[{elapsed:8.3f}s] {kind:<6} {detail}")

    async def send(self, payload: bytes) -> None:
        """Write raw bytes to the bridge."""
        self.log("TX", raw=repr(payload), hex=payload.hex(" "))
        self.writer.write(payload)
        await self.writer.drain()

    async def collect(self, first_timeout: float, quiet: float) -> list[Any]:
        """Read until no bytes arrive for `quiet` s, waiting `first_timeout` for the first."""
        items: list[Any] = []
        timeout = first_timeout
        start = time.monotonic()
        while True:
            try:
                async with asyncio.timeout(timeout):
                    data = await self.reader.read(1024)
            except TimeoutError:
                break
            if not data:
                self.log("EOF")
                break
            latency_ms = round((time.monotonic() - start) * 1000)
            self.log("RX", raw=repr(data), hex=data.hex(" "), after_ms=latency_ms)
            for item in self.decoder.feed(data):
                items.append(item)
                self._log_item(item)
            timeout = quiet
        return items

    def _log_item(self, item: Any) -> None:
        if isinstance(item, p.MalformedFrame):
            self.log("BAD", raw=repr(item.raw), reason=item.reason)
        else:
            self.log("FRAME", raw=repr(item.raw), event=repr(p.interpret(item)))


async def run(args: argparse.Namespace) -> int:
    """Run the probe. Exit codes: 0 answered, 1 TCP ok but silent, 2 TCP failed."""
    # A CLI tool, not the HA event loop: a blocking open here is fine.
    jsonl = open(args.jsonl, "a", encoding="utf-8") if args.jsonl else None  # noqa: SIM115, ASYNC230
    try:
        print(f"Connecting to {args.host}:{args.port} ...")
        try:
            async with asyncio.timeout(args.timeout):
                reader, writer = await asyncio.open_connection(args.host, args.port)
        except (OSError, TimeoutError) as err:
            print(f"TCP connection failed: {err!r}")
            print("-> check bridge IP/port, Wi-Fi, and that the bridge is in TCP server mode.")
            return 2
        probe = Probe(reader, writer, jsonl)
        probe.log("OPEN", host=args.host, port=args.port)

        # Anything the bridge sends on connect (e.g. a registration packet) shows up here.
        await probe.collect(first_timeout=0.5, quiet=0.2)

        formats = (
            [p.GroupFormat.UNPADDED, p.GroupFormat.PADDED]
            if args.group_format == "both"
            else [p.GroupFormat(args.group_format)]
        )
        answered = False
        for fmt in formats:
            print(f"\n== Read-only queries, group format: {fmt.value} ==")
            for command in p.READ_ONLY_COMMANDS:
                await probe.send(command.encode(fmt))
                items = await probe.collect(first_timeout=args.timeout, quiet=args.quiet)
                if not items:
                    probe.log("NONE", note=f"no reply within {args.timeout}s")
                answered |= any(isinstance(i, p.Frame) for i in items)

        if args.allow_writes:
            await _writes(probe, args)

        if args.listen:
            print(f"\n== Listening {args.listen}s for unsolicited messages (use the remote now) ==")
            await probe.collect(first_timeout=args.listen, quiet=args.listen)

        writer.close()
        probe.log("CLOSE")
        if not answered:
            print("\nNo frames received. TCP works but the amplifier did not answer:")
            print("-> check serial settings (9600 8N1), cable (straight vs crossover), amp power.")
            return 1
        return 0
    finally:
        if jsonl:
            jsonl.close()


async def _writes(probe: Probe, args: argparse.Namespace) -> None:
    commands = []
    if args.set_power:
        commands.append(p.set_power(args.set_power == "on"))
    if args.set_mute:
        commands.append(p.set_mute(args.set_mute == "on"))
    if args.set_source:
        commands.append(p.set_source(args.set_source))
    fmt = p.GroupFormat(args.write_group_format)
    for command in commands:
        print(f"\n== WRITE {command.encode(fmt)!r} ==")
        await probe.send(command.encode(fmt))
        await probe.collect(first_timeout=args.power_timeout, quiet=args.quiet)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument(
        "--group-format", choices=["unpadded", "padded", "both"], default="unpadded"
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="wait for first reply byte")
    parser.add_argument(
        "--quiet", type=float, default=0.5, help="silence that ends a reply (catches extra frames)"
    )
    parser.add_argument("--listen", type=float, default=0, help="seconds to listen afterwards")
    parser.add_argument("--jsonl", help="append a machine-readable transcript to this file")
    writes = parser.add_argument_group("writes (change amplifier state; need --allow-writes)")
    writes.add_argument("--allow-writes", action="store_true")
    writes.add_argument("--set-power", choices=["on", "standby"])
    writes.add_argument("--set-mute", choices=["on", "off"])
    writes.add_argument("--set-source", metavar="CODE", help="two-digit code, e.g. 20")
    writes.add_argument("--write-group-format", choices=["unpadded", "padded"], default="unpadded")
    writes.add_argument("--power-timeout", type=float, default=10.0)
    args = parser.parse_args()

    wants_write = args.set_power or args.set_mute or args.set_source
    if wants_write and not args.allow_writes:
        parser.error("--set-* options change the amplifier; add --allow-writes to confirm")
    documented = set(p.SOURCES[p.Model.CXA81]) | set(p.SOURCES[p.Model.CXA61])
    if args.set_source and args.set_source not in documented:
        parser.error(f"source {args.set_source} is not documented for CXA61/CXA81")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
