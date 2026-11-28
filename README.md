# Cambridge Audio CXA (Local Serial Bridge) for Home Assistant

> **Status: pre-alpha.** The protocol layer has been checked against a real CXA81 through a USR-W610 with the probe tool (2026-11-28): status, push updates, and power, mute and source control all work. **The integration itself has not yet run in Home Assistant against real hardware.**

This custom integration controls a Cambridge Audio **CXA81** (CXA61 is selectable but untested) over its RS232 port. The connection goes through a transparent Wi-Fi/Ethernet-to-serial bridge such as the PUSR USR-W610. Everything is local: no cloud, no phone app and no extra container.

## Project status
| Milestone | Status |
|---|---|
| 1. Protocol encoder/parser | Done (tested against the simulator) |
| 2. Async client, simulator, hardware probe | Done (tested against the simulator) |
| 3. Home Assistant setup screen and entity | Done (tested against the simulator) |
| 4. Validation on a real CXA81 + USR-W610 | In progress: probe tests pass; Home Assistant tests pending ([checklist](docs/hardware-validation.md)) |
| 5. HACS release (beta, then stable) | After real-hardware validation |

## Compatibility
| Component | Status |
|---|---|
| Home Assistant | Minimum **2026.11.0**, the release line the maintainer runs (2026.11.2). Automated tests still run against 2026.10.4, because no 2026.11 test harness has been released yet. Not yet tested in a running HA. |
| Install types | Any that allow custom integrations (Container, OS, Supervised, Core). No extra add-on or container needed. |
| Amplifiers | **CXA81: protocol verified on one unit** (firmware `04000G01A61E`, protocol 1.1) with the probe; not yet in Home Assistant. CXA61: selectable in setup, untested. Mk II: unknown. |
| Bridges | **PUSR USR-W610: works** (TCP server, transparent, 9600 8N1; see [hardware setup](docs/hardware-setup.md)). Any transparent TCP-server-to-RS232 bridge at 9600 8N1 should work in principle. |

**Not supported, by design:** volume. Cambridge's serial protocol defines no volume commands, so this integration shows no volume slider and no fake volume state. Playback controls are not supported either.

## Installation (manual, for testing)
HACS installation will follow the first hardware-tested beta.

1. Back up your Home Assistant configuration folder.
2. Copy `custom_components/cambridge_cxa_home/` from this repository into `<config>/custom_components/`.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, search for **Cambridge Audio CXA**, and enter the bridge's IP address and TCP port. The connection test only reads state; it never switches the amplifier on or changes anything.

To uninstall: delete the integration entry, remove the folder, and restart.

### What you get
One media player entity per amplifier:
- **State:** on, off (standby), or unavailable when the bridge or amplifier can't be reached.
- **Controls:** power on/off, mute, and source (A1–A4, D1–D3, Bluetooth, USB Audio, A1 Balanced).
- **Updates** are pushed by the amplifier when you use the remote or front panel.
- If the bridge's IP changes, use **Reconfigure** on the integration; the device and entity stay the same.
- **Diagnostics** can be downloaded from the device page; the bridge address is redacted.

## Repository layout
| Path | Purpose |
|---|---|
| `custom_components/cambridge_cxa_home/protocol.py` | Framing, encoding and parsing (no HA dependency) |
| `custom_components/cambridge_cxa_home/client.py` | Async TCP client with reconnect and state (no HA dependency) |
| `custom_components/cambridge_cxa_home/__init__.py` | Config entry setup, retry and unload |
| `custom_components/cambridge_cxa_home/config_flow.py` | Setup and reconfigure screens (read-only connection test) |
| `custom_components/cambridge_cxa_home/media_player.py` | The amplifier entity |
| `custom_components/cambridge_cxa_home/diagnostics.py` | Diagnostics download (address redacted) |
| `tests/` | 165 tests: protocol, client, tools, and HA-level tests against the simulator |
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
