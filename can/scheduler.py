"""Polling of the RoCon registers.

Times are milliseconds of the ESP clock (extended to a monotonic counter), so
intervals and timeouts do not depend on the delay of the exchange with the
bridge. Only one request is open at a time; the bridge itself waits for the
bus to be quiet before it sends it.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import logging
from typing import Any, Final

from ..bridge.protocol import CanFrame
from .protocol import read_frame, register_of
from .table import CanValue, Decoded

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_MS: Final = 3000


@dataclass(slots=True)
class _Slot:
    value: CanValue
    interval_ms: int
    last_answer: int | None = None
    last_request: int | None = None
    answers: int = 0
    lost: int = 0
    lost_logged: bool = False

    @property
    def last_activity(self) -> int | None:
        times = [t for t in (self.last_answer, self.last_request) if t is not None]
        return max(times) if times else None


@dataclass(slots=True)
class _OpenRequest:
    slot: _Slot
    frame: CanFrame
    handed_at: int
    sent_at: int | None = None


class CanScheduler:
    """Decide which register to read next and assign received frames."""

    def __init__(
        self,
        values: Iterable[CanValue],
        intervals: Mapping[str, float],
        *,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
    ) -> None:
        """Initialize the scheduler with the values to poll and their intervals in s."""
        self._timeout_ms = timeout_ms
        self._slots: dict[str, _Slot] = {
            value.key: _Slot(value, round(intervals[value.key] * 1000))
            for value in values
        }
        self._by_address: dict[tuple[int, ...], list[_Slot]] = {}
        for slot in self._slots.values():
            self._by_address.setdefault(slot.value.register.address, []).append(slot)
        self._open: _OpenRequest | None = None
        self.unhandled = 0
        self.requests = 0

    @property
    def keys(self) -> list[str]:
        """Return the keys of the polled values."""
        return list(self._slots)

    def interval_ms(self, key: str) -> int:
        """Return the polling interval of a value."""
        return self._slots[key].interval_ms

    def reset(self) -> None:
        """Forget all times, e.g. after the connection to the bridge was lost."""
        self._open = None
        for slot in self._slots.values():
            slot.last_answer = None
            slot.last_request = None

    def handle_sent(self, timestamp: int, frame: CanFrame) -> None:
        """Record when the bridge actually sent the open request."""
        if (
            (request := self._open) is not None
            and request.sent_at is None
            and request.frame == frame
        ):
            request.sent_at = timestamp

    def handle_frame(
        self, timestamp: int, frame: CanFrame
    ) -> tuple[CanValue, Decoded | None] | None:
        """Assign a received frame to a value and decode it.

        Returns None for frames that carry none of the polled values. The
        decoded value is None if it is not plausible; the frame still counts
        as answer.
        """
        if len(frame.data) < 7:
            return None
        for slot in self._by_address.get(register_of(frame.data), ()):
            if not slot.value.register.accepts(frame):
                continue
            slot.last_answer = timestamp
            slot.answers += 1
            if slot.lost_logged:
                _LOGGER.info("CAN value %s answers again", slot.value.key)
                slot.lost_logged = False
            if self._open is not None and self._open.slot is slot:
                self._open = None
            return slot.value, slot.value.decode(frame.data)
        self.unhandled += 1
        return None

    def next_request(self, now: int) -> CanFrame | None:
        """Return the next read request, or None while one is open or none is due."""
        if (request := self._open) is not None:
            started = (
                request.sent_at if request.sent_at is not None else request.handed_at
            )
            if now - started < self._timeout_ms:
                return None
            self._request_lost(request)
        slot = self._most_overdue(now)
        if slot is None:
            return None
        frame = read_frame(slot.value.command)
        slot.last_request = now
        self._open = _OpenRequest(slot, frame, now)
        self.requests += 1
        return frame

    def _request_lost(self, request: _OpenRequest) -> None:
        slot = request.slot
        slot.lost += 1
        self._open = None
        if not slot.lost_logged:
            _LOGGER.warning(
                "No answer from the heat pump for %s (%s)",
                slot.value.key,
                slot.value.register,
            )
            slot.lost_logged = True
        else:
            _LOGGER.debug("Still no answer for %s", slot.value.key)

    def _most_overdue(self, now: int) -> _Slot | None:
        best: _Slot | None = None
        best_overdue = 0
        for slot in self._slots.values():
            last = slot.last_activity
            if last is None:
                # Never asked: in table order before everything else.
                return slot
            overdue = now - last - slot.interval_ms
            if overdue > 0 and (best is None or overdue > best_overdue):
                best, best_overdue = slot, overdue
        return best

    def diagnostics(self) -> dict[str, Any]:
        """Return the state of the scheduler."""
        request = self._open
        return {
            "requests": self.requests,
            "unhandled_frames": self.unhandled,
            "open_request": None
            if request is None
            else {
                "key": request.slot.value.key,
                "handed_at": request.handed_at,
                "sent_at": request.sent_at,
            },
            "values": {
                key: {
                    "interval_ms": slot.interval_ms,
                    "last_answer": slot.last_answer,
                    "answers": slot.answers,
                    "lost": slot.lost,
                }
                for key, slot in self._slots.items()
            },
        }
