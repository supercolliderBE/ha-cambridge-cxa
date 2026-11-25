# Protocol evidence

Every protocol behaviour in this project is classified as one of the following:

- **Documented**: stated in the manufacturer document below.
- **Inferred**: a reasonable reading of the document that it does not state outright. Must be confirmed on hardware.
- **Unknown**: the document says nothing. The code makes the behaviour configurable or tolerant, and the mock simulates several variants.
- **Observed**: measured on real hardware. *There are no observed entries yet.*

## Source document

| Field | Value |
|---|---|
| Title | CXA61 and CXA81 Serial Control Protocol v1.0 |
| Reference | AP36646/2, © Cambridge Audio Ltd 2019 |
| URL | <https://www.cambridgeaudio.com/sites/default/files/compliance/doc/AP366462%20CXA61%20CXA81%20Serial%20Control%20Protocol%20%281%29.pdf> |
| Retrieved | 2026-11-25, 627,067 bytes, 5 pages, PDF creation date 2019-04-17 |
| SHA-256 | `b38d48b6fb68d492e82dc086fcc40c0945e82c3c7d55782131cfbcd1582dd4a6` |

The PDF is copyrighted and not redistributed here (`*.pdf` is git-ignored). This file records functional facts with page references. If the hash of a newly downloaded copy differs, re-review this page.

The hardware manual (<https://www.cambridgeaudio.com/gbr/en/node/19421/printable/print>) only says an RS232 port exists for custom-install control. It does **not** give the connector gender, pinout or cable type, and it does not describe serial behaviour in standby.

## Documented facts (AP36646/2)

| Topic | Fact | Page | Code |
|---|---|---|---|
| Serial | 9600 baud, 8 data bits, no parity, 1 stop bit | 1 | docs only (bridge config) |
| Framing | ASCII; starts `#`; group `,` number `,` data; ends CR (13) | 1 | `protocol.encode`, `FrameDecoder` |
| Framing | General format shows `gg` = two-byte group, `nn` = two-byte number | 1 | see "group padding" below |
| Groups | 00 errors; 01/02 amplifier cmd/reply; 03/04 source cmd/reply; 13/14 version cmd/reply | 2 | `protocol.Group` |
| Replies | "Each message that is sent to the CXA unit should receive a response back which is either a Reply message or an Error message." | 2 | request/response matching |
| Push | Power, mute or source changes "by any means" (e.g. IR remote) send a Reply message unprompted | 2 | unsolicited events update state |
| Errors | 00,01 group unknown; 00,02 number unknown; 00,03 data error; 00,04 valid but can't be actioned now. Errors are sent only by the amplifier. | 3 | `ErrorCode`, `CXARejectedError` |
| Sources (CXA81) | 00 A1, 01 A2, 02 A3, 03 A4, 04 D1, 05 D2, 06 D3, 14 Bluetooth, 16 USB Audio, 20 A1 Balanced | 3 | `SOURCES[CXA81]` |
| Sources (CXA61) | 00–06 as above, 10 MP3, 14 Bluetooth, 16 USB Audio (no A1 Balanced) | 3 | `SOURCES[CXA61]` |
| Amp commands | 01,01 get power; 01,02,{0 standby/1 on} set power; 01,03 get mute; 01,04,{0 off/1 muted} set mute | 4 | `GET_POWER`, `set_power`… |
| Amp replies | 02,01,{0/1} power state; 02,03,{0/1} mute state | 4 | `interpret` |
| Source commands | 03,01 get; **03,02 next; 03,03 previous**; 03,04,{code} set | 4 | `GET_SOURCE`, `NEXT_SOURCE`… |
| Source reply | 04,01,{code} | 4 | `SourceState` |
| Version | 13,01 → 14,01,`x.x` (protocol, e.g. `1.0`); 13,02 → 14,02,`x` (firmware, example `01000G01061E`) | 5 | `ProtocolVersion`, `FirmwareVersion` |

**Not in the document:** volume, balance, tone, display, input names, serial number, or any transport control. None is implemented, and none should be probed blindly.

## Inferred (confirm on hardware)

1. **Setter replies.** The document gives no reply for 01,02 / 01,04 / 03,02–03,04. Two things together suggest the reply is the matching "current state" reply (02,01 / 02,03 / 04,01): every message gets a reply or an error, and those are the only replies defined. The client waits for that key and checks the value (`CXANotConfirmedError` on mismatch).
2. **The amplifier answers while in standby.** The power reply defines `0 - Standby`, which suggests the unit can report standby. The setup check and the liveness poll depend on this.
3. **Error attribution.** Error frames carry no reference to the command that caused them. We attribute an error to the single in-flight request.
4. **Source codes in replies are two digits** (example `#04,01,02`). The parser also accepts one digit and normalizes it.

## Unknown (configurable or tolerated)

| Unknown | Handling | Mock knob |
|---|---|---|
| **Group padding of requests.** Request examples are unpadded (`#1,01`, `#3,04,02`), which contradicts the `gg` format. Reply and error examples are padded (`#02,01,1`, `#00,01`). | Default: documented example form (`GroupFormat.UNPADDED`); `PADDED` available. The parser accepts both. The probe's `--group-format both` settles it. | `accept_group_format` |
| Which commands work in standby | Nothing in standby is assumed except the power query. Unanswered or rejected mute/source queries leave the values *unknown* (`None`). | `standby_mode` |
| Whether a setter also produces a separate push frame | Duplicates are harmless: state updates are idempotent, and an extra frame with no pending request is just an event. | `duplicate_notifications` |
| Reply latency, wake-up time from standby | Request timeout 3 s, power timeout 10 s, both configurable. To be measured. | `reply_delay`, `power_on_delay` |
| Line endings added by the bridge | A stray LF is ignored. | `line_ending` |
| Firmware version format | Kept verbatim as a string. Never used as identity. | `firmware_version` |
| Mk II models | Not covered by AP36646/2. Unsupported until validated. | n/a |

## Corrections to the handover document

| Handover statement | Finding |
|---|---|
| Implement power, mute, source, version | Correct. The document **also** defines next/previous source (03,02 / 03,03). These are implemented in the client but not planned for the MVP UI. |
| "Example read-only request `#1,01`; reply `#02,01,1`" | Confirmed (page 4). |
| Two-digit vs single-digit group inconsistency | Confirmed, and more specific: *requests* are unpadded in the examples, while *replies and errors* are padded. Version requests (`#13,01`) are two-digit by nature. |
| Setters return a reply | **Not documented**; inferred only (see above). |
| "Read official command tables for … error meanings" | Only four generic error codes exist. Errors do not say which command they refer to. |
| Standby behaviour "reopen the PDF" | The PDF says nothing about standby. Neither does the hardware manual. This remains a hardware test. |
| Cable compatibility | Neither Cambridge document gives gender or pinout. Later research: the W610 manual confirms **DB9 male** (no pin table); a review says the CXA81 is **DB9 female**; Cambridge's convention (CXR FAQ) is straight-through. A straight-through M-F cable is therefore likely right, but unverified. See hardware-setup.md for the multimeter check. |
| HA docs at developers.home-assistant.io | These now redirect to contributors.home-assistant.io. `MediaPlayerState.STANDBY` is deprecated, so standby maps to `off`. |
| HACS branding | Since HA 2026.3, custom integrations ship `custom_components/<domain>/brand/icon.png`. We need an original icon; Cambridge's logo can't be used. |
| "Avoid competing TCP clients" | Real risk. The W610 allows up to 24 TCP clients in server mode, and another client's commands would confuse reply correlation. |
