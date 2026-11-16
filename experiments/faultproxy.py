"""Transparent, rule-driven SCPI/TCP proxy used by the QA suite to inject simulator faults
*at precisely defined points of a test run*.

Why it exists
-------------
``MF:FAULT:*`` injections live inside the simulator and are cleared by ``*RST`` -- which every
sequence ``init`` step sends. A fault armed from the outside before a run is therefore wiped, and
a run only lasts a few tens of milliseconds, so arming it "during" the run by wall-clock time is
racy. The proxy sits between the backend and the simulator (``instruments.json`` points at the
proxy ports), counts the SCPI commands that pass through and, when a rule matches, writes the
``MF:FAULT:*`` line(s) to the *simulator* immediately before forwarding the triggering command.
The faults themselves are still produced by the real simulator; the proxy only decides *when*.

It can also add a fixed per-command latency (used to stretch runs so they can be cancelled at
controlled progress points) and records a trace of every command (used to plan fault points).

The server->client direction is forwarded byte-for-byte without line buffering, so chunked
(FRAGMENT) and oversize responses reach the backend exactly as the simulator emitted them.
"""
from __future__ import annotations

import re
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

__all__ = ["FaultProxy", "Rule", "TraceEntry"]


@dataclass
class TraceEntry:
    t: float            # time.monotonic() when the command was seen
    wall: float         # time.time() (to align with API timestamps)
    instrument: str
    conn: int           # connection serial number (per proxy)
    text: str           # command text, stripped
    injected: list[str] = field(default_factory=list)  # fault lines sent just before it


@dataclass
class Rule:
    """Inject ``inject`` lines before forwarding matching commands.

    * ``match``  - regex (case-insensitive, ``re.search`` on the stripped command) or ``None``
                   (= every command).
    * ``nth``    - first matching command (1-based, counted from arming) that triggers.
    * ``times``  - number of consecutive matching commands that trigger (starting at ``nth``).
    * ``inject`` - SCPI lines (e.g. ``["MF:FAULT:DISCONNECT 1"]``) written to the simulator
                   immediately before the triggering command.
    * ``target`` - instrument that receives ``inject`` (default: the instrument that carries the
                   triggering command); used e.g. to set ``MF:DUT:FAULT`` when the analyzer queries.
    * ``action`` - optional callable executed (in the proxy thread) at the trigger, before the
                   command is forwarded; used for hard simulator kills at an exact point.
    * ``replace``- bytes sent to the client *instead of* the simulator's response line to the
                   triggering command (``b"\\n"`` = empty line, ``b"1.9"`` = truncated/unterminated,
                   ``b""`` = response swallowed). Only meaningful for queries.
    """

    instrument: str
    inject: list[str]
    match: Optional[str] = None
    nth: int = 1
    times: int = 1
    target: Optional[str] = None
    action: Optional[Callable[[], None]] = None
    replace: Optional[bytes] = None
    seen: int = 0
    fired: int = 0
    _rx: Optional["re.Pattern[str]"] = None

    def __post_init__(self) -> None:
        self._rx = re.compile(self.match, re.IGNORECASE) if self.match else None

    def check(self, text: str) -> bool:
        if self._rx is not None and not self._rx.search(text):
            return False
        self.seen += 1
        if self.nth <= self.seen < self.nth + self.times:
            self.fired += 1
            return True
        return False


class _Listener:
    def __init__(self, name: str, upstream_port: int, host: str) -> None:
        self.name = name
        self.upstream_port = upstream_port
        self.host = host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, 0))
        self.sock.listen(32)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]


class FaultProxy:
    def __init__(self, upstream_ports: dict[str, int], host: str = "127.0.0.1") -> None:
        self.host = host
        self._listeners = {n: _Listener(n, p, host) for n, p in upstream_ports.items()}
        self.listen_ports: dict[str, int] = {n: l.port for n, l in self._listeners.items()}
        self._lock = threading.Lock()
        self._rules: list[Rule] = []
        self._latency_ms: dict[str, float] = {}
        self._trace: list[TraceEntry] = []
        self._conn_serial = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._socks: set[socket.socket] = set()
        self.on_command: Optional[Callable[[TraceEntry], None]] = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        for l in self._listeners.values():
            t = threading.Thread(target=self._accept_loop, args=(l,), daemon=True, name=f"proxy-acc-{l.name}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            socks = list(self._socks)
        for s in socks:
            _close(s)
        for l in self._listeners.values():
            _close(l.sock)
        for t in self._threads:
            t.join(timeout=1.0)

    def sever_all(self) -> None:
        """Close every live connection (simulates a network cut); new connections still work."""
        with self._lock:
            socks = list(self._socks)
        for s in socks:
            _close(s)

    # ------------------------------------------------------------------ rules / latency / trace
    def arm(self, instrument: str, inject: list[str] | str = (), match: Optional[str] = None,
            nth: int = 1, times: int = 1, target: Optional[str] = None,
            action: Optional[Callable[[], None]] = None, replace: Optional[bytes] = None) -> Rule:
        if isinstance(inject, str):
            inject = [inject]
        rule = Rule(instrument, list(inject), match, nth, times, target, action, replace)
        with self._lock:
            self._rules.append(rule)
        return rule

    def clear_rules(self) -> None:
        with self._lock:
            self._rules.clear()

    def set_latency(self, instrument: str, ms: float) -> None:
        with self._lock:
            if ms <= 0:
                self._latency_ms.pop(instrument, None)
            else:
                self._latency_ms[instrument] = float(ms)

    def clear_latency(self) -> None:
        with self._lock:
            self._latency_ms.clear()

    def reset(self) -> None:
        """Remove rules and latency; keep the trace."""
        self.clear_rules()
        self.clear_latency()

    def clear_trace(self) -> None:
        with self._lock:
            self._trace.clear()

    def trace(self, instrument: Optional[str] = None) -> list[TraceEntry]:
        with self._lock:
            return [e for e in self._trace if instrument is None or e.instrument == instrument]

    def commands(self, instrument: str) -> list[str]:
        return [e.text for e in self.trace(instrument)]

    # ------------------------------------------------------------------ internals
    def _accept_loop(self, l: _Listener) -> None:
        while not self._stop.is_set():
            try:
                client, _ = l.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self._conn_serial += 1
                serial = self._conn_serial
            threading.Thread(target=self._serve, args=(l, client, serial), daemon=True,
                             name=f"proxy-conn-{l.name}-{serial}").start()

    def _serve(self, l: _Listener, client: socket.socket, serial: int) -> None:
        try:
            up = socket.create_connection((l.host, l.upstream_port), timeout=2.0)
        except OSError:
            _close(client)
            return
        up.settimeout(None)
        for s in (client, up):
            try:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        with self._lock:
            self._socks.update((client, up))
        replace_q: "deque[bytes]" = deque()
        down = threading.Thread(target=self._pump_down, args=(up, client, replace_q), daemon=True)
        down.start()
        try:
            self._pump_commands(l, client, up, serial, replace_q)
        finally:
            _close(client)
            _close(up)
            down.join(timeout=1.0)
            with self._lock:
                self._socks.discard(client)
                self._socks.discard(up)

    @staticmethod
    def _pump_down(src: socket.socket, dst: socket.socket, replace_q: "deque[bytes]") -> None:
        """simulator -> backend. Bytes pass through unmodified and unbuffered, except that a pending
        replacement swallows exactly one response line and sends the replacement instead."""
        buf = b""
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if not replace_q and not buf:
                    dst.sendall(data)
                    continue
                buf += data
                while replace_q and b"\n" in buf:
                    _, buf = buf.split(b"\n", 1)
                    repl = replace_q.popleft()
                    if repl:
                        dst.sendall(repl)
                if not replace_q and buf:
                    dst.sendall(buf)
                    buf = b""
        except OSError:
            pass
        finally:
            _close(src)
            _close(dst)

    def _pump_commands(self, l: _Listener, client: socket.socket, up: socket.socket, serial: int,
                       replace_q: "deque[bytes]") -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                data = client.recv(65536)
            except OSError:
                return
            if not data:
                return
            buf += data
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw, buf = buf[:nl + 1], buf[nl + 1:]
                text = raw.decode("ascii", "replace").strip()
                injected: list[str] = []
                elsewhere: list[tuple[str, list[str]]] = []
                actions: list[Callable[[], None]] = []
                replacements: list[bytes] = []
                with self._lock:
                    delay = self._latency_ms.get(l.name, 0.0)
                    for rule in self._rules:
                        if rule.instrument == l.name and text and rule.check(text):
                            if rule.target and rule.target != l.name:
                                elsewhere.append((rule.target, rule.inject))
                            else:
                                injected.extend(rule.inject)
                            if rule.action:
                                actions.append(rule.action)
                            if rule.replace is not None:
                                replacements.append(rule.replace)
                    entry = TraceEntry(time.monotonic(), time.time(), l.name, serial, text,
                                       list(injected) + [f"{t}:{x}" for t, xs in elsewhere for x in xs])
                    self._trace.append(entry)
                if self.on_command:
                    self.on_command(entry)
                replace_q.extend(replacements)          # before forwarding: the response cannot overtake it
                for tgt, lines in elsewhere:
                    self._inject_other(tgt, lines)
                for act in actions:
                    act()
                if delay:
                    time.sleep(delay / 1000.0)
                try:
                    for line in injected:
                        up.sendall(line.encode("ascii") + b"\n")
                    up.sendall(raw)
                except OSError:
                    return

    def _inject_other(self, target: str, lines: list[str]) -> None:
        """Send ``lines`` to another instrument's simulator socket on a private connection."""
        port = self._listeners[target].upstream_port
        try:
            with socket.create_connection((self.host, port), timeout=2.0) as s:
                for line in lines:
                    s.sendall(line.encode("ascii") + b"\n")
                s.sendall(b"MF:FAULT?\n")      # barrier: the answer proves all lines were processed
                s.settimeout(2.0)
                s.recv(4096)
        except OSError:
            pass


def _close(s: socket.socket) -> None:
    try:
        s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        s.close()
    except OSError:
        pass
