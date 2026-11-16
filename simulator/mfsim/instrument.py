"""Base class of the three virtual instruments: SCPI dispatch, common commands, fault hooks."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from . import __version__
from .bench import Bench
from .faults import KINDS, FaultInjector
from .scpi import (EXECUTION, SYNTAX, UNDEFINED_HEADER, Command, CommandTable,
                   ErrorQueue, ParsedLine, ScpiError, format_number, parse_integer, parse_line,
                   parse_number)

log = logging.getLogger("mfsim")

_FAULT_COUNT_MAX = 1_000_000


@dataclass(frozen=True)
class Reply:
    """What the transport must do after a command line.

    Attributes:
        payload: bytes to send (response line including ``\\n``), or None for no response.
        delay_s: stay silent this long before sending (``TIMEOUT`` fault).
        disconnect: close the connection instead of answering (``DISCONNECT`` fault).
        chunk_size / chunk_delay_s: send ``payload`` in chunks of this size, pausing between them
            (``FRAGMENT`` fault); 0 sends it in one piece.
    """

    payload: bytes | None = None
    delay_s: float = 0.0
    disconnect: bool = False
    chunk_size: int = 0
    chunk_delay_s: float = 0.0


class Instrument(ABC):
    """A SCPI instrument attached to the shared :class:`Bench`.

    Subclasses set ``MODEL``/``SERIAL``, register their commands in :meth:`register` and restore
    their own defaults in :meth:`reset_state`.
    """

    MODEL = ""
    SERIAL = ""
    FIRMWARE = "1.0.0"

    def __init__(self, bench: Bench) -> None:
        self.bench = bench
        self.errors = ErrorQueue()
        self.faults = FaultInjector()
        self.table = CommandTable()
        self._register_common()
        self.register()

    # -- to be provided by subclasses ----------------------------------------------------
    @abstractmethod
    def register(self) -> None:
        """Add the instrument-specific commands to :attr:`table`."""

    @abstractmethod
    def reset_state(self) -> None:
        """Restore this instrument's part of the bench to its ``*RST`` defaults."""

    def firmware(self) -> str:
        """Firmware version reported by ``*IDN?``."""
        return self.FIRMWARE

    # -- command helpers -------------------------------------------------------------------
    def number_command(self, header: str, read: Callable[[], float], write: Callable[[float], None],
                       low: float, high: float) -> Command:
        """A numeric setter/query pair; every successful write drops the stored acquisition."""
        def setter(args: tuple[str, ...]) -> None:
            write(parse_number(args[0], low, high))
            self.bench.invalidate()

        return Command(header, setter, lambda _args: format_number(read()))

    # -- common commands -------------------------------------------------------------------
    def _register_common(self) -> None:
        add = self.table.add
        add(Command("*IDN", getter=lambda _a: f"MeasureFlow,{self.MODEL},{self.SERIAL},{self.firmware()}"))
        add(Command("*RST", setter=self._reset, set_args=(0, 0)))
        add(Command("*CLS", setter=lambda _a: self.errors.clear(), set_args=(0, 0)))
        add(Command("*OPC", setter=lambda _a: None, getter=lambda _a: "1", set_args=(0, 0)))
        add(Command("*TST", getter=lambda _a: "0"))
        add(Command("SYSTem:ERRor", getter=lambda _a: self.errors.pop()))
        add(Command("SYSTem:VERSion", getter=lambda _a: "1999.0"))
        add(Command("MF:SIMulator:VERSion", getter=lambda _a: __version__))
        add(Command("MF:FAULT", getter=lambda _a: self.faults.status()))
        add(Command("MF:FAULT:CLEAR", setter=lambda _a: self.faults.clear(), set_args=(0, 0)))
        for kind in KINDS:
            add(Command(f"MF:FAULT:{kind}", setter=partial(self._arm_fault, kind),
                        set_args={"TIMEOUT": (1, 2), "FRAGMENT": (1, 3)}.get(kind, (1, 1))))

    def _reset(self, _args: tuple[str, ...]) -> None:
        """``*RST``: instrument defaults, no armed faults, default seed, counter 0, no stored buffer."""
        self.reset_state()
        self.faults.clear()
        self.bench.reset_acquisition_state()

    def _arm_fault(self, kind: str, args: tuple[str, ...]) -> None:
        count = parse_integer(args[0], 0, _FAULT_COUNT_MAX)
        if kind == "TIMEOUT":
            delay = parse_number(args[1], 0.0, 600_000.0) if len(args) > 1 else None
            self.faults.arm(kind, count, timeout_ms=delay)
        elif kind == "FRAGMENT":
            chunk = parse_integer(args[1], 1, 65_536) if len(args) > 1 else None
            delay = parse_number(args[2], 0.0, 60_000.0) if len(args) > 2 else None
            self.faults.arm(kind, count, chunk=chunk, chunk_delay_ms=delay)
        else:
            self.faults.arm(kind, count)

    # -- line processing -------------------------------------------------------------------
    def handle(self, line: str) -> Reply:
        """Process one input line (terminator already removed) and describe the reaction.

        Invalid lines only push errors on the queue and produce no response.  Syntactically valid
        lines (except ``MF:FAULT*``) pass through the fault injector.
        """
        text = line.strip()
        if not text:
            return Reply()
        try:
            parsed = parse_line(text)
        except ScpiError as error:
            self.errors.push(error.code)
            return Reply()
        exempt = parsed.nodes[:2] == ("MF", "FAULT")
        delay_s = 0.0
        if not exempt:
            fault = self.faults.on_command()
            if fault.disconnect:
                return Reply(disconnect=True)
            delay_s = fault.delay_s
        response = self._execute(parsed)
        if response is None:
            return Reply(delay_s=delay_s)
        if exempt:
            return Reply((response + "\n").encode("ascii"), delay_s)
        shaped = self.faults.on_response(response)
        return Reply((shaped.text + "\n").encode("ascii"), delay_s, False,
                     shaped.chunk_size, shaped.chunk_delay_s)

    def _execute(self, parsed: ParsedLine) -> str | None:
        try:
            with self.bench.lock:
                return self._dispatch(parsed)
        except ScpiError as error:
            self.errors.push(error.code)
        except Exception:  # noqa: BLE001 - a handler bug must never kill the connection thread
            log.exception("handler failure for %s", ":".join(parsed.nodes))
            self.errors.push(EXECUTION)
        return None

    def _dispatch(self, parsed: ParsedLine) -> str | None:
        command = self.table.lookup(parsed.nodes)
        if command is None:
            raise ScpiError(UNDEFINED_HEADER)
        if parsed.query:
            if command.getter is None:
                raise ScpiError(UNDEFINED_HEADER)
            self._check_arity(parsed.args, command.get_args)
            return command.getter(parsed.args)
        if command.setter is None:
            raise ScpiError(UNDEFINED_HEADER)
        self._check_arity(parsed.args, command.set_args)
        command.setter(parsed.args)
        return None

    @staticmethod
    def _check_arity(args: tuple[str, ...], bounds: tuple[int, int]) -> None:
        if not bounds[0] <= len(args) <= bounds[1]:
            raise ScpiError(SYNTAX)
