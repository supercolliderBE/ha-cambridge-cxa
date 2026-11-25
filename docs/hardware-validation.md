# Hardware validation

Real-device claims require an entry here. Simulator results are listed separately and **prove nothing about the hardware**.

## Environment (fill in)
| Item | Value |
|---|---|
| Amplifier model / Mk II? | CXA81, original or Mk II: _unconfirmed_ |
| Firmware (14,02 reply) | _unknown_ |
| Protocol version (14,01 reply) | _unknown_ |
| Bridge model / firmware | USR-W610 / _unknown_ |
| Cable / adapter used | _unverified_ |
| HA version / install type | 2026.11.2 (from mDNS, 2026-11-25) / Container on Synology |

## Checklist (all pending)
| # | Question | Evidence needed | Result |
|---|---|---|---|
| H1 | Cable and pinout work (TX↔RX, GND) | probe exit 0 | pending |
| H2 | Which request group format is accepted (`#1,01` vs `#01,01`)? | probe `--group-format both` | pending |
| H3 | Exact reply formatting (padding, CR vs CRLF from the bridge) | probe hex dump | pending |
| H4 | Does the bridge inject bytes on connect? | probe OPEN window | pending |
| H5 | Answers to power, mute and source queries **in standby** | probe with amp in standby | pending |
| H6 | Setter replies: is the 02,01/02,03/04,01 frame sent? Once or twice? | `--allow-writes` runs | pending |
| H7 | Wake-up time from standby until the power reply | probe timing | pending |
| H8 | Unsolicited pushes from the remote and front panel; latency (target < 2 s in HA) | probe `--listen` | pending |
| H9 | A1 Balanced reported as `20` and distinct from A1 `00` | probe | pending |
| H10 | Source codes on a Mk II, if applicable | probe | pending |
| H11 | Wi-Fi interruption → unavailable → automatic recovery | HA on Synology: entity state history | pending |
| H12 | Bridge power cycle and HA restart recovery | HA on Synology | pending |
| H13 | Behaviour with a second TCP client connected | probe in two terminals | pending |
| H14 | Setup from the HA UI on the real install: read-only test passes, no state change on the amplifier | HA on Synology + probe transcript | pending |
| H15 | Power, mute and source commands from HA are confirmed; front-panel changes appear in HA (latency) | HA on Synology | pending |
| H16 | The HA container can reach the bridge (Docker networking on Synology) | HA setup succeeds | pending |

## Simulator and validator results (not hardware evidence)
Latest: 2026-11-25, `main` after PR #3. Command: `uv run pytest -q`. Environment: Python 3.14.10, HA 2026.10.4 test harness, macOS and GitHub Actions (ubuntu). Result: **165 passed**, stable across 6 consecutive runs.

| Suite | Tests | Covers |
|---|---|---|
| `test_protocol.py` | 83 | Byte-exact documented examples, malformed input, stream framing |
| `test_client.py` | 46 | Client against the mock over loopback TCP |
| `test_tools.py` | 6 | Probe is read-only by default; mock error replies |
| `test_config_flow.py`, `test_init.py`, `test_media_player.py`, `test_diagnostics.py` | 30 | The integration inside HA's test harness, against the mock |

Official validators (GitHub Actions): **hassfest passes**. **HACS action: 9 of 10 checks pass**; the only failure is the missing `brand/icon.png` (Milestone 5).

Not yet done: a run in a real, running HA instance with its UI (planned before the hardware beta).

The mock simulates both group-format policies, three standby behaviours, delayed and slow-wake replies, 1-byte fragmentation, CRLF, coalesced and noisy frames, duplicate setter notifications, a silent amplifier behind a live TCP socket, abrupt disconnects, a bridge restart and a half-open link.
