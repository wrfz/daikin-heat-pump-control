"""Bus side of the simulated bridge firmware.

The classes follow the rules of the real firmware: ring buffers for received
data, a send queue, and for CAN a frame is only sent after the bus was quiet
for `quiet_ms`. Time is virtual: everything that would have happened up to
the current time is evaluated when an action is called.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import heapq
import itertools
from typing import Any

from .heat_pump import CAN_OWN_ID, HeatPump, SimCanFrame

TIMESTAMP_MODULO = 1 << 32
MAX_FRAMES_PER_RESPONSE = 100


@dataclass(order=True, slots=True)
class _Event:
    time: int
    seq: int
    frame: SimCanFrame = field(compare=False)


class CanBridge:
    """CAN part of the bridge firmware attached to the simulated heat pump."""

    def __init__(
        self,
        heat_pump: HeatPump,
        clock_ms: Callable[[], int],
        *,
        rx_capacity: int = 256,
        tx_capacity: int = 16,
        quiet_ms: int = 250,
        answer_delay_ms: int = 15,
    ) -> None:
        """Initialize the bridge."""
        self.heat_pump = heat_pump
        self.clock_ms = clock_ms
        self.rx_capacity = rx_capacity
        self.tx_capacity = tx_capacity
        self.quiet_ms = quiet_ms
        self.answer_delay_ms = answer_delay_ms
        self.rx: deque[tuple[int, SimCanFrame]] = deque()
        self.tx_done: list[tuple[int, SimCanFrame]] = []
        self.tx_queue: deque[tuple[int, SimCanFrame]] = deque()
        self.overflows = 0
        self.dropped = 0
        self.bus_off = 0
        self.state = "error_active"
        self.tx_errors = 0
        self.rx_errors = 0
        self.arbitration_lost = 0
        self.sent: list[tuple[int, SimCanFrame]] = []
        self._events: list[_Event] = []
        self._seq = itertools.count()
        self._last_activity: int | None = None
        self._time = clock_ms()

    def inject(self, frame: SimCanFrame, delay_ms: int = 0) -> None:
        """Put a frame of another bus participant on the bus."""
        self._schedule(self.clock_ms() + delay_ms, frame)

    def _schedule(self, time: int, frame: SimCanFrame) -> None:
        heapq.heappush(self._events, _Event(time, next(self._seq), frame))

    def _next_tx_time(self) -> int | None:
        if not self.tx_queue:
            return None
        queued = self.tx_queue[0][0]
        if self._last_activity is None:
            return queued
        return max(queued, self._last_activity + self.quiet_ms)

    def advance(self, now: int | None = None) -> None:
        """Run everything that happens on the bus up to `now`."""
        now = self.clock_ms() if now is None else now
        while True:
            next_rx = self._events[0].time if self._events else None
            next_tx = self._next_tx_time()
            candidates = [t for t in (next_rx, next_tx) if t is not None and t <= now]
            if not candidates:
                break
            if next_rx is not None and next_rx == min(candidates):
                event = heapq.heappop(self._events)
                self._receive(event.time, event.frame)
                continue
            assert next_tx is not None
            _, frame = self.tx_queue.popleft()
            self._transmit(next_tx, frame)
        self._time = now

    def _receive(self, time: int, frame: SimCanFrame) -> None:
        self._last_activity = time
        if len(self.rx) >= self.rx_capacity:
            self.rx.popleft()
            self.overflows += 1
        self.rx.append((time, frame))
        if frame.can_id != CAN_OWN_ID:
            for answer in self.heat_pump.handle_can(frame):
                self._schedule(time + self.answer_delay_ms, answer)

    def _transmit(self, time: int, frame: SimCanFrame) -> None:
        self._last_activity = time
        self.tx_done.append((time, frame))
        self.sent.append((time, frame))
        for answer in self.heat_pump.handle_can(frame):
            self._schedule(time + self.answer_delay_ms, answer)

    def exchange(self, frames: list[str]) -> dict[str, Any]:
        """Run `daikin_can_exchange`."""
        now = self.clock_ms()
        self.advance(now)
        for text in frames:
            can_id, _, data = text.partition("#")
            if len(self.tx_queue) >= self.tx_capacity:
                self.dropped += 1
                continue
            self.tx_queue.append(
                (now, SimCanFrame(can_id=int(can_id, 16), data=bytes.fromhex(data)))
            )
        self.advance(now)
        count = min(len(self.rx), MAX_FRAMES_PER_RESPONSE)
        taken = [self.rx.popleft() for _ in range(count)]
        rx = [[t % TIMESTAMP_MODULO, f.can_id, f.data.hex().upper()] for t, f in taken]
        tx = [
            [t % TIMESTAMP_MODULO, f.can_id, f.data.hex().upper()]
            for t, f in self.tx_done
        ]
        self.tx_done.clear()
        return {
            "now": now % TIMESTAMP_MODULO,
            "rx": rx,
            "tx": tx,
            "more": bool(self.rx),
            "pending": len(self.tx_queue),
            "overflows": self.overflows,
            "dropped": self.dropped,
        }

    def status(self) -> dict[str, Any]:
        """Return the CAN part of `daikin_bridge_info`."""
        return {
            "buffer": self.rx_capacity,
            "overflows": self.overflows,
            "state": self.state,
            "tx_errors": self.tx_errors,
            "rx_errors": self.rx_errors,
            "arbitration_lost": self.arbitration_lost,
            "bus_off": self.bus_off,
        }


class UartBridge:
    """UART part of the bridge firmware attached to the simulated heat pump."""

    def __init__(
        self,
        heat_pump: HeatPump,
        clock_ms: Callable[[], int],
        *,
        capacity: int = 1024,
        answer_delay_ms: int = 40,
        chunk_size: int = 7,
        chunk_interval_ms: int = 10,
    ) -> None:
        """Initialize the bridge."""
        self.heat_pump = heat_pump
        self.clock_ms = clock_ms
        self.capacity = capacity
        self.answer_delay_ms = answer_delay_ms
        self.chunk_size = chunk_size
        self.chunk_interval_ms = chunk_interval_ms
        self.overflows = 0
        self.rx = bytearray()
        self.rx_time: int | None = None
        self.requests: list[bytes] = []
        self._incoming: list[tuple[int, bytes]] = []
        self._tx_buffer = b""
        self._last_tx: int | None = None

    def advance(self, now: int | None = None) -> None:
        """Deliver the bytes that arrived up to `now`."""
        now = self.clock_ms() if now is None else now
        due = [item for item in self._incoming if item[0] <= now]
        self._incoming = [item for item in self._incoming if item[0] > now]
        for time, chunk in sorted(due):
            if self.rx_time is None:
                self.rx_time = time
            for byte in chunk:
                if len(self.rx) >= self.capacity:
                    del self.rx[0]
                    self.overflows += 1
                self.rx.append(byte)

    def _request_length(self) -> int | None:
        buffer = self._tx_buffer
        if not buffer:
            return None
        if buffer[0] == 0x03:
            return 4
        if buffer[0] == 0x02:
            return 3
        return len(buffer)

    def exchange(self, data: str) -> dict[str, Any]:
        """Run `daikin_uart_exchange`."""
        now = self.clock_ms()
        self.advance(now)
        sent_at = None
        if data:
            sent_at = now
            self._last_tx = now
            self._tx_buffer += bytes.fromhex(data)
            while (length := self._request_length()) is not None and len(
                self._tx_buffer
            ) >= length:
                request, self._tx_buffer = (
                    self._tx_buffer[:length],
                    self._tx_buffer[length:],
                )
                self.requests.append(request)
                answer = self.heat_pump.handle_uart(request)
                start = now + self.answer_delay_ms
                for index in range(0, len(answer), self.chunk_size):
                    self._incoming.append(
                        (
                            start + (index // self.chunk_size) * self.chunk_interval_ms,
                            answer[index : index + self.chunk_size],
                        )
                    )
        rx, rx_time = bytes(self.rx), self.rx_time
        self.rx.clear()
        self.rx_time = None
        result: dict[str, Any] = {
            "now": now % TIMESTAMP_MODULO,
            "rx": rx.hex().upper(),
            "overflows": self.overflows,
        }
        if rx_time is not None:
            result["rx_t"] = rx_time % TIMESTAMP_MODULO
        if sent_at is not None:
            result["tx_t"] = sent_at % TIMESTAMP_MODULO
        return result

    def status(self) -> dict[str, Any]:
        """Return the UART part of `daikin_bridge_info`."""
        return {"buffer": self.capacity, "overflows": self.overflows}
