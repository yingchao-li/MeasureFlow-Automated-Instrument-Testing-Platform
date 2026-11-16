#!/usr/bin/env python3
"""Check the simulator with PyVISA (pure-python ``@py`` backend) over raw TCP sockets.

Talks to all three instruments the way a VISA application would
(``TCPIP0::<host>::<port>::SOCKET`` with ``\\n`` termination), prints a PASS/FAIL table and exits
with status 0 only if every check passed.

Usage::

    python3 -m mfsim --base-port 5025 &       # from simulator/
    python3 verify_pyvisa.py                  # talks to 127.0.0.1:5025..5027
    python3 verify_pyvisa.py --spawn          # starts its own simulator on free ports
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyvisa
from pyvisa.resources import MessageBasedResource

HERE = Path(__file__).resolve().parent


@dataclass
class Check:
    """One row of the result table."""

    name: str
    expected: str
    actual: str
    passed: bool


class Sessions:
    """The three VISA sessions plus the result list."""

    def __init__(self, rm: pyvisa.ResourceManager, host: str, ports: Sequence[int], timeout_ms: int) -> None:
        self.sessions: dict[str, MessageBasedResource] = {}
        for name, port in zip(("siggen", "analyzer", "dut"), ports, strict=True):
            session = cast(MessageBasedResource, rm.open_resource(f"TCPIP0::{host}::{port}::SOCKET"))
            session.read_termination = "\n"
            session.write_termination = "\n"
            session.timeout = timeout_ms
            self.sessions[name] = session
        self.checks: list[Check] = []

    def query(self, name: str, command: str) -> str:
        """Send a query and return the stripped response."""
        return self.sessions[name].query(command).strip()

    def send(self, name: str, *commands: str) -> None:
        """Send setters, then synchronise with ``*OPC?`` (separate sockets are not ordered)."""
        for command in commands:
            self.sessions[name].write(command)
        self.query(name, "*OPC?")

    def record(self, name: str, expected: str, actual: str, passed: bool) -> None:
        """Append a check result."""
        self.checks.append(Check(name, expected, actual, passed))

    def expect_text(self, instrument: str, command: str, pattern: str) -> None:
        """Query and require the response to match the regular expression ``pattern``."""
        actual = self.query(instrument, command)
        self.record(f"{instrument}: {command}", pattern, actual, re.fullmatch(pattern, actual) is not None)

    def expect_range(self, label: str, instrument: str, command: str, low: float, high: float) -> None:
        """Query a number and require ``low <= value <= high``."""
        actual = self.query(instrument, command)
        try:
            passed = low <= float(actual) <= high
        except ValueError:
            passed = False
        self.record(label, f"{low:g} .. {high:g}", actual, passed)

    def close(self) -> None:
        """Close all sessions."""
        for session in self.sessions.values():
            session.close()


def run_checks(b: Sessions) -> None:
    """Exercise identification, configuration, measurements, profile/firmware switches and errors."""
    b.expect_text("siggen", "*IDN?", r"MeasureFlow,VSG-1000,SN-SIM-0001,1\.0\.0")
    b.expect_text("analyzer", "*IDN?", r"MeasureFlow,VAA-2000,SN-SIM-0002,1\.0\.0")
    b.expect_text("dut", "*IDN?", r"MeasureFlow,VDUT-HA1,SN-SIM-0003,1\.0\.0")
    for name in b.sessions:
        b.send(name, "*RST", "*CLS")
    b.expect_text("siggen", "MF:SOUR:CONF?", r"SIN,1000,0.05,48000,0")
    b.send("siggen", "SOUR:FUNC SIN", "SOUR:FREQ 1000", "SOUR:VOLT 0.05", "OUTP ON")
    b.expect_text("siggen", "SOUR:FREQ?", r"1000")
    b.expect_text("siggen", "MF:SOUR:CONF?", r"SIN,1000,0.05,48000,1")
    b.expect_text("analyzer", "MF:ACQ:CONF?", r"16384,48000,0,0")
    b.send("analyzer", "MF:ACQ:INIT")

    # NORMAL / 1.0.0: gain 20.016 dB, THD 0.118 %, SNR 71.8 dB, noise -80.8 dBV, RMS 0.354 V
    b.expect_range("NORMAL gain dB", "analyzer", "MEAS:GAIN?", 19.9, 20.15)
    b.expect_range("NORMAL THD %", "analyzer", "MEAS:THD?", 0.10, 0.14)
    b.expect_range("NORMAL SNR dB", "analyzer", "MEAS:SNR?", 71.0, 72.6)
    b.expect_range("NORMAL noise dBV", "analyzer", "MEAS:NOIS?", -81.4, -80.2)
    b.expect_range("NORMAL frequency Hz", "analyzer", "MEAS:FREQ?", 999.9, 1000.1)
    b.expect_range("NORMAL RMS V", "analyzer", "MEAS:RMS?", 0.350, 0.358)
    b.expect_text("analyzer", "MF:ANAL:WIN?", r"FLATTOP")

    b.send("dut", "MF:DUT:PROF LOWGAIN")
    b.expect_range("LOWGAIN gain dB", "analyzer", "MEAS:GAIN?", 13.9, 14.15)
    b.send("dut", "MF:DUT:PROF HIGHTHD")
    b.expect_range("HIGHTHD THD %", "analyzer", "MEAS:THD?", 2.8, 3.1)
    b.send("dut", "MF:DUT:PROF NOISY")
    b.expect_range("NOISY SNR dB", "analyzer", "MEAS:SNR?", 41.0, 42.6)
    b.send("dut", "MF:DUT:PROF CLIPPING")
    b.expect_range("CLIPPING THD %", "analyzer", "MEAS:THD?", 10.0, 100.0)
    b.expect_range("CLIPPING RMS V", "analyzer", "MEAS:RMS?", 0.0, 0.30)
    b.send("dut", "MF:DUT:PROF NORMAL", "MF:DUT:FW 1.2.0")
    b.expect_text("dut", "*IDN?", r"MeasureFlow,VDUT-HA1,SN-SIM-0003,1\.2\.0")
    b.expect_range("fw 1.2.0 THD %", "analyzer", "MEAS:THD?", 1.5, 3.0)
    b.expect_range("fw 1.2.0 gain dB", "analyzer", "MEAS:GAIN?", 19.0, 21.0)
    b.send("dut", "MF:DUT:FW 1.0.0")
    b.expect_text("dut", "MF:DUT:CONF?", r"NORMAL,20,100,8000,-80,0.004,0.01,1.5,1\.0\.0")

    b.sessions["analyzer"].write("MEAS:BOGUS?")
    b.expect_text("analyzer", "SYST:ERR?", r'-113,"Undefined header"')
    b.expect_text("analyzer", "SYST:ERR?", r'0,"No error"')
    b.send("siggen", "SOUR:FREQ 30000")
    b.expect_text("siggen", "SYST:ERR?", r'-222,"Data out of range"')
    b.send("siggen", "OUTP OFF")
    b.expect_text("analyzer", "MEAS:GAIN?", r"NAN")
    b.expect_text("analyzer", "SYST:ERR?", r'-221,"Settings conflict"')


def print_table(checks: Sequence[Check]) -> None:
    """Print the PASS/FAIL table."""
    width = max(len(c.name) for c in checks)
    print(f"{'CHECK':<{width}}  {'EXPECTED':<24}  {'ACTUAL':<44}  RESULT")
    for c in checks:
        print(f"{c.name:<{width}}  {c.expected:<24.24}  {c.actual:<44.44}  {'PASS' if c.passed else 'FAIL'}")
    failed = sum(not c.passed for c in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed" + (f", {failed} FAILED" if failed else ""))


def spawn_simulator() -> tuple[subprocess.Popen[str], list[int]]:
    """Start ``python3 -m mfsim --base-port 0`` and return the process and its three ports."""
    process = subprocess.Popen([sys.executable, "-m", "mfsim", "--base-port", "0"], cwd=HERE,
                               stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    line = process.stdout.readline()
    match = re.fullmatch(r"READY siggen=(\d+) analyzer=(\d+) dut=(\d+)\s*", line)
    if match is None:
        process.kill()
        raise RuntimeError(f"unexpected simulator output: {line!r}")
    return process, [int(p) for p in match.groups()]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns 0 only if all checks pass."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--base-port", type=int, default=5025)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--spawn", action="store_true", help="start a private simulator on free ports")
    args = parser.parse_args(argv)

    process = None
    ports = [args.base_port + i for i in range(3)]
    if args.spawn:
        process, ports = spawn_simulator()
    bench = None
    try:
        bench = Sessions(pyvisa.ResourceManager("@py"), args.host, ports, args.timeout_ms)
        run_checks(bench)
        print_table(bench.checks)
        return 0 if all(c.passed for c in bench.checks) else 1
    except (pyvisa.VisaIOError, OSError, RuntimeError) as error:
        print(f"FAIL: cannot talk to the simulator on {args.host}:{ports}: {error}", file=sys.stderr)
        return 2
    finally:
        if bench is not None:
            bench.close()
        if process is not None:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
