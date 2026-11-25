## What and why
<!-- One or two sentences. Link the issue or milestone. -->

## Checklist
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` pass locally
- [ ] Any new protocol behaviour is classified (documented / inferred / unknown / observed) in `docs/protocol-evidence.md`
- [ ] Hardware claims are backed by an entry in `docs/hardware-validation.md` (simulator results don't count)
- [ ] No code copied or adapted from unlicensed sources (see README, "Provenance")
- [ ] Setup and probing stay read-only; no queued, retried or replayed writes
- [ ] `docs/progress-log.md` updated
