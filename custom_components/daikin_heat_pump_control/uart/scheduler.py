"""Polling of the indoor unit registers.

Only one request is open at a time. A request is lost without an answer
within 3 s. A register is due 5 s after its last valid answer; of the due
registers the one sent longest ago goes first. After three failures in a row
(NAK, no answer, bad frame) a register counts as failed and is only asked
every 10 minutes until it answers again. Times are ESP milliseconds.
"""

from collections.abc import Iterable
from dataclasses import dataclass
import logging
from typing import Any, Final

from .protocol import Frame, Protocol, request

_LOGGER = logging.getLogger(__name__)

ANSWER_TIMEOUT_MS: Final = 3000
POLL_INTERVAL_MS: Final = 5000
FAILED_INTERVAL_MS: Final = 600_000
FAILURES_UNTIL_FAILED: Final = 3


@dataclass(slots=True)
class RegisterState:
    """Polling state of one register."""

    register: int
    last_sent: int | None = None
    last_answer: int | None = None
    failures: int = 0
    answers: int = 0
    lost: int = 0

    @property
    def failed(self) -> bool:
        """Return True while the register does not answer."""
        return self.failures >= FAILURES_UNTIL_FAILED


@dataclass(slots=True)
class OpenRequest:
    """The request waiting for its answer."""

    register: int
    queued_at: int
    sent_at: int | None = None

    @property
    def since(self) -> int:
        """Return the time from which the answer timeout runs."""
        return self.queued_at if self.sent_at is None else self.sent_at


class UartScheduler:
    """Decide which register to request next."""

    def __init__(self, protocol: Protocol, registers: Iterable[int]) -> None:
        """Initialize for the registers to poll, in table order."""
        self.protocol = protocol
        self.registers: dict[int, RegisterState] = {
            register: RegisterState(register) for register in dict.fromkeys(registers)
        }
        self.open: OpenRequest | None = None

    def reset(self) -> None:
        """Forget the open request and the times after a connection loss."""
        self.open = None
        for state in self.registers.values():
            state.last_sent = None
            state.last_answer = None

    @property
    def all_failed(self) -> bool:
        """Return True if every polled register failed."""
        return bool(self.registers) and all(
            state.failed for state in self.registers.values()
        )

    def is_failed(self, register: int) -> bool:
        """Return True if a register currently counts as failed."""
        state = self.registers.get(register)
        return state is not None and state.failed

    def handle_sent(self, timestamp: int) -> None:
        """Note the time at which the open request was sent."""
        if self.open is not None and self.open.sent_at is None:
            self.open.sent_at = timestamp

    def handle_frame(self, timestamp: int, frame: Frame) -> bool:
        """Note an answer; return True if the register was failed before."""
        state = self.registers.get(frame.register)
        if self.open is not None and self.open.register == frame.register:
            self.open = None
        if state is None:
            return False
        recovered = state.failed
        state.last_answer = timestamp
        state.failures = 0
        state.answers += 1
        if recovered:
            _LOGGER.info("UART register 0x%02X answers again", state.register)
        return recovered

    def handle_failure(self) -> int | None:
        """Fail the open request (NAK); return its register if it just failed."""
        if self.open is None:
            return None
        register = self.open.register
        self.open = None
        return self._fail(register)

    def check_timeout(self, now: int) -> int | None:
        """Fail an open request without answer; return its register if it failed."""
        open_request = self.open
        if open_request is None or now - open_request.since < ANSWER_TIMEOUT_MS:
            return None
        self.open = None
        return self._fail(open_request.register)

    def _fail(self, register: int) -> int | None:
        state = self.registers[register]
        state.lost += 1
        state.failures += 1
        if state.failures != FAILURES_UNTIL_FAILED:
            return None
        _LOGGER.warning(
            "UART register 0x%02X does not answer; asking again every %d minutes",
            register,
            FAILED_INTERVAL_MS // 60_000,
        )
        return register

    def retry_failed(self) -> None:
        """Ask the failed registers right away, e.g. after the unit answered."""
        for state in self.registers.values():
            if state.failed:
                state.last_sent = None

    def _due(self, state: RegisterState, now: int) -> bool:
        if state.failed:
            return (
                state.last_sent is None or now - state.last_sent >= FAILED_INTERVAL_MS
            )
        return state.last_answer is None or now - state.last_answer > POLL_INTERVAL_MS

    def next_request(self, now: int) -> bytes | None:
        """Return the next request to send, if any is due."""
        if self.open is not None:
            return None
        due = [state for state in self.registers.values() if self._due(state, now)]
        if not due:
            return None
        state = min(
            due, key=lambda item: -1 if item.last_sent is None else item.last_sent
        )
        state.last_sent = now
        self.open = OpenRequest(state.register, queued_at=now)
        return request(self.protocol, state.register)

    def diagnostics(self) -> dict[str, Any]:
        """Return the state of the registers."""
        return {
            "protocol": self.protocol,
            "open": None
            if self.open is None
            else {
                "register": f"{self.open.register:02X}",
                "sent_at": self.open.sent_at,
            },
            "registers": {
                f"{state.register:02X}": {
                    "last_sent": state.last_sent,
                    "last_answer": state.last_answer,
                    "answers": state.answers,
                    "lost": state.lost,
                    "failures": state.failures,
                    "failed": state.failed,
                }
                for state in self.registers.values()
            },
        }
