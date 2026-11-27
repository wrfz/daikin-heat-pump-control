"""Tests for the serial protocols and their detection (no Home Assistant)."""

from custom_components.daikin_heat_pump_control.uart.protocol import (
    NAK,
    EventKind,
    FrameParser,
    ProbeStep,
    Protocol,
    ProtocolDetector,
    checksum,
    request,
    s_frame_length,
)

from sim.indoor import ERGA_0X61, S_0X55, i_frame, s_frame


def test_checksum() -> None:
    """The checksum is the complement of the byte sum."""
    assert checksum(bytes.fromhex("03 40 10")) == 0xAC
    assert checksum(bytes.fromhex("03 40 61")) == 0x5B
    assert checksum(bytes.fromhex("03 40 20")) == 0x9C
    assert checksum(b"") == 0xFF
    assert checksum(bytes.fromhex("02 54")) == 0xA9


def test_requests() -> None:
    """Requests of both protocols."""
    assert request(Protocol.I, 0x61) == bytes.fromhex("03 40 61 5B")
    assert request(Protocol.I, 0x60) == bytes.fromhex("03 40 60 5C")
    assert request(Protocol.S, 0x54) == bytes.fromhex("02 54 A9")
    assert request(Protocol.S, 0x53) == bytes.fromhex("02 53 AA")


def test_i_frame_in_pieces() -> None:
    """An answer arriving in pieces is taken once it is complete."""
    parser = FrameParser(Protocol.I)
    assert parser.feed(ERGA_0X61[:7]) == []
    assert parser.pending == ERGA_0X61[:7]
    events = parser.feed(ERGA_0X61[7:])
    assert [event.kind for event in events] == [EventKind.FRAME]
    frame = events[0].frame
    assert frame is not None
    assert frame.register == 0x61
    assert frame.payload == ERGA_0X61[3:-1]
    assert parser.pending == b""


def test_i_two_frames_and_nak() -> None:
    """Several answers and a NAK in one piece; a lone 0x15 waits."""
    parser = FrameParser(Protocol.I)
    first = i_frame(0x10, bytes(16))
    second = i_frame(0x20, bytes(17))
    events = parser.feed(first + NAK + second + NAK[:1])
    assert [event.kind for event in events] == [
        EventKind.FRAME,
        EventKind.NAK,
        EventKind.FRAME,
    ]
    assert parser.pending == NAK[:1]
    assert [event.kind for event in parser.feed(NAK[1:])] == [EventKind.NAK]


def test_i_invalid_bytes() -> None:
    """Wrong start byte, length or checksum drop the buffer."""
    parser = FrameParser(Protocol.I)
    events = parser.feed(bytes.fromhex("41 61 0E 00"))
    assert [event.kind for event in events] == [EventKind.INVALID]
    assert parser.pending == b""

    assert [event.kind for event in parser.feed(bytes.fromhex("40 61 21 00"))] == [
        EventKind.INVALID
    ]
    assert [event.kind for event in parser.feed(bytes.fromhex("40 61 01"))] == [
        EventKind.INVALID
    ]
    bad = bytearray(i_frame(0x61, bytes(12)))
    bad[-1] ^= 0xFF
    assert [event.kind for event in parser.feed(bytes(bad))] == [EventKind.INVALID]
    assert parser.feed(bytes.fromhex("40 61")) == []
    parser.clear()
    assert parser.pending == b""


def test_s_frames() -> None:
    """S answers have fixed lengths; a wrong checksum is only flagged."""
    assert s_frame_length(0x50) == 6
    assert s_frame_length(0x56) == 6
    assert s_frame_length(0x54) == 18
    parser = FrameParser(Protocol.S)
    assert parser.feed(S_0X55[:10]) == []
    events = parser.feed(S_0X55[10:] + NAK)
    assert [event.kind for event in events] == [EventKind.FRAME, EventKind.NAK]
    frame = events[0].frame
    assert frame is not None
    assert frame.register == 0x55
    assert frame.payload == S_0X55[1:-1]
    assert frame.checksum_ok

    bad = bytearray(s_frame(0x50, b"\x01\x02\x03\x04"))
    assert len(bad) == 6
    bad[-1] ^= 0xFF
    events = parser.feed(bytes(bad))
    assert events[0].frame is not None
    assert not events[0].frame.checksum_ok


def test_detect_i() -> None:
    """An I answer to the first probe means I."""
    detector = ProtocolDetector()
    assert detector.start(100) == request(Protocol.I, 0x60)
    detector.sent(120)
    assert detector.feed(b"\x40\x60") is None
    detection = detector.feed(b"\x12")
    assert detection is not None
    assert detection.protocol is Protocol.I
    assert detector.step is ProbeStep.DONE


def test_detect_s_by_nak() -> None:
    """A NAK to the I probe means S."""
    detector = ProtocolDetector()
    detector.start(0)
    assert detector.feed(NAK[:1]) is None
    detection = detector.feed(NAK[1:])
    assert detection is not None
    assert detection.protocol is Protocol.S


def test_detect_after_timeouts() -> None:
    """Without answer the S probe follows; its answer or NAK decides."""
    detector = ProtocolDetector()
    detector.start(0)
    detector.sent(10)
    detector.sent(500)  # only the first send counts
    assert detector.check_timeout(2009) == (None, None)
    probe, detection = detector.check_timeout(2010)
    assert probe == request(Protocol.S, 0x53)
    assert detection is None
    assert detector.step is ProbeStep.S
    detection = detector.feed(S_0X55[:1])
    assert detection is not None
    assert detection.protocol is Protocol.S

    detector.start(0)
    detector.check_timeout(2000)
    assert detector.feed(b"\x99") is None
    detection = detector.feed(b"")
    assert detection is None
    detector.start(0)
    detector.check_timeout(2000)
    detection = detector.feed(NAK)
    assert detection is not None
    assert detection.protocol is Protocol.I


def test_detect_without_answer() -> None:
    """Two probes without answer give no protocol."""
    detector = ProtocolDetector()
    detector.start(0)
    detector.check_timeout(2000)
    assert detector.check_timeout(3999) == (None, None)
    probe, detection = detector.check_timeout(4000)
    assert probe is None
    assert detection is not None
    assert detection.protocol is None
