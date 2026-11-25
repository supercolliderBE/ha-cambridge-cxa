# Progress log

## 2026-11-25: minimum HA raised to 2026.11.0
- At the owner's request, `hacs.json` now claims only the release line they run. The test harness is still 2026.10.4 (no 2026.11 release yet); this gap is recorded in PLAN.md and the README.

## 2026-11-25: PR workflow
- README now shows milestone status and compatibility. Added a PR template with the evidence and safety checklist. From now on, changes go through PRs to `main` (earlier commits were pushed directly while the repo was set up).

## 2026-11-25: owner decisions
- Domain renamed `cambridge_cxa_local` → `cambridge_cxa_home`. Repository is `supercolliderBE/ha-cambridge-cxa`, the MIT copyright holder is supercolliderBE, and git uses the GitHub noreply identity. See PLAN.md.
- Owner's HA is 2026.11.2, read from its mDNS announcement. Set the `hacs.json` minimum to 2026.10.0, the oldest version covered by tests.

## 2026-11-25: milestones 1 and 2
- Downloaded and read the official AP36646/2 PDF (SHA-256 recorded in protocol-evidence.md). Checked HA developer docs (moved to contributors.home-assistant.io) and HACS requirements. The legacy community integration was not consulted.
- Dev toolchain: `uv` + Python 3.14.10. `pytest-homeassistant-custom-component==0.13.375` pins HA 2026.10.4. The latest HA release is 2026.11.3, which needs Python ≥ 3.14.2.
- Added `protocol.py` (framing, encoder, stream decoder, typed events, commands) and `client.py` (connection, supervisor, reconnect, liveness poll, read-only `fetch_device_info`).
- Added `tools/mock_amplifier.py` (independent parser; configurable spec-silent behaviours) and `tools/probe.py` (raw read-only probe, opt-in writes, JSONL transcript; Python 3.11+, verified on 3.11 and 3.13; 3.10 fails).
- Tests: 135 passing (stable over repeated runs). Ruff lint and format clean.
- Handover corrections are recorded in protocol-evidence.md. The main ones: setter replies are inferred, not documented; next/previous source commands exist; standby behaviour and cable pinout are undocumented everywhere we looked.
- Dev tools installed on the workstation via Homebrew: `uv` and `poppler` (for PDF text extraction).
