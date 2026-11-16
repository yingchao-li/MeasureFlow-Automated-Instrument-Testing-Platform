"""Shared fixtures: real TCP clients, an in-process rig without sockets, ephemeral ports."""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mfsim.bench import Bench  # noqa: E402
from mfsim.instruments import Analyzer, Dut, SigGen  # noqa: E402
from mfsim.simulator import Simulator  # noqa: E402


class Client:
    """Minimal blocking SCPI client on a real TCP socket (``\\n`` terminated, like the backend)."""

    def __init__(self, port: int, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buffer = b""

    def send(self, *commands: str) -> None:
        """Write command lines (no response expected)."""
        self.sock.sendall("".join(c + "\n" for c in commands).encode())

    def read_line(self, timeout: float | None = None) -> str:
        """Read one response line; ``socket.timeout`` if none arrives."""
        if timeout is not None:
            self.sock.settimeout(timeout)
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("closed by peer")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return line.decode()

    def query(self, command: str) -> str:
        """Send a query and return its response line."""
        self.send(command)
        return self.read_line()

    def sync(self) -> None:
        """Round trip that guarantees all earlier commands on this connection were processed."""
        assert self.query("*OPC?") == "1"

    def drain_errors(self) -> list[str]:
        """Read ``SYST:ERR?`` until the queue is empty and return the entries."""
        errors = []
        while (entry := self.query("SYST:ERR?")) != '0,"No error"':
            errors.append(entry)
        return errors

    def close(self) -> None:
        """Close the socket."""
        self.sock.close()


@pytest.fixture
def sim():
    """A running simulator on three ephemeral ports."""
    with Simulator(base_port=0) as simulator:
        yield simulator


@pytest.fixture
def make_client(sim):
    """Factory ``make_client("analyzer")`` returning connected :class:`Client` objects."""
    clients: list[Client] = []

    def factory(name: str) -> Client:
        client = Client(sim.ports[name])
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def siggen(make_client):
    return make_client("siggen")


@pytest.fixture
def analyzer(make_client):
    return make_client("analyzer")


@pytest.fixture
def dut(make_client):
    return make_client("dut")


class Rig:
    """The three instruments over one bench, driven in-process (no sockets).

    ``rig.sg("SOUR:FREQ?")`` returns the response text, or ``None`` when no response is produced.
    """

    def __init__(self, seed: int = 12345) -> None:
        self.bench = Bench(seed)
        self.siggen = SigGen(self.bench)
        self.analyzer = Analyzer(self.bench)
        self.dut = Dut(self.bench)

    @staticmethod
    def _ask(instrument, line: str) -> str | None:
        payload = instrument.handle(line).payload
        return None if payload is None else payload.decode().rstrip("\n")

    def sg(self, line: str) -> str | None:
        return self._ask(self.siggen, line)

    def an(self, line: str) -> str | None:
        return self._ask(self.analyzer, line)

    def du(self, line: str) -> str | None:
        return self._ask(self.dut, line)

    def tone(self, freq: float = 1000.0, amp: float = 0.05) -> None:
        """Generator: sine at ``freq``/``amp`` with the output on."""
        for line in ("SOUR:FUNC SIN", f"SOUR:FREQ {freq!r}", f"SOUR:VOLT {amp!r}", "OUTP ON"):
            self.sg(line)


@pytest.fixture
def rig() -> Rig:
    return Rig()


def free_port_block(count: int = 3) -> int:
    """First of ``count`` consecutive currently free TCP ports on 127.0.0.1."""
    for _ in range(50):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        base = probe.getsockname()[1]
        probe.close()
        holders = []
        try:
            for offset in range(count):
                holder = socket.socket()
                holder.bind(("127.0.0.1", base + offset))
                holders.append(holder)
            return base
        except OSError:
            continue
        finally:
            for holder in holders:
                holder.close()
    raise RuntimeError("no free port block")


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.01) -> bool:
    """Poll ``predicate`` until true or ``timeout`` seconds elapsed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
