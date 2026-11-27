"""Bus side of the simulated bridge firmware.

The classes follow the rules of the real firmware: ring buffers for received
data shared by all clients, each client with its own read position, a send
queue, and for CAN a frame is only sent after the bus was quiet for
`quiet_ms`. Only the master sends. Time is virtual: everything that would
have happened up to the current time is evaluated when an action is called.
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
MAX_UART_BYTES_PER_RESPONSE = 1024
MAX_UART_PIECES_PER_RESPONSE = 32
MAX_UART_PIECES = 64
DEFAULT_CLIENT = "sim"


class _Readers:
    """Read positions and missed entries of the clients of one shared buffer."""

    def __init__(self) -> None:
        self.cursors: dict[str, int] = {}
        self.overflows: dict[str, int] = {}

    def register(self, client: str, end: int) -> None:
        self.cursors[client] = end
        self.overflows[client] = 0

    def forget(self, client: str) -> None:
        self.cursors.pop(client, None)
        self.overflows.pop(client, None)

    def catch_up(self, client: str, begin: int, end: int) -> int:
        """Return the read position of a client after it missed dropped entries."""
        if client not in self.cursors:
            self.register(client, end)
        if self.cursors[client] < begin:
            self.overflows[client] += begin - self.cursors[client]
            self.cursors[client] = begin
        return self.cursors[client]


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
        self.rx_end = 0
        self.readers = _Readers()
        self.tx_done: list[tuple[int, SimCanFrame]] = []
        self.tx_queue: deque[tuple[int, SimCanFrame]] = deque()
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

    @property
    def overflows(self) -> int:
        """Return the frames the default client missed."""
        return self.readers.overflows.get(DEFAULT_CLIENT, 0)

    def register(self, client: str) -> None:
        """Start a client at the current end of the buffer."""
        self.readers.register(client, self.rx_end)

    def forget(self, client: str) -> None:
        """Remove a client that is gone."""
        self.readers.forget(client)

    def master_changed(self) -> None:
        """Drop the frames of the previous master."""
        self.tx_queue.clear()
        self.tx_done.clear()

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
        self.rx.append((time, frame))
        self.rx_end += 1
        if frame.can_id != CAN_OWN_ID:
            for answer in self.heat_pump.handle_can(frame):
                self._schedule(time + self.answer_delay_ms, answer)

    def _transmit(self, time: int, frame: SimCanFrame) -> None:
        self._last_activity = time
        self.tx_done.append((time, frame))
        self.sent.append((time, frame))
        for answer in self.heat_pump.handle_can(frame):
            self._schedule(time + self.answer_delay_ms, answer)

    def exchange(
        self,
        frames: list[str],
        client: str = DEFAULT_CLIENT,
        *,
        master: bool = True,
    ) -> dict[str, Any]:
        """Run `daikin_can_exchange` for a client.

        Returns the rx/tx part; the client fields are added by the node.
        """
        now = self.clock_ms()
        self.advance(now)
        rejected = 0
        for text in frames:
            if not master:
                rejected += 1
                continue
            can_id, _, data = text.partition("#")
            if len(self.tx_queue) >= self.tx_capacity:
                self.dropped += 1
                continue
            self.tx_queue.append(
                (now, SimCanFrame(can_id=int(can_id, 16), data=bytes.fromhex(data)))
            )
        self.advance(now)
        begin = self.rx_end - len(self.rx)
        cursor = self.readers.catch_up(client, begin, self.rx_end)
        count = min(self.rx_end - cursor, MAX_FRAMES_PER_RESPONSE)
        taken = [self.rx[cursor - begin + i] for i in range(count)]
        self.readers.cursors[client] = cursor + count
        rx = [[t % TIMESTAMP_MODULO, f.can_id, f.data.hex().upper()] for t, f in taken]
        tx: list[list[Any]] = []
        if master:
            tx = [
                [t % TIMESTAMP_MODULO, f.can_id, f.data.hex().upper()]
                for t, f in self.tx_done
            ]
            self.tx_done.clear()
        return {
            "now": now % TIMESTAMP_MODULO,
            "rx": rx,
            "tx": tx,
            "more": cursor + count < self.rx_end,
            "pending": len(self.tx_queue) if master else 0,
            "overflows": self.readers.overflows[client],
            "dropped": self.dropped,
            "rejected": rejected,
        }

    def status(self) -> dict[str, Any]:
        """Return the CAN part of `daikin_bridge_info`."""
        return {
            "buffer": self.rx_capacity,
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
        self.rx = bytearray()
        self.rx_end = 0
        self.readers = _Readers()
        # Start of each run of bytes: (sequence, time of the first byte, fresh).
        self.pieces: deque[tuple[int, int, bool]] = deque()
        self.requests: list[bytes] = []
        self._incoming: list[tuple[int, bytes]] = []
        self._tx_buffer = b""
        self._sent = False

    @property
    def overflows(self) -> int:
        """Return the bytes the default client missed."""
        return self.readers.overflows.get(DEFAULT_CLIENT, 0)

    def register(self, client: str) -> None:
        """Start a client at the current end of the buffer."""
        self.readers.register(client, self.rx_end)

    def forget(self, client: str) -> None:
        """Remove a client that is gone."""
        self.readers.forget(client)

    def master_changed(self) -> None:
        """Start a fresh piece with the next byte."""
        self._sent = True

    def advance(self, now: int | None = None) -> None:
        """Deliver the bytes that arrived up to `now`."""
        now = self.clock_ms() if now is None else now
        due = [item for item in self._incoming if item[0] <= now]
        self._incoming = [item for item in self._incoming if item[0] > now]
        for time, chunk in sorted(due):
            for byte in chunk:
                if not self.pieces or self._sent:
                    self.pieces.append((self.rx_end, time, self._sent))
                    self._sent = False
                if len(self.rx) >= self.capacity:
                    del self.rx[0]
                self.rx.append(byte)
                self.rx_end += 1
        begin = self.rx_end - len(self.rx)
        while len(self.pieces) > 1 and (
            self.pieces[1][0] <= begin or len(self.pieces) > MAX_UART_PIECES
        ):
            self.pieces.popleft()

    def _request_length(self) -> int | None:
        buffer = self._tx_buffer
        if not buffer:
            return None
        if buffer[0] == 0x03:
            return 4
        if buffer[0] == 0x02:
            return 3
        return len(buffer)

    def _send(self, now: int, data: bytes) -> None:
        self._sent = True
        self._tx_buffer += data
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

    def exchange(
        self, data: str, client: str = DEFAULT_CLIENT, *, master: bool = True
    ) -> dict[str, Any]:
        """Run `daikin_uart_exchange` for a client."""
        now = self.clock_ms()
        self.advance(now)
        result: dict[str, Any] = {"now": now % TIMESTAMP_MODULO, "rejected": 0}
        if data and master:
            self._send(now, bytes.fromhex(data))
            result["tx_t"] = now % TIMESTAMP_MODULO
        elif data:
            result["rejected"] = 1
        begin = self.rx_end - len(self.rx)
        cursor = self.readers.catch_up(client, begin, self.rx_end)
        rx: list[list[Any]] = []
        taken = 0
        pieces = list(self.pieces)
        for index, (start, time, fresh) in enumerate(pieces):
            end = pieces[index + 1][0] if index + 1 < len(pieces) else self.rx_end
            if end <= cursor:
                continue
            if (
                taken >= MAX_UART_BYTES_PER_RESPONSE
                or len(rx) >= MAX_UART_PIECES_PER_RESPONSE
            ):
                break
            first = cursor if index == 0 else max(cursor, start)
            last = min(end, first + MAX_UART_BYTES_PER_RESPONSE - taken)
            chunk = bytes(self.rx[first - begin : last - begin])
            rx.append(
                [time % TIMESTAMP_MODULO, chunk.hex().upper(), fresh and first == start]
            )
            taken += last - first
            cursor = last
        self.readers.cursors[client] = cursor
        result["rx"] = rx
        result["more"] = cursor < self.rx_end
        result["overflows"] = self.readers.overflows[client]
        return result

    def status(self) -> dict[str, Any]:
        """Return the UART part of `daikin_bridge_info`."""
        return {"buffer": self.capacity}
