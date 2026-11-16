"""Threaded TCP transport for one instrument: line framing, replies, fault effects."""

from __future__ import annotations

import contextlib
import logging
import socket
import socketserver
import threading

from .instrument import Instrument, Reply
from .scpi import MAX_LINE_BYTES, SYNTAX

log = logging.getLogger("mfsim")

_RECV_BYTES = 65536
_QUICKACK = getattr(socket, "TCP_QUICKACK", None)


class LineFramer:
    """Splits a TCP byte stream into lines terminated by ``\\n`` (a trailing ``\\r`` is dropped).

    A line longer than ``max_line`` bytes is reported once as ``None`` and discarded up to and
    including its terminator, so the stream stays in sync.
    """

    def __init__(self, max_line: int = MAX_LINE_BYTES) -> None:
        self.max_line = max_line
        self._buffer = bytearray()
        self._dropping = False

    def feed(self, data: bytes) -> list[str | None]:
        """Add received bytes; return the complete lines (``None`` marks an overlong one)."""
        self._buffer += data
        lines: list[str | None] = []
        while True:
            end = self._buffer.find(b"\n")
            if self._dropping:
                if end < 0:
                    self._buffer.clear()
                    return lines
                del self._buffer[:end + 1]
                self._dropping = False
                continue
            if end < 0:
                if len(self._buffer) > self.max_line + 1:
                    lines.append(None)
                    self._buffer.clear()
                    self._dropping = True
                return lines
            line = bytes(self._buffer[:end])
            del self._buffer[:end + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            lines.append(None if len(line) > self.max_line else line.decode("latin-1"))


class _TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 128

    def __init__(self, address: tuple[str, int], instrument: Instrument) -> None:
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        self.instrument = instrument
        self.stopping = threading.Event()
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        super().__init__(address, _Handler)

    def track(self, sock: socket.socket, add: bool) -> None:
        with self._connections_lock:
            (self._connections.add if add else self._connections.discard)(sock)

    def close_connections(self) -> None:
        with self._connections_lock:
            connections = list(self._connections)
        for sock in connections:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def handle_error(self, request: object, client_address: object) -> None:
        log.debug("connection %s ended with an error", client_address, exc_info=True)


class _Handler(socketserver.BaseRequestHandler):
    server: _TcpServer

    def handle(self) -> None:
        sock: socket.socket = self.request
        self.server.track(sock, True)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._serve(sock)
        except OSError:
            pass
        finally:
            self.server.track(sock, False)

    def _serve(self, sock: socket.socket) -> None:
        instrument = self.server.instrument
        framer = LineFramer()
        while not self.server.stopping.is_set():
            data = sock.recv(_RECV_BYTES)
            if not data:
                return
            if _QUICKACK is not None:
                # Acknowledge at once: a client that has Nagle enabled and sends a setter followed
                # by a query would otherwise wait ~40 ms for the delayed ACK of the setter.
                sock.setsockopt(socket.IPPROTO_TCP, _QUICKACK, 1)
            for line in framer.feed(data):
                if line is None:
                    instrument.errors.push(SYNTAX)
                    continue
                if not self._respond(sock, instrument.handle(line)):
                    return

    def _respond(self, sock: socket.socket, reply: Reply) -> bool:
        """Apply the reply; False means the connection must be closed."""
        stopping = self.server.stopping
        if reply.disconnect:
            return False
        if reply.delay_s > 0.0 and stopping.wait(reply.delay_s):
            return False
        payload = reply.payload
        if payload is None:
            return True
        if not reply.chunk_size:
            sock.sendall(payload)
            return True
        for start in range(0, len(payload), reply.chunk_size):
            if start and stopping.wait(reply.chunk_delay_s):
                return False
            sock.sendall(payload[start:start + reply.chunk_size])
        return True


class ScpiServer:
    """TCP server for one :class:`Instrument`, one thread per client connection."""

    def __init__(self, instrument: Instrument, host: str, port: int) -> None:
        self.instrument = instrument
        self._server = _TcpServer((host, port), instrument)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02},
                                        name=f"scpi-{instrument.MODEL}", daemon=True)

    @property
    def port(self) -> int:
        """The bound port (useful when constructed with port 0)."""
        return int(self._server.server_address[1])

    def start(self) -> None:
        """Start accepting connections (the socket is already listening)."""
        self._thread.start()

    def stop(self) -> None:
        """Stop accepting, close every client connection and release the port."""
        self._server.stopping.set()
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.close_connections()
        self._server.server_close()
        if self._thread.ident is not None:
            self._thread.join(timeout=2.0)
