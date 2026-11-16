"""SCPI text layer: error queue, line parsing, command table and argument helpers."""

from __future__ import annotations

import math
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np

MAX_LINE_BYTES = 4096

ERROR_TEXT: dict[int, str] = {
    -102: "Syntax error",
    -104: "Data type error",
    -113: "Undefined header",
    -200: "Execution error",
    -221: "Settings conflict",
    -222: "Data out of range",
    -224: "Illegal parameter value",
    -230: "Data corrupt or stale",
    -350: "Queue overflow",
}

SYNTAX = -102
DATA_TYPE = -104
UNDEFINED_HEADER = -113
EXECUTION = -200
SETTINGS_CONFLICT = -221
OUT_OF_RANGE = -222
ILLEGAL_VALUE = -224
DATA_CORRUPT = -230
QUEUE_OVERFLOW = -350


class ScpiError(Exception):
    """Raised by a handler; the dispatcher pushes ``code`` on the error queue and sends nothing."""

    def __init__(self, code: int) -> None:
        super().__init__(ERROR_TEXT.get(code, "Unknown error"))
        self.code = code


class ErrorQueue:
    """FIFO of SCPI errors, oldest first, thread-safe.

    Holds 20 entries.  When full, the newest entry is replaced by ``-350 Queue overflow`` and
    further errors are dropped until the queue is read.
    """

    CAPACITY = 20

    def __init__(self) -> None:
        self._items: deque[int] = deque()
        self._lock = threading.Lock()

    def push(self, code: int) -> None:
        """Append an error code."""
        with self._lock:
            if len(self._items) >= self.CAPACITY:
                self._items[-1] = QUEUE_OVERFLOW
            else:
                self._items.append(code)

    def pop(self) -> str:
        """Oldest error as ``<code>,"<message>"``, or ``0,"No error"`` when empty."""
        with self._lock:
            code = self._items.popleft() if self._items else 0
        return f'{code},"{ERROR_TEXT.get(code, "No error")}"'

    def clear(self) -> None:
        """Drop all queued errors (``*CLS``)."""
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# --------------------------------------------------------------------------------------------
# Line parsing
# --------------------------------------------------------------------------------------------
_PRINTABLE_RE = re.compile(r"[\x20-\x7e\t]*")
_LINE_RE = re.compile(
    r"^:?(\*[A-Za-z]+|[A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)*)(\?)?(?:[ \t]+(.*))?$")


@dataclass(frozen=True)
class ParsedLine:
    """A syntactically valid command line.

    Attributes:
        nodes: upper-case header mnemonics, e.g. ``("SOUR", "FREQ")``.
        query: True if the header ended in ``?``.
        args: comma-separated arguments, stripped.
    """

    nodes: tuple[str, ...]
    query: bool
    args: tuple[str, ...]


def parse_line(text: str) -> ParsedLine:
    """Split one command line into header nodes and arguments.

    Raises:
        ScpiError: -102 for non-printable or non-ASCII characters (tab is allowed), a malformed
            header or an empty argument.
    """
    if _PRINTABLE_RE.fullmatch(text) is None:
        raise ScpiError(SYNTAX)
    match = _LINE_RE.match(text)
    if match is None:
        raise ScpiError(SYNTAX)
    header, question, arg_text = match.groups()
    args: tuple[str, ...] = ()
    if arg_text is not None and arg_text.strip():
        args = tuple(part.strip() for part in arg_text.split(","))
        if any(not part for part in args):
            raise ScpiError(SYNTAX)
    return ParsedLine(tuple(header.upper().split(":")), question is not None, args)


# --------------------------------------------------------------------------------------------
# Command table
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Command:
    """One SCPI command.

    ``header`` uses the SCPI notation in which the upper-case prefix of every mnemonic is its
    short form (``SOURce:FREQuency`` accepts ``SOUR:FREQ``, ``SOURCE:FREQUENCY`` and mixed forms).

    Attributes:
        setter: called with the arguments of a non-query line; returns nothing.
        getter: called with the arguments of a query; returns the response text.
        set_args / get_args: inclusive ``(min, max)`` argument counts.
    """

    header: str
    setter: Callable[[tuple[str, ...]], None] | None = None
    getter: Callable[[tuple[str, ...]], str] | None = None
    set_args: tuple[int, int] = (1, 1)
    get_args: tuple[int, int] = (0, 0)


@dataclass
class _Node:
    children: dict[str, _Node] = field(default_factory=dict)
    command: Command | None = None


def _forms(mnemonic: str) -> tuple[str, str]:
    short = re.match(r"[A-Z0-9_*]+", mnemonic)
    return (short.group(0) if short else mnemonic).upper(), mnemonic.upper()


class CommandTable:
    """Trie of mnemonics; every short/long spelling of a node leads to the same child."""

    def __init__(self) -> None:
        self._root = _Node()

    def add(self, command: Command) -> None:
        """Register ``command``."""
        node = self._root
        for mnemonic in command.header.split(":"):
            short, long = _forms(mnemonic)
            child = node.children.get(short) or node.children.get(long)
            if child is None:
                child = _Node()
            node.children[short] = node.children[long] = child
            node = child
        node.command = command

    def lookup(self, nodes: tuple[str, ...]) -> Command | None:
        """Command registered for the (upper-case) header ``nodes``, if any."""
        node = self._root
        for name in nodes:
            child = node.children.get(name)
            if child is None:
                return None
            node = child
        return node.command


# --------------------------------------------------------------------------------------------
# Argument and response helpers
# --------------------------------------------------------------------------------------------
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_INTEGER_RE = re.compile(r"[+-]?\d+")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.]*")


def parse_number(arg: str, low: float, high: float) -> float:
    """Parse a plain decimal/exponent float within ``[low, high]``.

    Raises:
        ScpiError: -104 if ``arg`` is not a number (``NAN``, ``INF``, hex and thousands
            separators are rejected), -222 if it is outside the range.
    """
    if _NUMBER_RE.fullmatch(arg) is None:
        raise ScpiError(DATA_TYPE)
    value = float(arg)
    if not low <= value <= high:
        raise ScpiError(OUT_OF_RANGE)
    return value


def parse_integer(arg: str, low: int, high: int) -> int:
    """Parse an integer within ``[low, high]`` (``1e3`` is accepted, ``1.5`` is out of range)."""
    if _INTEGER_RE.fullmatch(arg):
        value = int(arg)
    else:
        number = parse_number(arg, -math.inf, math.inf)
        if not number.is_integer():
            raise ScpiError(OUT_OF_RANGE)
        value = int(number)
    if not low <= value <= high:
        raise ScpiError(OUT_OF_RANGE)
    return value


def parse_keyword(arg: str, allowed: Mapping[str, object]) -> object:
    """Look ``arg`` (case-insensitive) up in ``allowed``.

    Raises:
        ScpiError: -222 for a number that is not a member, -224 for an unknown word, -104 for
            anything else.
    """
    key = arg.upper()
    if key in allowed:
        return allowed[key]
    if _NUMBER_RE.fullmatch(arg):
        raise ScpiError(OUT_OF_RANGE)
    raise ScpiError(ILLEGAL_VALUE if _WORD_RE.fullmatch(arg) else DATA_TYPE)


def format_number(value: float) -> str:
    """Response number format: ``%.9g``, with ``NAN``, ``INF`` and ``-INF`` spelled out."""
    if math.isnan(value):
        return "NAN"
    if math.isinf(value):
        return "INF" if value > 0 else "-INF"
    return f"{value:.9g}"


def format_vector(values: np.ndarray, digits: int = 6) -> str:
    """Comma-separated numbers with ``digits`` significant digits (waveform/spectrum payloads).

    Non-finite values are spelled ``NAN``, ``INF`` and ``-INF``.
    """
    numbers = values.tolist()
    if np.isfinite(values).all():
        pattern = f"%.{digits}g"
        return ",".join([pattern % v for v in numbers])
    return ",".join(f"{v:.{digits}g}" if math.isfinite(v) else format_number(v) for v in numbers)
