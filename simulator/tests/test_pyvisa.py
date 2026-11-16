"""``verify_pyvisa.py`` end to end with the pure-python PyVISA backend."""

from __future__ import annotations

import pytest

pytest.importorskip("pyvisa")
pytest.importorskip("pyvisa_py")

import verify_pyvisa  # noqa: E402

from conftest import free_port_block  # noqa: E402
from mfsim.simulator import Simulator  # noqa: E402


def test_verify_script_passes_against_a_fresh_simulator(capsys):
    assert verify_pyvisa.main(["--spawn"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out and "checks passed" in out
    assert out.count("PASS") >= 25


def test_verify_script_against_explicit_ports(capsys):
    base = free_port_block()
    with Simulator(base_port=base):
        assert verify_pyvisa.main(["--base-port", str(base)]) == 0
    assert "checks passed" in capsys.readouterr().out


def test_verify_script_reports_a_connection_failure(capsys):
    base = free_port_block()
    assert verify_pyvisa.main(["--base-port", str(base), "--timeout-ms", "300"]) == 2
    assert "cannot talk to the simulator" in capsys.readouterr().err


def test_verify_script_exits_non_zero_when_a_check_fails(capsys, monkeypatch):
    monkeypatch.setattr(verify_pyvisa, "run_checks",
                        lambda b: b.expect_range("forced failure", "analyzer", "MEAS:RMS?", 5.0, 6.0))
    base = free_port_block()
    with Simulator(base_port=base):
        assert verify_pyvisa.main(["--base-port", str(base)]) == 1
    out = capsys.readouterr().out
    assert "forced failure" in out and "FAIL" in out and "1 FAILED" in out
