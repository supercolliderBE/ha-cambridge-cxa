# Cambridge Audio CXA (Local Serial Bridge) for Home Assistant

> **Status: pre-alpha, not usable in Home Assistant yet.** The protocol library, client, simulator and probe exist and are tested against a simulator only. The Home Assistant entity and config flow are the next milestone. **No real-hardware compatibility is claimed.**

This custom integration controls a Cambridge Audio **CXA81** (CXA61 support is planned) over its RS232 port. The connection goes through a transparent Wi-Fi/Ethernet-to-serial bridge such as the PUSR USR-W610. Everything is local: no cloud, no phone app and no extra container.

## Project status
| Milestone | Status |
|---|---|
| 1. Protocol encoder/parser | Done (tested against the simulator) |
| 2. Async client, simulator, hardware probe | Done (tested against the simulator) |
| 3. Home Assistant setup screen and entity | In progress next |
| 4. Validation on a real CXA81 + USR-W610 | Waiting for hardware ([checklist](docs/hardware-validation.md)) |
| 5. HACS release (beta, then stable) | After real-hardware validation |

## Compatibility
| Component | Status |
|---|---|
| Home Assistant | Minimum **2026.11.0**, the release line the maintainer runs (2026.11.2). Automated tests still run against 2026.10.4, because no 2026.11 test harness has been released yet. Not yet tested in a running HA. |
| Install types | Any that allow custom integrations (Container, OS, Supervised, Core). No extra add-on or container needed. |
| Amplifiers | **CXA81: planned, not yet verified on hardware.** CXA61: protocol supported in code, untested. Mk II: unknown. |
| Bridges | PUSR USR-W610 (planned test device). Any transparent TCP-server-to-RS232 bridge at 9600 8N1 should work in principle; none verified yet. |

## Planned features (MVP)
- Power (on/standby), mute, and source selection, including **A1 Balanced** on the CXA81.
- Live updates when the remote or front panel changes state. The amplifier pushes these.
- Unavailable is shown distinctly from standby, with automatic reconnection.

**Not supported, by design:** volume. Cambridge's serial protocol defines no volume commands, so this integration shows no volume slider and no fake volume state. Playback controls are not supported either.

## Repository layout
| Path | Purpose |
|---|---|
| `custom_components/cambridge_cxa_home/protocol.py` | Framing, encoding and parsing (no HA dependency) |
| `custom_components/cambridge_cxa_home/client.py` | Async TCP client with reconnect and state (no HA dependency) |
| `tools/mock_amplifier.py` | Simulated amplifier for development and tests |
| `tools/probe.py` | Read-only hardware probe (Python 3.11+, stdlib only) |
| `docs/` | [Plan](docs/PLAN.md), [architecture](docs/architecture.md), [protocol evidence](docs/protocol-evidence.md), [hardware setup](docs/hardware-setup.md), [validation](docs/hardware-validation.md), [progress log](docs/progress-log.md) |

## Development
```sh
uv sync --group dev          # Python 3.14.2+, HA test harness, ruff
uv run pytest -q
uv run ruff check . && uv run ruff format --check .

# Try the client and probe without hardware:
uv run python tools/mock_amplifier.py --port 8899          # terminal 1
uv run python tools/probe.py 127.0.0.1 8899 --listen 20    # terminal 2
```

## Provenance and licence
This is an independent implementation, written from Cambridge Audio's published *CXA61 and CXA81 Serial Control Protocol* (AP36646/2) and the official Home Assistant documentation. It does not copy or adapt the existing community integration. That integration has no stated licence.

The code is MIT-licensed (see [LICENSE](LICENSE)). The licence covers only this project's original work. Cambridge's protocol PDF is not redistributed here; it is [linked](docs/protocol-evidence.md) instead.

Cambridge Audio, CXA61 and CXA81 are trademarks of their owner. This project is not affiliated with or endorsed by Cambridge Audio.
