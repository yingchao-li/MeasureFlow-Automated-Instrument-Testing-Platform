"""Fault injection shared by all three instrument servers (INTERFACE.md section 3.1).

Each server owns one :class:`FaultInjector`.  Counters are armed with ``MF:FAULT:<kind> <n>``,
decrement per affected command/response and are evaluated after the line was parsed.
``MF:FAULT:*`` commands are exempt: they are never faulted and never consume a counter.

Semantics chosen where the contract is silent:

* ``DISCONNECT``: the command is *not executed*; the connection is closed without a response.
* ``TIMEOUT``: the command executes normally and the connection stays silent for ``delay_ms``
  before the response (if any) is sent; nothing else on the connection is processed meanwhile.
* ``GARBAGE``, ``NAN``, ``INF``, ``OVERSIZE`` replace the text of a *query response*;
  ``NAN``/``INF`` only apply to responses that are a single number.  At most one replacement is
  applied per response, in the order GARBAGE, NAN, INF, OVERSIZE; the other counters wait.
* ``FRAGMENT`` is independent: the (possibly replaced) response is sent in chunks.
* ``OVERSIZE``: the response is the original text followed by spaces, 2 MiB + 1 KiB in total.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

KINDS = ("TIMEOUT", "DISCONNECT", "GARBAGE", "FRAGMENT", "NAN", "INF", "OVERSIZE")
GARBAGE_TEXT = "#!GARBAGE~~"
OVERSIZE_BYTES = 2 * 1024 * 1024 + 1024
DEFAULT_TIMEOUT_MS = 5000.0
DEFAULT_FRAGMENT_CHUNK = 3
DEFAULT_FRAGMENT_DELAY_MS = 15.0
_NUMERIC_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class CommandFault:
    """Effect on the command being processed."""

    disconnect: bool = False
    delay_s: float = 0.0


@dataclass(frozen=True)
class ResponseFault:
    """Effect on the response text: possibly replaced, possibly sent in chunks."""

    text: str
    chunk_size: int = 0
    chunk_delay_s: float = 0.0


class FaultInjector:
    """Thread-safe set of armed fault counters of one instrument server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.clear()

    def clear(self) -> None:
        """Disarm everything and restore the default timing parameters (``MF:FAULT:CLEAR``)."""
        with self._lock:
            self._counts = dict.fromkeys(KINDS, 0)
            self._timeout_ms = DEFAULT_TIMEOUT_MS
            self._chunk = DEFAULT_FRAGMENT_CHUNK
            self._chunk_delay_ms = DEFAULT_FRAGMENT_DELAY_MS

    def arm(self, kind: str, count: int, timeout_ms: float | None = None,
            chunk: int | None = None, chunk_delay_ms: float | None = None) -> None:
        """Set the counter of ``kind`` to ``count`` (0 disarms) and optionally its timing."""
        with self._lock:
            self._counts[kind] = count
            if kind == "TIMEOUT":
                self._timeout_ms = DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
            elif kind == "FRAGMENT":
                self._chunk = DEFAULT_FRAGMENT_CHUNK if chunk is None else chunk
                self._chunk_delay_ms = (DEFAULT_FRAGMENT_DELAY_MS if chunk_delay_ms is None
                                        else chunk_delay_ms)

    def status(self) -> str:
        """Remaining counters as ``TIMEOUT=0,DISCONNECT=0,...`` (``MF:FAULT?``)."""
        with self._lock:
            return ",".join(f"{kind}={self._counts[kind]}" for kind in KINDS)

    def on_command(self) -> CommandFault:
        """Consume the per-command counters (DISCONNECT, TIMEOUT) for one command."""
        with self._lock:
            disconnect = self._counts["DISCONNECT"] > 0
            if disconnect:
                self._counts["DISCONNECT"] -= 1
            delayed = self._counts["TIMEOUT"] > 0
            if delayed:
                self._counts["TIMEOUT"] -= 1
            return CommandFault(disconnect, self._timeout_ms / 1000.0 if delayed else 0.0)

    def on_response(self, text: str) -> ResponseFault:
        """Consume the per-response counters for one query response and shape it."""
        with self._lock:
            numeric = _NUMERIC_RE.fullmatch(text) is not None
            if self._counts["GARBAGE"] > 0:
                self._counts["GARBAGE"] -= 1
                text = GARBAGE_TEXT
            elif numeric and self._counts["NAN"] > 0:
                self._counts["NAN"] -= 1
                text = "NAN"
            elif numeric and self._counts["INF"] > 0:
                self._counts["INF"] -= 1
                text = "INF"
            elif self._counts["OVERSIZE"] > 0:
                self._counts["OVERSIZE"] -= 1
                text = text + " " * (OVERSIZE_BYTES - len(text))
            if self._counts["FRAGMENT"] > 0:
                self._counts["FRAGMENT"] -= 1
                return ResponseFault(text, self._chunk, self._chunk_delay_ms / 1000.0)
            return ResponseFault(text)
