"""Command line entry point: ``python3 -m mfsim --host 127.0.0.1 --base-port 5025 --seed 12345``."""

from __future__ import annotations

import argparse
import ipaddress
import signal
import sys
import threading
from collections.abc import Sequence

from . import __version__
from .bench import DEFAULT_SEED
from .simulator import Simulator

LOOPBACK_NAMES = ("localhost",)


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of the simulator."""
    parser = argparse.ArgumentParser(prog="mfsim", description="MeasureFlow virtual instruments (SCPI over TCP)")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind (default: 127.0.0.1)")
    parser.add_argument("--base-port", type=int, default=5025,
                        help="siggen port; analyzer = base+1, dut = base+2; 0 picks free ports (default: 5025)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="noise seed restored by *RST (default: 12345)")
    parser.add_argument("--unsafe-bind", action="store_true", help="allow binding a non-loopback address")
    parser.add_argument("--version", action="version", version=f"mfsim {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Start the simulator, print ``READY ...`` and serve until SIGINT/SIGTERM.

    Returns:
        0 after a clean shutdown, 2 for invalid arguments or if a port cannot be bound.
    """
    args = build_parser().parse_args(argv)
    if not _is_loopback(args.host) and not args.unsafe_bind:
        print(f"mfsim: refusing to bind non-loopback address {args.host!r} (use --unsafe-bind)", file=sys.stderr)
        return 2
    if not 0 <= args.base_port <= 65533 or args.seed < 0:
        print("mfsim: --base-port must be 0..65533 and --seed >= 0", file=sys.stderr)
        return 2
    try:
        simulator = Simulator(args.host, args.base_port, args.seed)
    except OSError as error:
        print(f"mfsim: cannot bind {args.host}:{args.base_port}..{args.base_port + 2}: {error}", file=sys.stderr)
        return 2
    stop = threading.Event()
    previous = {signum: signal.signal(signum, lambda *_: stop.set())
                for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        simulator.start()
        print(simulator.ready_line(), flush=True)
        while not stop.wait(0.2):
            pass
    finally:
        simulator.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
