"""Polling of the RoCon registers and the queue of writes.

Times are milliseconds of the ESP clock (extended to a monotonic counter), so
intervals and timeouts do not depend on the delay of the exchange with the
bridge. Only one request is open at a time; the bridge itself waits for the
bus to be quiet before it sends a frame.

Writes and raw frames wait in a queue and go before the polling. A write is
handed to the bridge together with a read of the same register; the answer
to that read, received after the write was sent, confirms the write.
"""

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import logging
from typing import Any, Final

from ..bridge.protocol import CanFrame
from .protocol import (
    FRAME_LENGTH,
    LONG_REGISTER,
    OWN_ID,
    Kind,
    frame_kind,
    read_frame,
    register_of,
)
from .table import CanValue, Decoded

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_MS: Final = 3000
RAW: Final = "raw"


@dataclass(frozen=True, slots=True, kw_only=True)
class Outcome:
    """Result of a write or of a raw frame."""

    # True once the bridge reported the (write or raw) frame as sent.
    sent: bool
    # The answer: the read-back frame of a write, or the answer to a raw read.
    answer: CanFrame | None = None
    # The read-back value of a write; None if it was not plausible.
    decoded: Decoded | None = None


type Done = Callable[[Outcome], None]


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


@dataclass(slots=True, eq=False)
class Job:
    """A queued write or raw frame."""

    key: str
    frames: tuple[CanFrame, ...]
    done: Done
    # The frame of kind write that is counted when it is sent.
    write: CanFrame | None = None
    # Writes: the value read back. Raw reads: the register of the answer.
    slot: _Slot | None = None
    answer_register: tuple[int, ...] | None = None
    cancelled: bool = False

    def cancel(self) -> None:
        """Do not report the outcome; a job not handed over yet is dropped."""
        self.cancelled = True


@dataclass(slots=True)
class _OpenRequest:
    # Sending this frame starts the timeout.
    frame: CanFrame
    handed_at: int
    slot: _Slot | None = None
    job: Job | None = None
    sent_at: int | None = None
    written_at: int | None = None


@dataclass(slots=True)
class _Counters:
    requests: int = 0
    unhandled: int = 0
    writes: int = 0
    write_failures: int = 0
    raw: int = 0


def _raw_register(data: bytes) -> tuple[int, ...] | None:
    """Return the register of a raw frame, or None if it carries none."""
    if len(data) < 3 or (data[2] == LONG_REGISTER and len(data) < 5):
        return None
    return register_of(data)


class CanScheduler:
    """Decide which frame to send next and assign received frames."""

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
        self._jobs: deque[Job] = deque()
        self._counters = _Counters()

    @property
    def keys(self) -> list[str]:
        """Return the keys of the polled values."""
        return list(self._slots)

    @property
    def unhandled(self) -> int:
        """Return the number of received frames that carried no polled value."""
        return self._counters.unhandled

    @property
    def requests(self) -> int:
        """Return the number of read requests handed to the bridge."""
        return self._counters.requests

    def interval_ms(self, key: str) -> int:
        """Return the polling interval of a value."""
        return self._slots[key].interval_ms

    def reset(self) -> None:
        """Forget all times and fail all writes, e.g. after the connection was lost."""
        outcomes = [(job, Outcome(sent=False)) for job in self._jobs]
        self._jobs.clear()
        if (request := self._open) is not None and request.job is not None:
            sent = request.written_at is not None or (
                request.job.write is None and request.sent_at is not None
            )
            outcomes.insert(0, (request.job, Outcome(sent=sent)))
        self._open = None
        for slot in self._slots.values():
            slot.last_answer = None
            slot.last_request = None
        if dropped := [item for item in outcomes if not item[0].cancelled]:
            _LOGGER.warning(
                "Dropped %d CAN write(s) because the bus is unavailable: %s",
                len(dropped),
                ", ".join(job.key for job, _ in dropped),
            )
            for job, outcome in dropped:
                self._finish(job, outcome)

    # ------------------------------------------------------------- requests

    def request_write(self, key: str, data: bytes, done: Done) -> Job:
        """Queue a write of a polled value; `done` gets the read-back value."""
        slot = self._slots[key]
        write = CanFrame(can_id=OWN_ID, data=data)
        job = Job(
            key=key,
            frames=(write, read_frame(slot.value.command)),
            done=done,
            write=write,
            slot=slot,
        )
        self._jobs.append(job)
        return job

    def request_raw(self, data: bytes, done: Done) -> Job:
        """Queue a raw frame; `done` gets the first answer to a read request."""
        frame = CanFrame(can_id=OWN_ID, data=data)
        register = _raw_register(data)
        is_read = register is not None and frame_kind(data) == Kind.READ
        job = Job(
            key=RAW,
            frames=(frame,),
            done=done,
            write=frame if frame_kind(data) == Kind.WRITE else None,
            answer_register=register if is_read else None,
        )
        self._jobs.append(job)
        return job

    def _finish(self, job: Job, outcome: Outcome) -> None:
        if not job.cancelled:
            job.done(outcome)

    # -------------------------------------------------------------- frames

    def handle_sent(self, timestamp: int, frame: CanFrame) -> str | None:
        """Record a frame the bridge sent; return the key if it was a write."""
        request = self._open
        if request is None:
            return None
        job = request.job
        if (
            job is not None
            and job.write is not None
            and request.written_at is None
            and frame == job.write
        ):
            request.written_at = timestamp
            self._counters.writes += 1
            if job.slot is None and job.answer_register is None:
                # Raw frame without answer: done once it is on the bus.
                self._open = None
                self._finish(job, Outcome(sent=True))
            return job.key
        if request.sent_at is None and frame == request.frame:
            request.sent_at = timestamp
            if job is not None and job.slot is None and job.answer_register is None:
                self._open = None
                self._finish(job, Outcome(sent=True))
        return None

    def handle_frame(
        self, timestamp: int, frame: CanFrame
    ) -> tuple[CanValue, Decoded | None] | None:
        """Assign a received frame to a value and decode it.

        Returns None for frames that carry none of the polled values. The
        decoded value is None if it is not plausible; the frame still counts
        as answer.
        """
        self._match_raw(frame)
        if len(frame.data) < FRAME_LENGTH:
            return None
        for slot in self._by_address.get(register_of(frame.data), ()):
            if not slot.value.register.accepts(frame):
                continue
            slot.last_answer = timestamp
            slot.answers += 1
            if slot.lost_logged:
                _LOGGER.info("CAN value %s answers again", slot.value.key)
                slot.lost_logged = False
            decoded = slot.value.decode(frame.data)
            self._match_slot(slot, timestamp, frame, decoded)
            return slot.value, decoded
        self._counters.unhandled += 1
        return None

    def _match_raw(self, frame: CanFrame) -> None:
        request = self._open
        if (
            request is None
            or (job := request.job) is None
            or job.answer_register is None
            or frame.can_id == OWN_ID
            or len(frame.data) < 3
            or frame_kind(frame.data) != Kind.ANSWER
            or _raw_register(frame.data) != job.answer_register
        ):
            return
        self._open = None
        self._finish(job, Outcome(sent=True, answer=frame))

    def _match_slot(
        self, slot: _Slot, timestamp: int, frame: CanFrame, decoded: Decoded | None
    ) -> None:
        request = self._open
        if request is None or request.slot is not slot:
            return
        job = request.job
        if job is None:
            self._open = None
            return
        if request.written_at is None or timestamp < request.written_at:
            # Heard before the write reached the bus: not the read-back.
            return
        self._open = None
        self._finish(job, Outcome(sent=True, answer=frame, decoded=decoded))

    # ------------------------------------------------------------ planning

    def next_request(self, now: int) -> list[CanFrame]:
        """Return the frames to hand to the bridge; empty while one is open."""
        if (request := self._open) is not None:
            started = (
                request.sent_at if request.sent_at is not None else request.handed_at
            )
            if now - started < self._timeout_ms:
                return []
            self._request_lost(request)
        while self._jobs:
            job = self._jobs.popleft()
            if job.cancelled:
                continue
            return self._start_job(job, now)
        slot = self._most_overdue(now)
        if slot is None:
            return []
        frame = read_frame(slot.value.command)
        slot.last_request = now
        self._open = _OpenRequest(frame, now, slot=slot)
        self._counters.requests += 1
        return [frame]

    def _start_job(self, job: Job, now: int) -> list[CanFrame]:
        if job.slot is not None:
            job.slot.last_request = now
            self._counters.requests += 1
        else:
            self._counters.raw += 1
        self._open = _OpenRequest(job.frames[-1], now, slot=job.slot, job=job)
        return list(job.frames)

    def _request_lost(self, request: _OpenRequest) -> None:
        self._open = None
        if (job := request.job) is not None:
            if job.slot is not None:
                self._counters.write_failures += 1
                _LOGGER.warning("No read-back of the written CAN value %s", job.key)
            sent = request.written_at if job.write is not None else request.sent_at
            self._finish(job, Outcome(sent=sent is not None))
        if (slot := request.slot) is None:
            return
        slot.lost += 1
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
        counters = self._counters
        return {
            "requests": counters.requests,
            "unhandled_frames": counters.unhandled,
            "writes": counters.writes,
            "write_failures": counters.write_failures,
            "raw_frames": counters.raw,
            "queued": [job.key for job in self._jobs if not job.cancelled],
            "open_request": None
            if request is None
            else {
                "key": request.job.key
                if request.job is not None
                else request.slot.value.key
                if request.slot is not None
                else None,
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
