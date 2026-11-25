"""Tests for framing, encoding and interpretation (AP36646/2)."""

from __future__ import annotations

import pytest

from custom_components.cambridge_cxa_home import protocol as p

# --- encoding: documented request examples, byte for byte ---------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (p.GET_POWER, b"#1,01\r"),
        (p.set_power(False), b"#1,02,0\r"),
        (p.set_power(True), b"#1,02,1\r"),
        (p.GET_MUTE, b"#1,03\r"),
        (p.set_mute(False), b"#1,04,0\r"),
        (p.set_mute(True), b"#1,04,1\r"),
        (p.GET_SOURCE, b"#3,01\r"),
        (p.NEXT_SOURCE, b"#3,02\r"),
        (p.PREVIOUS_SOURCE, b"#3,03\r"),
        (p.set_source("02"), b"#3,04,02\r"),
        (p.GET_PROTOCOL_VERSION, b"#13,01\r"),
        (p.GET_FIRMWARE_VERSION, b"#13,02\r"),
    ],
)
def test_default_encoding_matches_documented_examples(command: p.Command, expected: bytes) -> None:
    assert command.encode() == expected


def test_padded_group_format() -> None:
    assert p.GET_POWER.encode(p.GroupFormat.PADDED) == b"#01,01\r"
    assert p.set_source("20").encode(p.GroupFormat.PADDED) == b"#03,04,20\r"
    # Two-digit groups are identical in both forms.
    assert p.GET_PROTOCOL_VERSION.encode(p.GroupFormat.PADDED) == b"#13,01\r"


def test_terminator_is_cr_only() -> None:
    assert p.GET_POWER.encode().endswith(b"\r")
    assert b"\n" not in p.GET_POWER.encode()


@pytest.mark.parametrize("bad", ["", "a,b", "#", "\r", "é"])
def test_encode_rejects_unsafe_data(bad: str) -> None:
    with pytest.raises(ValueError):
        p.encode(1, 2, bad)


def test_encode_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        p.encode(100, 1)


@pytest.mark.parametrize(("raw", "norm"), [("0", "00"), ("2", "02"), ("20", "20")])
def test_normalize_source_code(raw: str, norm: str) -> None:
    assert p.normalize_source_code(raw) == norm


@pytest.mark.parametrize("bad", ["", "123", "a1", "-1", "²"])
def test_normalize_source_code_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        p.normalize_source_code(bad)


def test_set_source_validates_code() -> None:
    with pytest.raises(ValueError):
        p.set_source("abc")


# --- source tables -----------------------------------------------------------


def test_cxa81_source_table() -> None:
    assert p.SOURCES[p.Model.CXA81] == {
        "00": "A1",
        "01": "A2",
        "02": "A3",
        "03": "A4",
        "04": "D1",
        "05": "D2",
        "06": "D3",
        "14": "Bluetooth",
        "16": "USB Audio",
        "20": "A1 Balanced",
    }


def test_a1_balanced_is_distinct_from_a1() -> None:
    assert p.source_name(p.Model.CXA81, "00") == "A1"
    assert p.source_name(p.Model.CXA81, "20") == "A1 Balanced"


def test_cxa61_has_mp3_and_no_balanced() -> None:
    assert p.source_name(p.Model.CXA61, "10") == "MP3"
    assert p.source_name(p.Model.CXA61, "20") is None
    assert p.source_name(p.Model.CXA81, "10") is None


def test_source_names_unique_per_model() -> None:
    for table in p.SOURCES.values():
        assert len(set(table.values())) == len(table)


# --- parse_frame ---------------------------------------------------------------


def test_parse_documented_replies() -> None:
    frame = p.parse_frame(b"#02,01,1")
    assert frame == p.Frame(2, 1, "1", b"#02,01,1")
    assert isinstance(frame, p.Frame)
    assert frame.key == (2, 1)
    assert p.parse_frame(b"#00,04") == p.Frame(0, 4, None, b"#00,04")
    assert p.parse_frame(b"#14,02,01000G01061E") == p.Frame(
        14, 2, "01000G01061E", b"#14,02,01000G01061E"
    )


def test_parse_accepts_unpadded_group() -> None:
    frame = p.parse_frame(b"#2,01,0")
    assert isinstance(frame, p.Frame)
    assert frame.key == (2, 1)


@pytest.mark.parametrize(
    "raw",
    [
        b"02,01,1",  # no '#'
        b"#02",  # no number
        b"#xx,01",  # non-numeric group
        b"#123,01",  # group too long
        b"#02,1x",  # bad number
        b"#02,01,",  # empty data
        b"#02,01,\x01",  # control char
        b"#02,01,\xff",  # non-ASCII
        b"#02,01,1,2",  # extra comma inside data
    ],
)
def test_parse_rejects_malformed(raw: bytes) -> None:
    assert isinstance(p.parse_frame(raw), p.MalformedFrame)


# --- FrameDecoder: TCP stream behaviour ------------------------------------------


def _frames(items: list[p.Frame | p.MalformedFrame]) -> list[bytes]:
    return [item.raw for item in items if isinstance(item, p.Frame)]


def test_decoder_single_frame() -> None:
    assert _frames(p.FrameDecoder().feed(b"#02,01,1\r")) == [b"#02,01,1"]


def test_decoder_fragmented_byte_by_byte() -> None:
    decoder = p.FrameDecoder()
    out: list[p.Frame | p.MalformedFrame] = []
    for byte in b"#04,01,20\r":
        out += decoder.feed(bytes([byte]))
    assert _frames(out) == [b"#04,01,20"]


def test_decoder_coalesced_frames() -> None:
    out = p.FrameDecoder().feed(b"#02,01,1\r#02,03,0\r#04,01,20\r")
    assert _frames(out) == [b"#02,01,1", b"#02,03,0", b"#04,01,20"]


def test_decoder_split_across_reads() -> None:
    decoder = p.FrameDecoder()
    assert decoder.feed(b"#02,01,1\r#02,0") != []
    assert _frames(decoder.feed(b"3,1\r")) == [b"#02,03,1"]


@pytest.mark.parametrize("payload", [b"#02,01,1\r\n", b"\n#02,01,1\r", b"#02,01,1\n\r"])
def test_decoder_ignores_stray_lf(payload: bytes) -> None:
    assert _frames(p.FrameDecoder().feed(payload)) == [b"#02,01,1"]


def test_decoder_skips_empty_lines() -> None:
    assert p.FrameDecoder().feed(b"\r\r\r") == []


def test_decoder_drops_noise_before_hash() -> None:
    out = p.FrameDecoder().feed(b"\x00\xffgarbage#02,01,1\r")
    assert _frames(out) == [b"#02,01,1"]


def test_decoder_reports_line_without_hash() -> None:
    out = p.FrameDecoder().feed(b"hello\r#02,01,0\r")
    assert isinstance(out[0], p.MalformedFrame)
    assert _frames(out) == [b"#02,01,0"]


def test_decoder_bounds_buffer_and_recovers() -> None:
    decoder = p.FrameDecoder(max_length=16)
    out = decoder.feed(b"#" + b"9" * 100)
    assert len(out) == 1
    assert isinstance(out[0], p.MalformedFrame)
    assert len(decoder._buffer) <= 16
    # The rest of the oversized line is discarded until CR; then we recover.
    assert decoder.feed(b"9999\r") == []
    assert _frames(decoder.feed(b"#02,01,1\r")) == [b"#02,01,1"]


def test_decoder_reset_drops_partial() -> None:
    decoder = p.FrameDecoder()
    decoder.feed(b"#02,0")
    decoder.reset()
    assert _frames(decoder.feed(b"#02,03,1\r")) == [b"#02,03,1"]


# --- interpret ---------------------------------------------------------------------


def _interpret(raw: bytes) -> p.Event:
    frame = p.parse_frame(raw)
    assert isinstance(frame, p.Frame)
    return p.interpret(frame)


@pytest.mark.parametrize(
    ("raw", "event"),
    [
        (b"#02,01,1", p.PowerState(on=True)),
        (b"#02,01,0", p.PowerState(on=False)),
        (b"#02,03,0", p.MuteState(muted=False)),
        (b"#02,03,1", p.MuteState(muted=True)),
        (b"#04,01,02", p.SourceState("02")),
        (b"#04,01,2", p.SourceState("02")),
        (b"#04,01,20", p.SourceState("20")),
        (b"#14,01,1.0", p.ProtocolVersion("1.0")),
        (b"#14,02,01000G01061E", p.FirmwareVersion("01000G01061E")),
        (b"#00,01", p.DeviceError(p.ErrorCode.GROUP_UNKNOWN)),
        (b"#00,02", p.DeviceError(p.ErrorCode.NUMBER_UNKNOWN)),
        (b"#00,03", p.DeviceError(p.ErrorCode.DATA_ERROR)),
        (b"#00,04", p.DeviceError(p.ErrorCode.NOT_AVAILABLE)),
    ],
)
def test_interpret_documented_messages(raw: bytes, event: p.Event) -> None:
    assert _interpret(raw) == event


def test_firmware_version_keeps_leading_zeros() -> None:
    event = _interpret(b"#14,02,0001")
    assert isinstance(event, p.FirmwareVersion)
    assert event.version == "0001"


def test_undocumented_error_code_preserved() -> None:
    event = _interpret(b"#00,09")
    assert event == p.DeviceError(9)
    assert isinstance(event, p.DeviceError)
    assert "09" in event.description


@pytest.mark.parametrize(
    "raw",
    [
        b"#02,01,2",  # power value out of range
        b"#02,01",  # power reply without data
        b"#02,03,x",  # mute value invalid
        b"#02,02,1",  # undocumented reply number
        b"#04,01",  # source without data
        b"#04,01,abc",  # invalid source code
        b"#14,01",  # version without data
        b"#00,01,1",  # error with data
        b"#01,01",  # a *request* echoed back is not a reply
        b"#99,01,1",  # undocumented group
    ],
)
def test_interpret_unknown(raw: bytes) -> None:
    assert isinstance(_interpret(raw), p.UnknownMessage)


def test_reply_keys() -> None:
    assert p.GET_POWER.reply == p.set_power(True).reply == (2, 1)
    assert p.GET_MUTE.reply == p.set_mute(True).reply == (2, 3)
    assert p.GET_SOURCE.reply == p.set_source("00").reply == p.NEXT_SOURCE.reply == (4, 1)
    assert p.GET_PROTOCOL_VERSION.reply == (14, 1)
    assert p.GET_FIRMWARE_VERSION.reply == (14, 2)


def test_read_only_commands_do_not_change_state() -> None:
    assert all(not c.changes_state and c.data is None for c in p.READ_ONLY_COMMANDS)
    assert p.set_power(True).changes_state
