# Progress log

## 2026-11-25: cable research and branch cleanup
- Pinout research recorded in hardware-setup.md: W610 is DB9 male (PUSR manual), CXA81 DB9 female (review), Cambridge recommends straight-through for its CXR receivers. Added a multimeter method to find each TX pin, and the options if the wiring doesn't match.
- Deleted three merged branches; turned on automatic deletion of PR branches after merge.

## 2026-11-25: main protected
- Added a repository ruleset "Protect main": pull request required (0 approvals, so the owner can merge their own PRs), required checks `test` and `hassfest`, force-push and deletion blocked, no bypass actors. Verified: a direct push to `main` is rejected with GH013.

## 2026-11-25: documentation catch-up
- After PR #3 merged: updated hardware-validation.md (165 tests broken down by suite, validator results, new checklist items H14–H16 for the real HA install), the README layout and feature text, architecture.md, the plan status, and an "Add to Home Assistant" step in hardware-setup.md.

## 2026-11-25: milestone 3 (HA MVP)
- Repo made public after rewriting two web-merge commits that carried the owner's real email (owner enabled GitHub email privacy).
- Added `__init__.py` (setup/unload, `ConfigEntryNotReady`, stop on HA shutdown), `config_flow.py` (user + reconfigure, read-only validation, duplicate prevention, generated unique ID), `media_player.py`, `diagnostics.py`, `strings.json` and `translations/en.json`. `manifest.json` now has `config_flow: true`.
- 30 new HA-level tests (165 total), stable across 6 runs. They run against the simulator only.
- Found while testing: in HA 2026.10, `device_registry.async_get_device` is deprecated (identifiers are no longer unique across config entries); tests use `async_get_device_by_identifier`. HA skips unavailable entities in service calls, so commands during an outage never reach the integration.
- Official validators: hassfest caught uppercase selector translation keys (fixed: `cxa61`/`cxa81`); hassfest now runs on every PR. HACS action: 9/10 checks pass. The only failure is the missing brand icon (Milestone 5). Added the manifest `categories` field (`media_entertainment.speakers_audio`) after a HACS warning.
- Not done yet: an end-to-end run in a real HA instance with the UI (tests use HA's own test harness). Planned before the hardware beta.

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
