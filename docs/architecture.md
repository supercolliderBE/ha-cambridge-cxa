# Architecture

```
Home Assistant (container)
  custom_components/cambridge_cxa_home/
    __init__ / config_flow / media_player / diagnostics          (HA-specific)
          │ listener callbacks, async commands
    client.py   CXAClient      state, supervise, reconnect, poll   (no HA imports)
                CXAConnection  one socket, one reader task, request lock
    protocol.py framing, encode, parse, interpret                  (no HA imports)
          │ raw TCP, one long-lived connection
  USR-W610 (TCP server, transparent) ── RS232 9600 8N1 ── CXA81
```

`protocol.py` and `client.py` import nothing from Home Assistant. That keeps them unit-testable without HA, and lets `tools/probe.py` load `protocol.py` on any machine with Python 3.11+. (The probe loads the file directly so the integration's `__init__.py` never runs.) The handover's proposed `state.py` was folded into `client.py` as the immutable `AmplifierState`, because the state is small and owned by the client.

## Data flow
- **Reading.** Exactly one reader task per connection reads bytes and passes them to `FrameDecoder`. It parses and interprets each frame, then calls `CXAClient._handle_event`, which updates state and notifies listeners. *Only then* does it resolve the pending request, if the frame matches. Every reply updates state, whether anyone asked for it or not.
- **Writing.** `CXAConnection.request` holds an `asyncio.Lock`, so only one request is ever in flight. It registers the pending reply key before writing, then waits with a timeout. A `00,xx` error frame fails the in-flight request.
- **Setters** check that the reply's value matches the request. If not, they raise `CXANotConfirmedError`, so success is never reported falsely.

## Correlation limits
The protocol has no transaction IDs, so replies are matched only by `(group, number)`. If a request times out and its reply arrives late, that reply can satisfy a later request with the same key. State remains correct (the frame is still authoritative), but the later command's verdict can be wrong. The value check on setters narrows this window. A second TCP client on the bridge (the W610 allows up to 24) would break correlation further, so the docs advise running a single client.

## Connection lifecycle
1. `start()` connects, clears power/mute/source to *unknown*, and requires an answer to the **power query** as proof of life. It then reads mute, source, protocol and firmware versions, tolerating failures, and marks the client available. If anything fails, nothing is left running, so HA can retry setup.
2. The supervisor waits for loss. Every `poll_interval` (60 s by default) it sends a read-only power query; two consecutive failures count as a dead link. This catches half-open TCP over Wi-Fi, which TCP keepalive (enabled best-effort) can be slow to notice.
3. On loss, the in-flight request fails with `CXAConnectionLostError` and the client becomes unavailable. It then reconnects with jittered exponential backoff (1 s up to 60 s) and does a full resync. **Nothing is queued or replayed.** Commands issued while unavailable fail immediately with `CXANotConnectedError`.
4. `stop()` cancels the supervisor, closes the socket and awaits the reader. It is idempotent, and tests assert that no tasks leak.

## Testing strategy
- `tests/test_protocol.py`: byte-exact documented examples, the malformed-input corpus, and stream fragmentation, coalescing, noise and overflow.
- `tests/test_client.py`: the real client over loopback TCP against `tools/mock_amplifier.py`. The mock has its **own** parser and does not import `protocol.py`, so the two implementations cross-check each other.
- `tests/test_tools.py`: the probe CLI is read-only by default, refuses writes without opt-in, and returns the right exit codes.
- `tests/test_config_flow.py`, `test_init.py`, `test_media_player.py`, `test_diagnostics.py`: the integration inside HA's test harness, talking to the mock over loopback TCP. They cover read-only setup, error mapping, duplicates, reconfigure, setup retry, unload, shutdown, push updates, commands, the outage/recovery cycle, and diagnostics redaction.
