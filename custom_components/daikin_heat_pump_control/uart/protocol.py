"""Serial protocols of the indoor unit at the X10A connector.

Protocol I: request `03 40 <register> <checksum>`, answer
`40 <register> <length> <payload> <checksum>` where the length counts from
the register byte to the checksum.

Protocol S (older units): request `02 <register> <checksum>`, answer
`<register> <payload> <checksum>` with a fixed length per register.

A unit answers a request it does not know with `15 EA` (NAK). The checksum is
the complement of the byte sum.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

NAK: Final = bytes((0x15, 0xEA))
I_REQUEST: Final = bytes((0x03, 0x40))
I_ANSWER: Final = 0x40
S_REQUEST: Final = 0x02
I_MAX_LENGTH: Final = 32
S_LENGTH: Final = 18
S_SHORT_LENGTH: Final = 6
S_SHORT_REGISTERS: Final = frozenset({0x50, 0x56})


class Protocol(StrEnum):
    """Serial protocol of the indoor unit."""

    I = "i"  # noqa: E741
    S = "s"


def checksum(data: bytes) -> int:
    """Return the checksum of the bytes: the complement of their sum."""
    return (~sum(data)) & 0xFF


def request(protocol: Protocol, register: int) -> bytes:
    """Return the request for a register."""
    head = (
        I_REQUEST + bytes((register,))
        if protocol is Protocol.I
        else bytes((S_REQUEST, register))
    )
    return head + bytes((checksum(head),))


def s_frame_length(register: int) -> int:
    """Return the length of an S answer including register byte and checksum."""
    return S_SHORT_LENGTH if register in S_SHORT_REGISTERS else S_LENGTH


class EventKind(StrEnum):
    """What the parser found in the received bytes."""

    FRAME = "frame"
    NAK = "nak"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True, kw_only=True)
class Frame:
    """An answer of the indoor unit."""

    register: int
    payload: bytes
    raw: bytes
    checksum_ok: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """A frame, a NAK or bytes that were dropped."""

    kind: EventKind
    data: bytes
    frame: Frame | None = None


class FrameParser:
    """Split the received bytes into answers.

    Answers may arrive in pieces; incomplete bytes stay in the buffer until
    the rest arrives or `clear` is called.
    """

    def __init__(self, protocol: Protocol) -> None:
        """Initialize the parser for a protocol."""
        self.protocol = protocol
        self._buffer = bytearray()

    @property
    def pending(self) -> bytes:
        """Return the bytes waiting for the rest of an answer."""
        return bytes(self._buffer)

    def clear(self) -> None:
        """Drop incomplete bytes."""
        self._buffer.clear()

    def feed(self, data: bytes) -> list[Event]:
        """Add received bytes; return the answers and NAKs found."""
        self._buffer.extend(data)
        events: list[Event] = []
        while self._buffer:
            buffer = self._buffer
            if buffer[:2] == NAK:
                del buffer[:2]
                events.append(Event(kind=EventKind.NAK, data=NAK))
                continue
            if len(buffer) == 1 and buffer[0] == NAK[0]:
                break
            event = self._take_i() if self.protocol is Protocol.I else self._take_s()
            if event is None:
                break
            events.append(event)
        return events

    def _drop_all(self) -> Event:
        data = bytes(self._buffer)
        self._buffer.clear()
        return Event(kind=EventKind.INVALID, data=data)

    def _take_i(self) -> Event | None:
        buffer = self._buffer
        if buffer[0] != I_ANSWER:
            return self._drop_all()
        if len(buffer) < 3:
            return None
        length = buffer[2]
        if not 2 <= length <= I_MAX_LENGTH:
            return self._drop_all()
        total = 2 + length
        if len(buffer) < total:
            return None
        raw = bytes(buffer[:total])
        if checksum(raw[:-1]) != raw[-1]:
            return self._drop_all()
        del buffer[:total]
        frame = Frame(register=raw[1], payload=raw[3:-1], raw=raw)
        return Event(kind=EventKind.FRAME, data=raw, frame=frame)

    def _take_s(self) -> Event | None:
        buffer = self._buffer
        total = s_frame_length(buffer[0])
        if len(buffer) < total:
            return None
        raw = bytes(buffer[:total])
        del buffer[:total]
        frame = Frame(
            register=raw[0],
            payload=raw[1:-1],
            raw=raw,
            checksum_ok=checksum(raw[:-1]) == raw[-1],
        )
        return Event(kind=EventKind.FRAME, data=raw, frame=frame)


# ------------------------------------------------------------ detection

PROBE_TIMEOUT_MS: Final = 2000
I_PROBE_REGISTER: Final = 0x60
S_PROBE_REGISTER: Final = 0x53
S_ANSWER_REGISTERS: Final = frozenset({0x50, 0x53, 0x54, 0x55, 0x56})


class ProbeStep(StrEnum):
    """Step of the protocol detection."""

    I = "i"  # noqa: E741
    S = "s"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class Detection:
    """Result of the protocol detection; `protocol` is None without any answer."""

    protocol: Protocol | None


class ProtocolDetector:
    """Find out which protocol the indoor unit speaks.

    First the I request for 0x60: an I answer means I, a NAK means S. Without
    answer within 2 s the S request for 0x53: an S answer means S, a NAK
    means I. Without answer within another 2 s there is no result.
    """

    def __init__(self) -> None:
        """Initialize the detector."""
        self.step = ProbeStep.I
        self._buffer = bytearray()
        self._since = 0
        self._sent = False

    def start(self, now: int) -> bytes:
        """Return the first probe, handed to the bridge at `now`."""
        self.step = ProbeStep.I
        return self._probe(now, request(Protocol.I, I_PROBE_REGISTER))

    def _probe(self, now: int, probe: bytes) -> bytes:
        self._buffer.clear()
        self._since = now
        self._sent = False
        return probe

    def sent(self, timestamp: int) -> None:
        """Note the time at which the probe was sent."""
        if not self._sent:
            self._since = timestamp
            self._sent = True

    def feed(self, data: Iterable[int]) -> Detection | None:
        """Add received bytes; return the result once the answer is clear."""
        self._buffer.extend(data)
        buffer = self._buffer
        if self.step is ProbeStep.I:
            if buffer[:2] == NAK:
                return self._done(Protocol.S)
            if len(buffer) >= 3 and buffer[0] == I_ANSWER:
                return self._done(Protocol.I)
        elif self.step is ProbeStep.S:
            if buffer[:2] == NAK:
                return self._done(Protocol.I)
            if buffer and buffer[0] in S_ANSWER_REGISTERS:
                return self._done(Protocol.S)
        return None

    def check_timeout(self, now: int) -> tuple[bytes | None, Detection | None]:
        """Move on after a probe without answer.

        Returns the next probe to send, or the result when both probes went
        unanswered.
        """
        if now - self._since < PROBE_TIMEOUT_MS:
            return None, None
        if self.step is ProbeStep.I:
            self.step = ProbeStep.S
            return self._probe(now, request(Protocol.S, S_PROBE_REGISTER)), None
        if self.step is ProbeStep.S:
            return None, self._done(None)
        return None, None  # pragma: no cover

    def _done(self, protocol: Protocol | None) -> Detection:
        self.step = ProbeStep.DONE
        self._buffer.clear()
        return Detection(protocol)
