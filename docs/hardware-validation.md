# Hardware validation

Real-device claims require an entry here. Simulator results are listed separately and **prove nothing about the hardware**.

## Environment
| Item | Value |
|---|---|
| Amplifier model / Mk II? | CXA81, original or Mk II: _unconfirmed_ (rear label not yet read) |
| Firmware (14,02 reply) | `04000G01A61E` (observed 2026-11-28) |
| Protocol version (14,01 reply) | `1.1` (observed 2026-11-28; the PDF's example is `1.0`) |
| Bridge model / firmware | USR-W610 / _not recorded_ |
| Bridge settings | STA mode, transparent, TCP server, RS232 9600 8N1, no flow control, registration/heartbeat packets off, TCP password off |
| Cable / adapter used | Worked as connected; exact type _not recorded_ |
| HA version / install type | 2026.11.2 (from mDNS, 2026-11-25) / Container on Synology |

## Checklist
| # | Question | Evidence needed | Result |
|---|---|---|---|
| H1 | Cable and pinout work (TX↔RX, GND) | probe exit 0 | **Pass** (2026-11-28, run B). Both directions work. |
| H2 | Which request group format is accepted (`#1,01` vs `#01,01`)? | probe `--group-format both` | **Both** are answered identically, on and in standby (runs B, C). |
| H3 | Exact reply formatting (padding, CR vs CRLF from the bridge) | probe hex dump | Replies and errors use **two-digit groups**, end in **CR only** (`0d`, no LF). Source codes are two digits. Several frames can arrive in one TCP read (run C). |
| H4 | Does the bridge inject bytes on connect? | probe OPEN window | **None seen** in the 0.5 s before the first request, or anywhere else, with registration and heartbeat packets off. |
| H5 | Answers to power, mute and source queries **in standby** | probe with amp in standby | Power: `#02,01,0`. Mute and source: error **`#00,04`** (can't be actioned now). Protocol and firmware version queries are still answered (run C). |
| H6 | Setter replies: is the 02,01/02,03/04,01 frame sent? Once or twice? | `--allow-writes` runs | **Yes, once.** Every setter is answered by exactly one matching state reply with the new value (runs D, E). |
| H7 | Wake-up time from standby until the power reply | probe timing | Power-on command: reply after **3.0 s**, sent together with source and mute (`#02,01,1` `#04,01,00` `#02,03,0`). Standby command: reply after **1.2 s**. A read-only run started a few seconds after the wake reply got normal answers for power, mute and source (run E). |
| H8 | Unsolicited pushes from the remote and front panel; latency (target < 2 s in HA) | probe `--listen` | **Pushes work** for mute, source and power from the IR remote (runs B, C). A remote power-on pushes power, source and mute together. Front panel and end-to-end latency in HA: not yet measured. |
| H9 | A1 Balanced reported as `20` and distinct from A1 `00` | probe | pending (A1 Balanced not selected yet) |
| H10 | Source codes on a Mk II, if applicable | probe | pending (model not confirmed). Codes `00` A1, `01` A2, `04` D1, `14` Bluetooth matched the owner's button presses in order (run B). |
| H11 | Wi-Fi interruption → unavailable → automatic recovery | HA on Synology: entity state history | pending |
| H12 | Bridge power cycle and HA restart recovery | HA on Synology | pending |
| H13 | Behaviour with a second TCP client connected | probe in two terminals | pending |
| H14 | Setup from the HA UI on the real install: read-only test passes, no state change on the amplifier | HA on Synology + probe transcript | pending |
| H15 | Power, mute and source commands from HA are confirmed; front-panel changes appear in HA (latency) | HA on Synology | pending |
| H16 | The HA container can reach the bridge (Docker networking on Synology) | HA setup succeeds | pending |

## Probe sessions (2026-11-28)
All runs used `tools/probe.py` from a Mac on the same LAN. The bridge address is left out on purpose. JSONL transcripts are kept locally and are git-ignored.

| Run | Conditions | Result |
|---|---|---|
| A | Amp on, `--group-format both --listen 30` | Exit 1. Every query unanswered. Remote presses produced bursts of only `00` and `e0` bytes, about 25 bytes per message. **Cause: the bridge's serial settings were wrong** (the owner found and corrected them). This byte pattern is a useful sign of a baud-rate mismatch. |
| B | Amp on, same command, after fixing the bridge | Exit 0. Power `1`, mute `0`, source `04` (D1), protocol `1.1`, firmware `04000G01A61E`. Reply time about 60–120 ms. During the listen window: mute pushes `#02,03,1`/`#02,03,0` and source pushes `01`, `04`, `14`, `00`, matching the owner's presses (A2, D1, Bluetooth, A1). |
| C | Amp in standby, same command; owner pressed power on the remote after about 15 s | Exit 0. Power `0`; mute and source `#00,04`; version queries answered. On the remote power-on, one TCP read carried `#02,01,1\r#04,01,00\r#02,03,0\r`. |
| D | Amp on, `--allow-writes`: mute on, mute off, source D1, source A1 | All exit 0. `#1,04,1` → `#02,03,1`; `#1,04,0` → `#02,03,0`; `#3,04,04` → `#04,01,04`; `#3,04,00` → `#04,01,00`. Reply time 76–162 ms. |
| E | `--allow-writes`: standby, then on; then a read-only run | All exit 0. `#1,02,0` → `#02,01,0` after 1180 ms. `#1,02,1` → `#02,01,1`, `#04,01,00`, `#02,03,0` after 3014 ms. The read-only run right afterwards was answered normally. |

Writes used unpadded groups (the probe default). Padded writes were not tried.

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

**Known gap between the mock and the real amplifier:** none of the mock's three standby behaviours matches what run C showed. The real CXA81 rejects mute and source with `00,04` but still answers version queries; the mock's `reject_all_but_power` also rejects the version queries. The client tolerates both, but the mock should gain this behaviour.
