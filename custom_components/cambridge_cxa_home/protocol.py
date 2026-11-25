"""Cambridge Audio CXA61/CXA81 serial protocol: framing, encoding and parsing.

This module is pure Python with no Home Assistant imports, so it can be used
by the probe tool and tested in isolation.

Source of truth: Cambridge Audio "CXA61 and CXA81 Serial Control Protocol
v1.0", document AP36646/2 (PDF dated 2019-04-17). See docs/protocol-evidence.md
for the page-by-page provenance of every constant below and for the points
that are inferred rather than documented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum

FRAME_START = b"#"
FRAME_END = b"\r"  # ASCII 13. The spec says nothing about LF; we tolerate it.
FIELD_SEPARATOR = ","

# Longest documented frame is a firmware version reply (~22 bytes). Anything
# much longer without a CR is noise or a framing fault, not a real message.
MAX_FRAME_LENGTH = 64


class Group(IntEnum):
    """Command groups (AP36646/2, "Group Commands")."""

    ERROR = 0
    AMPLIFIER = 1
    AMPLIFIER_REPLY = 2
    SOURCE = 3
    SOURCE_REPLY = 4
    VERSION = 13
    VERSION_REPLY = 14


class ErrorCode(IntEnum):
    """Group 00 error numbers. The amplifier only ever sends these."""

    GROUP_UNKNOWN = 1
    NUMBER_UNKNOWN = 2
    DATA_ERROR = 3
    NOT_AVAILABLE = 4  # Valid command that cannot be actioned right now.


ERROR_DESCRIPTIONS: dict[ErrorCode, str] = {
    ErrorCode.GROUP_UNKNOWN: "Command group unknown",
    ErrorCode.NUMBER_UNKNOWN: "Command number unknown",
    ErrorCode.DATA_ERROR: "Command data error",
    ErrorCode.NOT_AVAILABLE: "Command not available",
}


class GroupFormat(Enum):
    """How to write the group field of outgoing commands.

    The spec's general format says the group is two bytes ("gg"), but its
    request examples write single-digit groups unpadded (``#1,01``,
    ``#3,04,02``), while replies and errors are padded (``#02,01,1``,
    ``#00,01``). Which form real firmware accepts has not been verified on
    hardware. We default to the form used in the documented request examples.
    """

    UNPADDED = "unpadded"  # "#1,01\r"  (documented request examples)
    PADDED = "padded"  # "#01,01\r" (documented general message format)


DEFAULT_GROUP_FORMAT = GroupFormat.UNPADDED


class Model(StrEnum):
    """Amplifier models covered by AP36646/2."""

    CXA61 = "CXA61"
    CXA81 = "CXA81"


# Source codes (AP36646/2, "Source Selection"). Codes are two-digit decimal
# strings in the documented examples (``#3,04,02``, ``#04,01,02``).
SOURCES: dict[Model, dict[str, str]] = {
    Model.CXA61: {
        "00": "A1",
        "01": "A2",
        "02": "A3",
        "03": "A4",
        "04": "D1",
        "05": "D2",
        "06": "D3",
        "10": "MP3",
        "14": "Bluetooth",
        "16": "USB Audio",
    },
    Model.CXA81: {
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
    },
}


def normalize_source_code(code: str) -> str:
    """Return a source code as the documented two-digit string.

    Raises ValueError for anything that is not one or two decimal digits.
    """
    if not (1 <= len(code) <= 2 and code.isdigit() and code.isascii()):
        raise ValueError(f"invalid source code {code!r}")
    return f"{int(code):02d}"


def source_name(model: Model, code: str) -> str | None:
    """Return the display name for a source code, or None if undocumented."""
    return SOURCES[model].get(code)


# --- Frames -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Frame:
    """One syntactically valid message, before semantic interpretation."""

    group: int
    number: int
    data: str | None
    raw: bytes

    @property
    def key(self) -> tuple[int, int]:
        """(group, number), used to match replies to requests."""
        return (self.group, self.number)


@dataclass(frozen=True, slots=True)
class MalformedFrame:
    """Bytes that were delimited like a frame but could not be parsed."""

    raw: bytes
    reason: str


def encode(
    group: int,
    number: int,
    data: str | None = None,
    group_format: GroupFormat = DEFAULT_GROUP_FORMAT,
) -> bytes:
    """Encode a command frame, e.g. ``encode(1, 1)`` gives ``#1,01`` + CR."""
    if not 0 <= group <= 99 or not 0 <= number <= 99:
        raise ValueError("group and number must be in 0..99")
    group_text = f"{group:02d}" if group_format is GroupFormat.PADDED else str(group)
    text = f"#{group_text},{number:02d}"
    if data is not None:
        if not data or not _is_safe_data(data):
            raise ValueError(f"invalid data field {data!r}")
        text += f",{data}"
    return text.encode("ascii") + FRAME_END


def parse_frame(raw: bytes) -> Frame | MalformedFrame:
    """Parse a single frame. ``raw`` excludes the CR terminator.

    Lenient on input: groups and numbers may be one or two digits, since the
    spec itself uses both forms. Strict on characters: printable ASCII only.
    """
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return MalformedFrame(raw, "non-ASCII bytes")
    if not text.startswith("#"):
        return MalformedFrame(raw, "missing '#' start byte")
    fields = text[1:].split(FIELD_SEPARATOR, 2)
    if len(fields) < 2:
        return MalformedFrame(raw, "missing command number")
    group_text, number_text = fields[0], fields[1]
    if not _is_small_number(group_text) or not _is_small_number(number_text):
        return MalformedFrame(raw, "group/number must be 1-2 decimal digits")
    data: str | None = None
    if len(fields) == 3:
        data = fields[2]
        if not data or not _is_safe_data(data):
            return MalformedFrame(raw, "invalid data field")
    return Frame(int(group_text), int(number_text), data, raw)


def _is_small_number(text: str) -> bool:
    return 1 <= len(text) <= 2 and text.isascii() and text.isdigit()


def _is_safe_data(text: str) -> bool:
    return all(0x20 <= ord(ch) < 0x7F and ch not in "#," for ch in text)


class FrameDecoder:
    """Incremental decoder for a TCP byte stream.

    TCP gives no message boundaries: one read may hold half a frame or several
    frames. Feed it whatever arrives and it yields complete items in order.

    * Frames end at CR. A stray LF (e.g. a bridge appending CRLF) is ignored.
    * Bytes before the last ``#`` in a line are discarded as line noise.
    * A line that grows past ``max_length`` without a CR is discarded and
      reported as malformed, so a noisy line cannot grow memory without bound.
    """

    def __init__(self, max_length: int = MAX_FRAME_LENGTH) -> None:
        self._buffer = bytearray()
        self._max_length = max_length
        self._overflowing = False

    def feed(self, data: bytes) -> list[Frame | MalformedFrame]:
        """Consume bytes and return any complete frames."""
        out: list[Frame | MalformedFrame] = []
        for byte in data:
            if byte == 0x0D:
                if self._overflowing:
                    self._overflowing = False
                elif self._buffer:
                    out.append(self._finish_line(bytes(self._buffer)))
                self._buffer.clear()
            elif byte == 0x0A or self._overflowing:
                continue
            else:
                self._buffer.append(byte)
                if len(self._buffer) > self._max_length:
                    out.append(MalformedFrame(bytes(self._buffer), "frame too long; discarded"))
                    self._buffer.clear()
                    self._overflowing = True
        return out

    @staticmethod
    def _finish_line(line: bytes) -> Frame | MalformedFrame:
        start = line.rfind(FRAME_START)
        if start < 0:
            return MalformedFrame(line, "no '#' in line")
        return parse_frame(line[start:])

    def reset(self) -> None:
        """Drop buffered partial data, e.g. after a reconnect."""
        self._buffer.clear()
        self._overflowing = False


# --- Semantic events ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PowerState:
    """Reply 02,01: current power state."""

    on: bool


@dataclass(frozen=True, slots=True)
class MuteState:
    """Reply 02,03: current mute state."""

    muted: bool


@dataclass(frozen=True, slots=True)
class SourceState:
    """Reply 04,01: current source, as a normalized two-digit code."""

    code: str


@dataclass(frozen=True, slots=True)
class ProtocolVersion:
    """Reply 14,01, e.g. "1.0"."""

    version: str


@dataclass(frozen=True, slots=True)
class FirmwareVersion:
    """Reply 14,02. Kept verbatim; its format is not documented."""

    version: str


@dataclass(frozen=True, slots=True)
class DeviceError:
    """Group 00: the amplifier rejected the most recent message."""

    code: ErrorCode | int

    @property
    def description(self) -> str:
        """Description from the spec, or a generic one for unknown codes."""
        if isinstance(self.code, ErrorCode):
            return ERROR_DESCRIPTIONS[self.code]
        return f"Undocumented error {self.code:02d}"


@dataclass(frozen=True, slots=True)
class UnknownMessage:
    """A well-formed frame we don't understand. Logged, never acted on."""

    frame: Frame
    reason: str


Event = (
    PowerState
    | MuteState
    | SourceState
    | ProtocolVersion
    | FirmwareVersion
    | DeviceError
    | UnknownMessage
)


def interpret(frame: Frame) -> Event:  # noqa: C901, PLR0911 -- flat dispatch table
    """Convert a frame from the amplifier into a typed event."""
    group, number, data = frame.group, frame.number, frame.data

    if group == Group.ERROR:
        if data is not None:
            return UnknownMessage(frame, "error frame with data")
        try:
            return DeviceError(ErrorCode(number))
        except ValueError:
            return DeviceError(number)

    if group == Group.AMPLIFIER_REPLY and number in (1, 3):
        if data not in ("0", "1"):
            return UnknownMessage(frame, "expected data 0 or 1")
        if number == 1:
            return PowerState(on=data == "1")
        return MuteState(muted=data == "1")

    if group == Group.SOURCE_REPLY and number == 1:
        if data is None:
            return UnknownMessage(frame, "source reply without data")
        try:
            return SourceState(normalize_source_code(data))
        except ValueError:
            return UnknownMessage(frame, "invalid source code")

    if group == Group.VERSION_REPLY and number in (1, 2):
        if data is None:
            return UnknownMessage(frame, "version reply without data")
        if number == 1:
            return ProtocolVersion(data)
        return FirmwareVersion(data)

    return UnknownMessage(frame, "undocumented group/number")


# --- Commands -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Command:
    """A request plus the reply key that answers it.

    The protocol has no transaction IDs, so a reply is matched to a request
    only by (group, number). For setters the spec lists no dedicated reply;
    we expect the matching "current state" reply because the spec says every
    message gets a reply or error, and those are the only replies defined in
    the reply groups. This inference must be confirmed on hardware.
    """

    group: Group
    number: int
    data: str | None
    reply: tuple[int, int]
    changes_state: bool

    def encode(self, group_format: GroupFormat = DEFAULT_GROUP_FORMAT) -> bytes:
        """Encode this command for the wire."""
        return encode(self.group, self.number, self.data, group_format)


_POWER_REPLY = (Group.AMPLIFIER_REPLY, 1)
_MUTE_REPLY = (Group.AMPLIFIER_REPLY, 3)
_SOURCE_REPLY = (Group.SOURCE_REPLY, 1)

GET_POWER = Command(Group.AMPLIFIER, 1, None, _POWER_REPLY, False)
GET_MUTE = Command(Group.AMPLIFIER, 3, None, _MUTE_REPLY, False)
GET_SOURCE = Command(Group.SOURCE, 1, None, _SOURCE_REPLY, False)
GET_PROTOCOL_VERSION = Command(Group.VERSION, 1, None, (Group.VERSION_REPLY, 1), False)
GET_FIRMWARE_VERSION = Command(Group.VERSION, 2, None, (Group.VERSION_REPLY, 2), False)
NEXT_SOURCE = Command(Group.SOURCE, 2, None, _SOURCE_REPLY, True)
PREVIOUS_SOURCE = Command(Group.SOURCE, 3, None, _SOURCE_REPLY, True)


def set_power(on: bool) -> Command:
    """Command 01,02: 1 = on, 0 = standby."""
    return Command(Group.AMPLIFIER, 2, "1" if on else "0", _POWER_REPLY, True)


def set_mute(muted: bool) -> Command:
    """Command 01,04: 1 = muted, 0 = unmuted."""
    return Command(Group.AMPLIFIER, 4, "1" if muted else "0", _MUTE_REPLY, True)


def set_source(code: str) -> Command:
    """Command 03,04 with a two-digit source code."""
    return Command(Group.SOURCE, 4, normalize_source_code(code), _SOURCE_REPLY, True)


READ_ONLY_COMMANDS: tuple[Command, ...] = (
    GET_POWER,
    GET_MUTE,
    GET_SOURCE,
    GET_PROTOCOL_VERSION,
    GET_FIRMWARE_VERSION,
)
