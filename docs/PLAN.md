# Implementation plan

The status of each milestone is kept current here. For details of what changed and when, see [progress-log.md](progress-log.md).

## Principles
- **Independent implementation.** Sources are Cambridge's AP36646/2 and the official HA/HACS docs only. The unlicensed community integration (`lievencoghe/cambridge_cxa`), its forks and its PRs are not consulted, copied or adapted. This is *not* a formal, legally audited clean-room process.
- **Document, infer or measure; never invent.** Every protocol behaviour is classified in [protocol-evidence.md](protocol-evidence.md).
- **Simulation is not validation.** Results from the mock and from real hardware are recorded separately ([hardware-validation.md](hardware-validation.md)).
- **Safe by default.** Setup and probing are read-only. Writes are never queued, retried or replayed. There is no fake volume.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Scaffold, protocol encoder/parser, typed events, unit tests | **Done** (2026-11-25) |
| 2 | Async TCP client, reconnect/resync, stateful mock, read-only probe CLI, tests | **Done** (2026-11-25) |
| 3 | HA MVP: config flow (+ reconfigure), setup/unload, `media_player`, diagnostics, HA tests | Next |
| 4 | Hardware validation on CXA81 + USR-W610 (see checklist) | Blocked on hardware |
| 5 | Release: brand icon, HACS/hassfest green, docs, beta tag, then stable | After 4 |

### Milestone 3 design (planned)
- `config_flow.py`: user step (model, host, port) → `fetch_device_info` (read-only). Errors: `cannot_connect` (TCP), `no_response` (TCP OK but amplifier silent), `rejected` (e.g. group format). Unique ID: a generated UUID stored in the entry, because the protocol exposes no serial number and firmware/IP aren't identities. Duplicate prevention by host+port match. A reconfigure step changes host/port and keeps the identity.
- `__init__.py`: `CXAClient` in `entry.runtime_data`. `ConfigEntryNotReady` if the first connect fails. The client is stopped on unload.
- `media_player.py`: device class `receiver`. Features `TURN_ON | TURN_OFF | VOLUME_MUTE | SELECT_SOURCE` only. State `on`/`off` (standby → `off`, because `STANDBY` is deprecated); `available` follows the connection. Push updates via the client listener, with `should_poll = False`. Command errors surface as `HomeAssistantError`.
- `diagnostics.py`: protocol/firmware version, reconnect count, last error, malformed/unknown frame counters. Host and port redacted.
- A settable group format (options flow) only if hardware shows it's needed.

### Deferred (not in MVP)
Source aliases and an options flow, next/previous source services, CXA61 and Mk II support (after validation), local USB serial transport, and IR/Control Bus volume. None of these will be added without evidence.

## Owner decisions (2026-11-25)
1. **Copyright:** "supercolliderBE and ha-cambridge-cxa contributors". The GitHub profile has no public display name.
2. **GitHub:** `supercolliderBE/ha-cambridge-cxa`; codeowner `@supercolliderBE`. Commits use the GitHub noreply address.
3. **Domain:** `cambridge_cxa_home` (renamed from the handover's `cambridge_cxa_local`). It is fixed from now on, because changing it later breaks entity and unique IDs.

## Resolved
- **Minimum HA version: 2026.11.0** (`hacs.json`). The owner chose to claim only the release line they run: HA **2026.11.2** (Container on Synology), read from its mDNS `_home-assistant._tcp` announcement on 2026-11-25. Known gap: the automated tests run against the 2026.10.4 harness, which is older than the minimum, because `pytest-homeassistant-custom-component` has no 2026.11 release yet (latest 0.13.375). Upgrade the harness as soon as one is published.
