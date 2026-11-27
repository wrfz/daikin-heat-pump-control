"""State of the UART values and their distribution to the entities."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import logging
from typing import Any, Final

from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .bridge.node import UartChannel
from .bridge.protocol import UartExchangeResult
from .const import DOMAIN, UartProtocol
from .logic.derived import DERIVED, Derived
from .logic.refrigerant import (
    CIRCUIT_TRIGGERS,
    DISCHARGE,
    INPUTS as CIRCUIT_INPUTS,
    LIQUID,
    SATURATION,
    STATE_TRIGGERS,
    SUBCOOLING,
    SUPERHEAT,
    CircuitValues,
    RefrigerantCircuit,
)
from .logic.smoothing import Smoother
from .uart.protocol import (
    I_PROBE_REGISTER,
    Detection,
    EventKind,
    Frame,
    FrameParser,
    Protocol,
    ProtocolDetector,
)
from .uart.scheduler import FAILED_INTERVAL_MS, UartScheduler
from .uart.table import (
    ActiveValue,
    OutdoorUnit,
    StateValue,
    Status,
    decode,
    unit_values,
)

_LOGGER = logging.getLogger(__name__)

# Poll the bridge this often while an answer is expected.
ANSWER_POLL_INTERVAL: Final = 0.1

TEMPERATURE_SPREAD: Final = "temperature_spread"
THERMAL_POWER: Final = "thermal_power"

type UartState = StateValue


@dataclass(frozen=True, slots=True, kw_only=True)
class Computed:
    """A value computed from table values."""

    key: str
    inputs: tuple[str, ...]
    raw: bool = False


# Computed entities and the table values they need.
COMPUTED: Final[tuple[Computed, ...]] = (
    Computed(key="thermal_power", inputs=("tv", "tr", "flow_rate")),
    Computed(key="thermal_power_raw", inputs=("tv", "tr", "flow_rate"), raw=True),
    Computed(key="temperature_spread", inputs=("tv", "tr")),
    Computed(key="temperature_spread_raw", inputs=("tv", "tr"), raw=True),
    Computed(key=SUBCOOLING, inputs=(SATURATION, LIQUID)),
    Computed(key=SUPERHEAT, inputs=(SATURATION, DISCHARGE)),
)
_DERIVED: Final[dict[str, Derived]] = {
    derived.smoothed: derived
    for derived in DERIVED
    if derived.smoothed in (THERMAL_POWER, TEMPERATURE_SPREAD)
}


def resolve_protocol(
    option: str | None, detected: str | None
) -> tuple[Protocol | None, bool]:
    """Return the protocol to use and whether it may be detected again."""
    if option in (UartProtocol.I, UartProtocol.S):
        return Protocol(option), False
    if detected in (Protocol.I, Protocol.S):
        return Protocol(detected), True
    return None, True


def uart_entities(unit: OutdoorUnit, protocol: Protocol | None) -> dict[str, bool]:
    """Return the key of every UART entity and whether it is enabled by default.

    Without a known protocol there are no entities.
    """
    if protocol is None:
        return {}
    values = unit_values(unit, protocol)
    entities = {key: value.status is Status.CONFIRMED for key, value in values.items()}
    for computed in COMPUTED:
        if all(key in values for key in computed.inputs):
            entities[computed.key] = not computed.raw and all(
                entities[key] for key in computed.inputs
            )
    return entities


def needed_values(values: dict[str, ActiveValue], active: Iterable[str]) -> set[str]:
    """Return the table keys to poll for the given active entity keys."""
    active = set(active)
    needed = {key for key in active if key in values}
    for computed in COMPUTED:
        if computed.key in active:
            needed.update(computed.inputs)
            if computed.key in (SUBCOOLING, SUPERHEAT):
                needed.update(CIRCUIT_INPUTS)
    return {key for key in needed if key in values}


class UartCoordinator:
    """Poll the indoor unit over a bridge channel and keep the states."""

    def __init__(
        self,
        hass: HomeAssistant,
        channel: UartChannel,
        *,
        unit: OutdoorUnit,
        protocol: Protocol | None,
        may_detect: bool,
        active: Iterable[str],
        on_detected: Callable[[Protocol], None],
    ) -> None:
        """Initialize the coordinator.

        `protocol` None means the protocol is detected first; `on_detected`
        is called when a detection finds another protocol than `protocol`.
        """
        self.hass = hass
        self.channel = channel
        self.unit = unit
        self.protocol = protocol
        self.may_detect = may_detect
        self._on_detected = on_detected
        self.values = unit_values(unit, protocol) if protocol else {}
        active = set(active)
        needed = needed_values(self.values, active)
        self._polled = {
            key: value for key, value in self.values.items() if key in needed
        }
        self._by_register: dict[int, list[ActiveValue]] = defaultdict(list)
        for value in self._polled.values():
            self._by_register[value.layout.register].append(value)
        self._detector = ProtocolDetector()
        self._detecting = False
        self._fallback = False
        self._halted = False
        self._last_detection: int | None = None
        self.detections: list[dict[str, Any]] = []
        self.parser = FrameParser(protocol or Protocol.I)
        self.scheduler = self._new_scheduler()
        self._derived = [
            _DERIVED[computed.key]
            for computed in COMPUTED
            if computed.key in _DERIVED
            and (computed.key in active or f"{computed.key}_raw" in active)
            and all(key in self.values for key in computed.inputs)
        ]
        self._smoothers: dict[str, Smoother] = {
            derived.smoothed: Smoother()
            for derived in self._derived
            if derived.smoothed is not None and derived.smoothed in active
        }
        self._circuit: RefrigerantCircuit | None = None
        if active & {SUBCOOLING, SUPERHEAT} and SATURATION in self._polled:
            self._circuit = RefrigerantCircuit(self._polled)
        self._states: dict[str, UartState] = {}
        self._raw: dict[str, str] = {}
        self._short_payload_logged: set[str] = set()
        self._listeners: dict[str, list[CALLBACK_TYPE]] = defaultdict(list)
        self._available = channel.available
        self._unsub_answer_poll: CALLBACK_TYPE | None = None

    def _new_scheduler(self) -> UartScheduler:
        if self.protocol is None:
            # Until a protocol is known, an I answer to 0x60 also counts.
            return UartScheduler(Protocol.I, [I_PROBE_REGISTER])
        return UartScheduler(
            self.protocol, (value.layout.register for value in self._polled.values())
        )

    @property
    def available(self) -> bool:
        """Return True while the bus can be used."""
        return self.channel.available

    def value_available(self, key: str) -> bool:
        """Return True unless the register of a table value does not answer."""
        value = self.values.get(key)
        return value is None or not self.scheduler.is_failed(value.layout.register)

    def state(self, key: str) -> UartState:
        """Return the current state of a value."""
        return self._states.get(key)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Follow the exchanges and the availability of the channel."""
        unsub_result = self.channel.async_add_listener(self._handle_result)
        unsub_node = self.channel.node.async_add_listener(self._handle_node)

        @callback
        def _stop() -> None:
            unsub_result()
            unsub_node()
            self._cancel_answer_poll()

        return _stop

    @callback
    def async_add_listener(self, key: str, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a listener for changes of a value."""
        self._listeners[key].append(listener)

        @callback
        def _remove() -> None:
            self._listeners[key].remove(listener)

        return _remove

    @callback
    def _notify(self, keys: Iterable[str]) -> None:
        for key in keys:
            for listener in list(self._listeners.get(key, ())):
                listener()

    @callback
    def _handle_node(self) -> None:
        available = self.channel.available
        if available == self._available:
            return
        self._available = available
        if not available:
            self._reset()
        self._notify(list(self._listeners))

    def _reset(self) -> None:
        self._cancel_answer_poll()
        self.scheduler.reset()
        self.parser.clear()
        self._detecting = False
        self._states.clear()
        self._raw.clear()
        for smoother in self._smoothers.values():
            smoother.reset()
        if self._circuit is not None:
            self._circuit.reset()

    # ------------------------------------------------------------ exchange

    def is_halted(self) -> bool:
        """Return True once a detected protocol change waits for the reload."""
        return self._halted

    @callback
    def _handle_result(self, result: UartExchangeResult) -> None:
        if self.is_halted():
            return
        clock = self.channel.clock
        now = clock.extend(result.now)
        changed: set[str] = set()
        if result.sent_at is not None:
            sent_at = clock.extend(result.sent_at)
            if self._detecting:
                self._detector.sent(sent_at)
            else:
                self.scheduler.handle_sent(sent_at)
        received_at = (
            clock.extend(result.received_at) if result.received_at is not None else now
        )
        if self._detecting:
            self._run_detection(now, result.received)
        else:
            self._handle_bytes(received_at, result.received, changed)
            changed.update(self._register_keys(self.scheduler.check_timeout(now)))
        if self.is_halted():
            return
        for key, smoother in self._smoothers.items():
            if smoother.update(now / 1000):
                self._set(key, smoother.value, changed)
        self._notify(changed)
        if not self.channel.available:
            return
        if not self._detecting and self._should_detect(now):
            self._start_detection(now)
        elif not self._detecting and (request := self.scheduler.next_request(now)):
            self.channel.async_send(request)
        if self._detecting or self.scheduler.open is not None:
            self._schedule_answer_poll()

    def _register_keys(self, register: int | None) -> set[str]:
        if register is None:
            return set()
        return {value.key for value in self._by_register.get(register, ())}

    @callback
    def _schedule_answer_poll(self) -> None:
        if self._unsub_answer_poll is not None:
            return

        @callback
        def _poll(_now: Any) -> None:
            self._unsub_answer_poll = None
            self.channel.async_request_exchange()

        self._unsub_answer_poll = async_call_later(
            self.hass,
            ANSWER_POLL_INTERVAL,
            HassJob(_poll, f"{DOMAIN} UART answer poll", cancel_on_shutdown=True),
        )

    @callback
    def _cancel_answer_poll(self) -> None:
        if self._unsub_answer_poll is not None:
            self._unsub_answer_poll()
            self._unsub_answer_poll = None

    def _handle_bytes(self, timestamp: int, data: bytes, changed: set[str]) -> None:
        if not data:
            return
        for event in self.parser.feed(data):
            match event.kind:
                case EventKind.NAK:
                    changed.update(self._register_keys(self.scheduler.handle_failure()))
                case EventKind.INVALID:
                    _LOGGER.debug("Dropped UART bytes %s", event.data.hex(" ").upper())
                case EventKind.FRAME:
                    assert event.frame is not None
                    self._handle_frame(timestamp, event.frame, changed)
                    if self.is_halted():
                        return

    def _handle_frame(self, timestamp: int, frame: Frame, changed: set[str]) -> None:
        if not frame.checksum_ok:
            _LOGGER.debug(
                "UART frame with wrong checksum used: %s", frame.raw.hex(" ").upper()
            )
        if self.scheduler.handle_frame(timestamp, frame):
            changed.update(self._register_keys(frame.register))
        if self.protocol is None:
            _LOGGER.info("UART protocol I confirmed by an answer")
            self._detected(Protocol.I)
            return
        decoded: set[str] = set()
        for active in self._by_register.get(frame.register, ()):
            if not active.layout.fits(frame.payload):
                if active.key not in self._short_payload_logged:
                    self._short_payload_logged.add(active.key)
                    _LOGGER.warning(
                        "UART register 0x%02X has %d payload bytes; %s is not in it",
                        frame.register,
                        len(frame.payload),
                        active.key,
                    )
                continue
            self._raw[active.key] = frame.raw.hex().upper()
            state = decode(active.value, active.layout, frame.payload, self.unit)
            self._set(active.key, state, changed)
            decoded.add(active.key)
        self._update_circuit(decoded, changed)

    def _set(self, key: str, state: UartState, changed: set[str]) -> None:
        if key in self._states and self._states[key] == state:
            return
        self._states[key] = state
        changed.add(key)
        for derived in self._derived:
            if key in derived.inputs:
                value = derived.compute(self._states)
                self._set(derived.key, value, changed)
                if derived.smoothed in self._smoothers:
                    self._smoothers[derived.smoothed].set_raw(value)

    def _update_circuit(self, decoded: set[str], changed: set[str]) -> None:
        circuit = self._circuit
        if circuit is None:
            return
        result: CircuitValues | None = None
        if decoded & CIRCUIT_TRIGGERS:
            result = circuit.update_circuit(self._states)
        elif decoded & STATE_TRIGGERS:
            result = circuit.update_state(self._states)
        if result is not None:
            self._set(SUBCOOLING, result.subcooling, changed)
            self._set(SUPERHEAT, result.superheat, changed)

    # ----------------------------------------------------------- detection

    def _should_detect(self, now: int) -> bool:
        if not self.may_detect:
            return False
        if self.protocol is None and self._last_detection is None:
            return True
        if not self.scheduler.all_failed:
            return False
        return (
            self._last_detection is None
            or now - self._last_detection >= FAILED_INTERVAL_MS
        )

    def _start_detection(self, now: int) -> None:
        self._detecting = True
        self._last_detection = now
        self.scheduler.open = None
        self.parser.clear()
        self.channel.async_send(self._detector.start(now))

    def _run_detection(self, now: int, data: bytes) -> None:
        detection = self._detector.feed(data) if data else None
        if detection is None:
            probe, detection = self._detector.check_timeout(now)
            if probe is not None:
                self.channel.async_send(probe)
        if detection is not None:
            self._detection_done(now, detection)

    def _detection_done(self, now: int, detection: Detection) -> None:
        self._detecting = False
        self.detections.append({"at": now, "protocol": detection.protocol})
        del self.detections[:-5]
        if detection.protocol is None:
            if self.protocol is None:
                _LOGGER.info("No answer to the UART protocol detection; trying I")
            else:
                _LOGGER.debug("No answer to the UART protocol detection")
            return
        if detection.protocol is self.protocol:
            _LOGGER.debug("UART protocol %s detected again", detection.protocol)
            self.scheduler.retry_failed()
            return
        self._detected(detection.protocol)

    def _detected(self, protocol: Protocol) -> None:
        if self.protocol is None:
            _LOGGER.info("UART protocol %s detected", protocol.upper())
        else:
            _LOGGER.warning(
                "The indoor unit no longer answers in UART protocol %s but in %s",
                self.protocol.upper(),
                protocol.upper(),
            )
        self._halted = True
        self._cancel_answer_poll()
        self._on_detected(protocol)

    # ---------------------------------------------------------- diagnostics

    def diagnostics(self) -> dict[str, Any]:
        """Return the values, the protocol and the polling state."""
        return {
            "available": self.available,
            "outdoor_unit": self.unit.model,
            "protocol": self.protocol,
            "may_detect": self.may_detect,
            "detecting": self._detecting,
            "detections": list(self.detections),
            "values": {
                key: {"state": state, "frame": self._raw.get(key)}
                for key, state in sorted(self._states.items())
            },
            "polled": sorted(self._polled),
            "pending_bytes": self.parser.pending.hex().upper(),
            "scheduler": self.scheduler.diagnostics(),
        }
