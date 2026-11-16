"""Assembly of the bench, the three instruments and their servers."""

from __future__ import annotations

from types import TracebackType

from .bench import DEFAULT_SEED, Bench
from .instruments import Analyzer, Dut, SigGen
from .server import ScpiServer

INSTRUMENT_NAMES = ("siggen", "analyzer", "dut")


class Simulator:
    """Three SCPI servers (siggen, analyzer, dut) over one shared :class:`Bench`.

    Ports are ``base_port``, ``base_port + 1`` and ``base_port + 2``; ``base_port=0`` lets the OS
    pick three free ports (see :attr:`ports`).  Sockets listen as soon as the object exists.
    """

    def __init__(self, host: str = "127.0.0.1", base_port: int = 5025, seed: int = DEFAULT_SEED) -> None:
        self.bench = Bench(seed)
        self.instruments = {
            "siggen": SigGen(self.bench), "analyzer": Analyzer(self.bench), "dut": Dut(self.bench)}
        self._servers: dict[str, ScpiServer] = {}
        try:
            for offset, name in enumerate(INSTRUMENT_NAMES):
                port = base_port + offset if base_port else 0
                self._servers[name] = ScpiServer(self.instruments[name], host, port)
        except OSError:
            self.stop()
            raise

    @property
    def ports(self) -> dict[str, int]:
        """Bound TCP port of each instrument."""
        return {name: server.port for name, server in self._servers.items()}

    def ready_line(self) -> str:
        """The line printed on stdout once everything listens."""
        return "READY " + " ".join(f"{name}={port}" for name, port in self.ports.items())

    def start(self) -> None:
        """Start serving clients."""
        for server in self._servers.values():
            server.start()

    def stop(self) -> None:
        """Stop all servers and close every connection."""
        for server in self._servers.values():
            server.stop()

    def __enter__(self) -> Simulator:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.stop()
