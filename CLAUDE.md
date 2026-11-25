# Working rules for this repository

- Brief: `CLAUDE_CODE_HANDOVER.md`. Its known errors are corrected in `docs/protocol-evidence.md`; that file and `docs/PLAN.md` take precedence.
- Do **not** read, copy or adapt `lievencoghe/cambridge_cxa`, its forks or its PRs (no licence). Sources: Cambridge AP36646/2 and the official HA/HACS docs only.
- Never invent protocol details. Classify each behaviour as documented, inferred, unknown or observed in `docs/protocol-evidence.md`. Hardware claims go only in `docs/hardware-validation.md`, with evidence.
- `protocol.py` and `client.py` must not import `homeassistant`.
- `tools/mock_amplifier.py` must not import the integration (it is an independent cross-check).
- Setup, validation and the probe stay read-only. Never queue, retry or replay state-changing commands.
- Before committing: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`. Add a dated entry to `docs/progress-log.md`.
- Work on a branch and open a PR to `main`; never push to `main` directly. Wait for CI to pass, and merge only when the owner approves.
- Do not push, publish, or install into the production Home Assistant without explicit approval.
