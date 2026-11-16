"""Command-line entry point: READY line, signals, argument handling."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from conftest import Client, free_port_block
from mfsim import __main__ as cli

SIM_DIR = Path(__file__).resolve().parents[1]
READY = re.compile(r"READY siggen=(\d+) analyzer=(\d+) dut=(\d+)")


def start(*args: str) -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, "-m", "mfsim", *args], cwd=SIM_DIR, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def test_subprocess_prints_ready_serves_and_exits_cleanly_on_sigterm():
    base = free_port_block()
    process = start("--host", "127.0.0.1", "--base-port", str(base), "--seed", "12345")
    try:
        line = process.stdout.readline()
        assert line == f"READY siggen={base} analyzer={base + 1} dut={base + 2}\n"
        assert Client(base).query("*IDN?") == "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0"
        assert Client(base + 1).query("MF:SIM:VERS?") == "0.1.0"
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_subprocess_exits_cleanly_on_sigint_even_with_open_connections():
    process = start("--base-port", "0")
    try:
        ports = [int(p) for p in READY.fullmatch(process.stdout.readline().strip()).groups()]
        client = Client(ports[1])
        client.send("MF:FAULT:TIMEOUT 1,60000")
        client.sock.sendall(b"*OPC?\n")          # a handler asleep in a TIMEOUT fault must not block the exit
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_seed_argument_sets_the_reset_default():
    process = start("--base-port", "0", "--seed", "777")
    try:
        ports = [int(p) for p in READY.fullmatch(process.stdout.readline().strip()).groups()]
        client = Client(ports[1])
        assert client.query("MF:ACQ:SEED?") == "777"
        client.send("MF:ACQ:SEED 5", "*RST")
        assert client.query("MF:ACQ:SEED?") == "777"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_port_in_use_exits_with_status_2_and_no_ready_line():
    base = free_port_block()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", base + 2))
    blocker.listen()
    try:
        process = start("--base-port", str(base))
        out, err = process.communicate(timeout=10)
        assert process.returncode == 2 and "READY" not in out and "cannot bind" in err
    finally:
        blocker.close()


@pytest.mark.parametrize("args", [["--host", "0.0.0.0"], ["--host", "192.0.2.1"], ["--host", "example.org"],
                                  ["--base-port", "70000"], ["--base-port", "-1"], ["--seed", "-5"]])
def test_invalid_or_unsafe_arguments_are_refused(args):
    assert cli.main(args) == 2


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0 and "mfsim 0.1.0" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--base-port", "abc"])


def test_unsafe_bind_flag_allows_a_non_loopback_address():
    assert cli._is_loopback("127.0.0.1") and cli._is_loopback("localhost") and cli._is_loopback("::1")
    assert cli._is_loopback("127.5.5.5")
    assert not cli._is_loopback("0.0.0.0") and not cli._is_loopback("10.0.0.1") and not cli._is_loopback("host.example")


def test_main_in_process_serves_until_signalled(capsys):
    previous = signal.getsignal(signal.SIGTERM)
    timer = threading.Timer(0.8, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        assert cli.main(["--base-port", "0"]) == 0
    finally:
        timer.cancel()
    assert READY.fullmatch(capsys.readouterr().out.strip())
    assert signal.getsignal(signal.SIGTERM) is previous        # handlers restored


def test_main_in_process_reports_a_bind_failure(capsys):
    base = free_port_block()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", base))
    blocker.listen()
    try:
        assert cli.main(["--base-port", str(base)]) == 2
    finally:
        blocker.close()
    assert "cannot bind" in capsys.readouterr().err
