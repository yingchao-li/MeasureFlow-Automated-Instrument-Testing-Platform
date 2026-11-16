"""REST API conformance tests (docs/INTERFACE.md section 5) against the real backend + simulator.

Success shapes are validated with the JSON schemas in ``schemas.py``; failure modes are checked for
the unified error body, status code and *absence of side effects*. Where the contract is silent the
accepted status set is spelled out in the test (and kept minimal).
"""
from __future__ import annotations

import http.client
import json
import math
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pytest

import truth_adapter as ta
from schemas import (COMMAND_RESULT, ENVIRONMENT, HEALTH, INSTRUMENT_ONE, INSTRUMENTS, LIVE, LOGS, REPORTS,
                     RESULTS, RUN_ENVELOPE, RUNS, SEQUENCES, STATUS_ENVELOPE, SUMMARY, assert_error_body,
                     assert_task_semantics, validate)
from stack import Stack

ALL = ("siggen", "analyzer", "dut")
ALLOWED_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
BAD_ORIGINS = ["http://evil.com", "http://127.0.0.1:5174", "http://localhost:5173.evil.com", "https://localhost:5173",
               "http://127.0.0.1", "null", "http://localhost:5173@evil.com", "http://LOCALHOST.evil.com:5173"]


# ------------------------------------------------------------------------------------------ helpers
def raw(st: Stack, method: str, path: str, body: Optional[bytes] = None, headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0) -> tuple[int, dict[str, str], bytes]:
    """HTTP request with the path sent *verbatim* (requests/urllib3 would normalise ``..``)."""
    conn = http.client.HTTPConnection("127.0.0.1", st.backend_port, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse()
        data = r.read()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, data
    finally:
        conn.close()


def post_raw(st: Stack, path: str, body: bytes | str, ctype: Optional[str] = "application/json") -> Any:
    h = {"Content-Type": ctype} if ctype else {}
    return st.api("POST", path, data=body if isinstance(body, bytes) else body.encode(), headers=h)


def wait_until(pred, timeout: float = 6.0, poll: float = 0.05, what: str = "condition") -> Any:  # noqa: ANN001
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(poll)
    raise AssertionError(f"timeout waiting for {what}")


def inst_state(st: Stack, iid: str) -> str:
    return st.instruments()[iid]["state"]


def ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


@pytest.fixture
def connected(pstack: Stack) -> Stack:
    pstack.connect_all()
    return pstack


@pytest.fixture(scope="module")
def history(pstack: Stack) -> dict[str, Any]:
    """A diverse persisted history: PASS/FAIL/ERROR runs over several firmwares/profiles, retried tasks."""
    ids: dict[str, str] = {}
    spec = [("normal", "full_pipeline", None, {"profile": "NORMAL", "firmware": "1.0.0"}),
            ("lowgain", "full_pipeline", None, {"profile": "LOWGAIN"}),
            ("fw110", "full_pipeline", None, {"profile": "NORMAL", "firmware": "1.1.0"}),
            ("fw120", "full_pipeline", None, {"profile": "NORMAL", "firmware": "1.2.0"}),
            ("highthd", "thd_measurement", None, {"profile": "HIGHTHD"}),
            ("noisy", "noise_floor", None, {"profile": "NOISY"}),
            ("sweep", "frequency_sweep", {"frequency_hz": 2000}, None),
            ("gain", "gain_verification", None, None)]
    for key, seq, params, dut in spec:
        r = pstack.run_sequence(seq, parameters=params, dut=dut, label=f"hist-{key}")
        ids[key] = r["run_id"]
    # an ERROR run with retries (unrecovered) and a recovered one
    pstack.proxy.arm("analyzer", "MF:FAULT:TIMEOUT 1,2500", match=r"^MEAS:GAIN\?", nth=1, times=100)  # type: ignore[union-attr]
    ids["timeout"] = pstack.run_sequence("gain_verification", retries=1, label="hist-timeout", timeout=60)["run_id"]
    pstack.proxy.reset()                                      # type: ignore[union-attr]
    pstack.proxy.arm("analyzer", "MF:FAULT:TIMEOUT 1,2500", match=r"^MEAS:GAIN\?", nth=1, times=2)  # type: ignore[union-attr]
    ids["recovered"] = pstack.run_sequence("gain_verification", retries=1, label="hist-recovered", timeout=60)["run_id"]
    pstack.proxy.reset()                                      # type: ignore[union-attr]
    return ids


# ================================================================================= health / environment
def test_health_shape_and_states(pstack: Stack) -> None:
    h = pstack.api_json("GET", "/api/health")
    validate(h, HEALTH, "health")
    assert h["instruments_total"] == 3 and h["running_test"] is None
    assert h["version"] == h["software"]["backend"]
    assert any(c["name"] == "results_dir_writable" and c["status"] == "ok" for c in h["checks"])
    cfg = json.loads((pstack.mf_root / "configs" / "instruments.json").read_text())
    assert h["software"]["config_version"] == cfg["config_version"]
    # nothing connected -> degraded (instrument offline), never "down" while the results dir is writable
    wait_until(lambda: pstack.api_json("GET", "/api/health")["instruments_online"] == 0, what="0 online")
    assert pstack.api_json("GET", "/api/health")["status"] == "degraded"
    pstack.connect_all()
    h2 = wait_until(lambda: (lambda x: x if x["instruments_online"] == 3 else None)(pstack.api_json("GET", "/api/health")),
                    timeout=6, what="3 online")
    assert h2["status"] == "ok", h2["checks"]
    assert h2["software"]["simulator"] == pstack.scpi("siggen", "MF:SIM:VERS?")
    assert h2["uptime_s"] >= h["uptime_s"]


def test_health_goes_degraded_when_simulator_disappears_and_recovers(stack: Stack) -> None:
    # (no fault proxy here: it would keep the instrument ports listening after the simulator died)
    stack.connect_all()
    wait_until(lambda: stack.api_json("GET", "/api/health")["status"] == "ok", timeout=8, what="ok before the kill")
    stack.kill_simulator()
    try:
        wait_until(lambda: stack.api_json("GET", "/api/health")["status"] == "degraded", timeout=10, what="degraded")
        assert stack.api("GET", "/api/health").status_code == 200, "health must stay answerable"
        assert any(c["status"] != "ok" for c in stack.api_json("GET", "/api/health")["checks"])
    finally:
        stack.start_simulator()
    stack.connect_all()
    wait_until(lambda: stack.api_json("GET", "/api/health")["status"] == "ok", timeout=8, what="ok again")


def test_health_is_cheap_even_under_load(pstack: Stack) -> None:
    t0 = time.monotonic()
    for _ in range(200):
        assert pstack.api("GET", "/api/health").status_code == 200
    assert (time.monotonic() - t0) / 200 < 0.05, "health must be cheap (cached)"


def test_environment_report(connected: Stack) -> None:
    env = connected.api_json("GET", "/api/environment")
    validate(env, ENVIRONMENT, "environment")
    assert env["config"]["sequences"] == 7
    assert env["software"]["api_version"] == "1.0"
    assert {i["id"] for i in env["instruments"]} == set(ALL)
    assert all(i["state"] == "connected" and i["idn"].startswith("MeasureFlow,") for i in env["instruments"])
    cal = {c["instrument_id"]: c for c in env["calibration"]}
    assert set(cal) == {"siggen", "analyzer"}
    for c in cal.values():
        due = datetime.strptime(c["calibrated_on"], "%Y-%m-%d").date() + timedelta(days=365)
        assert c["due"] == due.isoformat() and c["simulated"] is True
        assert abs(c["days_remaining"] - (due - date.today()).days) <= 1
        assert c["status"] == ("valid" if c["days_remaining"] > 30 else "due_soon" if c["days_remaining"] >= 0 else "expired")
    deps = {d["name"]: d for d in env["dependencies"]}
    assert len(deps) >= 3 and all(d["status"] == "ok" for d in deps.values()), deps
    assert env["history"]["runs"] == len(connected.all_runs())


def test_environment_flags_unreachable_simulator(stack: Stack) -> None:
    stack.kill_simulator()
    try:
        env = stack.api_json("GET", "/api/environment")
        validate(env, ENVIRONMENT, "environment")
        bad = [d for d in env["dependencies"] if d["name"].startswith("simulator_")]
        assert bad and all(d["status"] in ("warn", "fail") for d in bad), "dead simulator ports must be reported"
    finally:
        stack.start_simulator()


@pytest.mark.parametrize("calibrated_on,status,health", [
    ((date.today() - timedelta(days=400)).isoformat(), "expired", "degraded"),
    ((date.today() - timedelta(days=345)).isoformat(), "due_soon", "degraded"),
    ((date.today() - timedelta(days=10)).isoformat(), "valid", "ok"),
])
def test_calibration_status_rules_and_never_blocks_runs(make_stack: Any, calibrated_on: str, status: str, health: Optional[str]) -> None:
    cal = {"records": [{"instrument_id": i, "certificate": f"SIM-{i}", "calibrated_on": calibrated_on, "valid_days": 365,
                        "simulated": True} for i in ("siggen", "analyzer")]}
    st: Stack = make_stack(config_files={"calibration.json": cal}, overrides={i: {"timeout_ms": 500} for i in ALL})
    st.connect_all()
    env = st.api_json("GET", "/api/environment")
    assert {c["status"] for c in env["calibration"]} == {status}
    if health:
        h = wait_until(lambda: (lambda x: x if x["instruments_online"] == 3 else None)(st.api_json("GET", "/api/health")),
                       what="online")
        assert h["status"] == health, h
    if status == "expired":
        logs = st.logs_since(0, 1000, level="warn")["logs"]
        assert any("calibrat" in e["message"].lower() for e in logs), "expired calibration must log a warning"
    assert st.run_sequence("gain_verification")["status"] == "PASS", "expired calibration must never block runs"


# ================================================================================= instruments
def test_instrument_list_shape_and_disconnected_defaults(pstack: Stack) -> None:
    body = pstack.api_json("GET", "/api/instruments")
    validate(body, INSTRUMENTS, "instruments")
    by = {i["id"]: i for i in body["instruments"]}
    assert set(by) == set(ALL)
    cfg = json.loads((pstack.mf_root / "configs" / "instruments.json").read_text())
    for c in cfg["instruments"]:
        i = by[c["id"]]
        assert i["port"] == c["port"] and i["host"] == c["host"] and i["name"] == c["name"] and i["kind"] == c["kind"]
        assert i["state"] == "disconnected" and i["settings"] is None and i["leased_by"] is None
    assert by["siggen"]["calibration"]["status"] == "valid" and by["analyzer"]["calibration"]["status"] == "valid"


def test_connect_single_and_all_reflect_real_instrument_state(pstack: Stack) -> None:
    out = pstack.api_json("POST", "/api/instruments/connect", {"id": "siggen"})
    validate(out, INSTRUMENTS, "connect")
    assert [i["id"] for i in out["instruments"]] == ["siggen"] and out["instruments"][0]["state"] == "connected"
    assert inst_state(pstack, "analyzer") == "disconnected", "connecting one instrument must not connect others"
    out = pstack.api_json("POST", "/api/instruments/connect", {"id": "all"})
    by = {i["id"]: i for i in out["instruments"]}
    assert set(by) == set(ALL) and all(i["state"] == "connected" for i in by.values())
    for iid, i in by.items():
        assert i["idn"] == pstack.scpi(iid, "*IDN?"), "idn must be the instrument's real answer"
        assert i["firmware"] == i["idn"].split(",")[3]
        assert i["last_seen"] and i["latency_ms"] is not None and i["last_error"] is None
    # settings reflect the instrument (cross-checked directly over SCPI)
    s = by["siggen"]["settings"]
    f, fr, a, sr, o = pstack.scpi("siggen", "MF:SOUR:CONF?").split(",")
    assert (s["function"], s["frequency_hz"], s["amplitude_vpk"], s["sample_rate_hz"], s["output"]) == (f, float(fr), float(a), float(sr), o == "1")
    assert by["analyzer"]["settings"]["points"] == int(pstack.scpi("analyzer", "MF:ACQ:POIN?"))
    d = by["dut"]["settings"]
    conf = pstack.scpi("dut", "MF:DUT:CONF?").split(",")
    assert d["profile"] == conf[0] and d["gain_db"] == float(conf[1]) and d["firmware"] == conf[8] == "1.0.0"
    assert (d["hpf_hz"], d["lpf_hz"], d["noise_dbv"], d["hd2"], d["hd3"], d["clip_vpk"]) == tuple(float(x) for x in conf[2:8])


def test_connect_is_idempotent_and_disconnect_roundtrip(pstack: Stack) -> None:
    for _ in range(3):
        assert pstack.api_json("POST", "/api/instruments/connect", {"id": "dut"})["instruments"][0]["state"] == "connected"
    out = pstack.api_json("POST", "/api/instruments/disconnect", {"id": "dut"})
    assert out["instruments"][0]["state"] == "disconnected" and out["instruments"][0]["settings"] is None
    out = pstack.api_json("POST", "/api/instruments/disconnect", {"id": "dut"})       # idempotent
    assert out["instruments"][0]["state"] == "disconnected"
    for _ in range(20):                                                              # reconnect cycles do not leak
        pstack.connect_all(); pstack.disconnect_all()
    assert all(i["state"] == "disconnected" for i in pstack.instruments().values())


def test_disconnect_switches_generator_output_off(connected: Stack) -> None:
    connected.api_json("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"output": True}})
    assert connected.scpi("siggen", "OUTP?") == "1"
    connected.api_json("POST", "/api/instruments/disconnect", {"id": "siggen"})
    assert connected.scpi("siggen", "OUTP?") == "0", "best-effort OUTP OFF before closing"


def test_connect_failure_sets_error_state_and_recovers(pstack: Stack) -> None:
    pstack.kill_simulator()
    try:
        r = pstack.api("POST", "/api/instruments/connect", {"id": "siggen"})
        assert r.status_code in (502, 504), r.text
        assert assert_error_body(r.json())["code"] in ("COMMUNICATION_ERROR", "TIMEOUT")
        i = pstack.instruments()["siggen"]
        assert i["state"] == "error" and i["last_error"], "failed connect must leave state=error with last_error"
        r = pstack.api("POST", "/api/instruments/connect", {"id": "all"})
        assert r.status_code in (502, 504)
    finally:
        pstack.start_simulator()
    out = pstack.api_json("POST", "/api/instruments/connect", {"id": "all"})
    assert all(i["state"] == "connected" and i["last_error"] is None for i in out["instruments"])


@pytest.mark.parametrize("host", ["192.168.1.1", "example.com", "10.0.0.1", "8.8.8.8", "0.0.0.0", "::2",
                                  "evil.com", "127.0.0.1.evil.com", "localhost.evil.com", "169.254.169.254",
                                  "fe80::1", "[::1]x", "1.2.3.4"])
def test_non_loopback_hosts_are_forbidden_and_cause_no_connection_attempt(pstack: Stack, host: str) -> None:
    seq0 = pstack.logs_since(0, 1)["last_seq"]
    r = pstack.api("POST", "/api/instruments/connect", {"id": "siggen", "host": host, "port": 5025})
    assert r.status_code == 403, f"{host}: {r.status_code} {r.text}"
    assert assert_error_body(r.json(), "FORBIDDEN_HOST")
    assert inst_state(pstack, "siggen") == "disconnected"
    cfg = json.loads((pstack.mf_root / "configs" / "instruments.json").read_text())
    shown = pstack.instruments()["siggen"]
    assert shown["host"] == "127.0.0.1", "rejected host override must not be stored"
    new = [e for e in pstack.logs_since(seq0, 500)["logs"] if e["source"] == "scpi"]
    assert not new, f"no SCPI traffic expected for a forbidden host, saw {new[:2]}"


_QA001 = pytest.mark.xfail(strict=True, reason="QA-001: loopback check runs on the trimmed host, the raw string is then used (docs/QA_REVIEW.md)")


@pytest.mark.parametrize("host", ["http://127.0.0.1", "127.0.0.1:5025", " ", "", "a" * 300,
                                  pytest.param("127.0.0.1\n", marks=_QA001), pytest.param(" 127.0.0.1", marks=_QA001),
                                  pytest.param("127.0.0.1 ", marks=_QA001), pytest.param("\t127.0.0.1", marks=_QA001)])
def test_malformed_host_values_are_rejected_not_connected(pstack: Stack, host: str) -> None:
    r = pstack.api("POST", "/api/instruments/connect", {"id": "siggen", "host": host})
    assert r.status_code in (400, 403), f"{host!r}: {r.status_code} {r.text}"
    assert_error_body(r.json())
    assert inst_state(pstack, "siggen") == "disconnected"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_host_override_is_accepted(pstack: Stack, host: str) -> None:
    out = pstack.api_json("POST", "/api/instruments/connect", {"id": "siggen", "host": host, "port": pstack.instrument_ports["siggen"]})
    assert out["instruments"][0]["state"] == "connected"


def test_ipv6_loopback_is_not_forbidden(pstack: Stack) -> None:
    r = pstack.api("POST", "/api/instruments/connect", {"id": "siggen", "host": "::1", "port": pstack.instrument_ports["siggen"]})
    assert r.status_code != 403, "::1 is an allowed loopback host (the simulator just does not listen on IPv6)"
    assert r.status_code in (200, 502, 504)


@pytest.mark.parametrize("body", [{}, {"id": 5}, {"id": None}, {"id": ["siggen"]}, {"id": "nope"}, {"id": "siggen", "bogus": 1},
                                  {"id": "siggen", "port": 0}, {"id": "siggen", "port": 70000}, {"id": "siggen", "port": -1},
                                  {"id": "siggen", "port": "5025"}, {"id": "siggen", "port": 5025.5}, {"id": "siggen", "host": 5}])
def test_connect_validation(pstack: Stack, body: dict[str, Any]) -> None:
    r = pstack.api("POST", "/api/instruments/connect", body)
    expect = 404 if body.get("id") == "nope" and len(body) == 1 else 400
    assert r.status_code == expect, f"{body}: {r.status_code} {r.text}"
    assert_error_body(r.json(), "NOT_FOUND" if expect == 404 else "INVALID_ARGUMENT")
    assert all(i["state"] == "disconnected" for i in pstack.instruments().values())


@pytest.mark.parametrize("body,code", [({}, 400), ({"id": 1}, 400), ({"id": "nope"}, 404), ({"id": "all", "x": 1}, 400)])
def test_disconnect_validation(pstack: Stack, body: dict[str, Any], code: int) -> None:
    r = pstack.api("POST", "/api/instruments/disconnect", body)
    assert r.status_code == code and assert_error_body(r.json())


# ================================================================================= command
def test_command_query_and_setter_shapes(connected: Stack) -> None:
    q = connected.command("siggen", "*IDN?")
    validate(q, COMMAND_RESULT, "command result")
    assert q["is_query"] is True and q["response"].startswith("MeasureFlow,VSG-1000") and q["error"] is None
    assert q["id"] == "siggen" and q["command"] == "*IDN?"
    s = connected.command("siggen", "SOUR:FREQ 1500")
    validate(s, COMMAND_RESULT, "setter result")
    assert s["is_query"] is False and s["response"] is None and s["error"] is None
    assert connected.command("siggen", "SOUR:FREQ?")["response"] == "1500"
    assert connected.scpi("siggen", "SOUR:FREQ?") == "1500", "setter really reached the instrument"
    assert abs(ts(q["timestamp"]) - time.time()) < 30


@pytest.mark.parametrize("cmd,code", [("SOUR:FREQ 5", -222), ("SOUR:FREQ abc", -104), ("NOPE:CMD 1", -113), ("SOUR:VOLT 99", -222)])
def test_command_setter_error_is_reported_and_queue_drained(connected: Stack, cmd: str, code: int) -> None:
    r = connected.command("siggen", cmd)
    assert r["error"] is not None and r["error"]["code"] == code and r["error"]["message"]
    assert connected.scpi("siggen", "SYST:ERR?") == '0,"No error"', "backend must have consumed the error queue entry"
    ok = connected.command("siggen", "SOUR:FREQ 1000")
    assert ok["error"] is None, "stale error must not leak into the next command"


def test_command_to_fault_free_query_returns_exact_text(connected: Stack) -> None:
    assert connected.command("analyzer", "MF:ACQ:POIN?")["response"] == "16384"
    assert connected.command("dut", "MF:DUT:CONF?")["response"].startswith("NORMAL,20,100,8000,-80,")


def test_command_response_longer_than_4096_is_truncated_and_flagged(connected: Stack) -> None:
    connected.command("siggen", "OUTP ON")
    r = connected.command("analyzer", "MF:ACQ:FFT?")
    assert r["truncated"] is True and len(r["response"]) <= 4096
    assert re.match(r"^48000,16384,", r["response"])
    short = connected.command("analyzer", "*OPC?")
    assert short.get("truncated") in (None, False)


_QA003 = pytest.mark.xfail(strict=True, reason="QA-003: command is trimmed before validation, trailing line break accepted (docs/QA_REVIEW.md)")


@pytest.mark.parametrize("cmd", ["", "x" * 513, pytest.param("*IDN?\n", marks=_QA003), pytest.param("*IDN?\r", marks=_QA003), "*IDN?\n*IDN?", "SOUR:FREQ\t1000", "café?", "\x00?", "\x7f?", 5, None, ["*IDN?"]])
def test_command_validation(connected: Stack, cmd: Any) -> None:
    r = connected.api("POST", "/api/instruments/command", {"id": "siggen", "command": cmd})
    assert r.status_code == 400, f"{cmd!r}: {r.status_code}"
    assert_error_body(r.json(), "INVALID_ARGUMENT")


def test_command_length_boundary_512_accepted(connected: Stack) -> None:
    cmd = " " * 507 + "*IDN?"
    assert len(cmd) == 512
    r = connected.api("POST", "/api/instruments/command", {"id": "siggen", "command": cmd})
    assert r.status_code == 200 and r.json()["response"].startswith("MeasureFlow")


@pytest.mark.parametrize("body,code", [({"id": "siggen"}, 400), ({"command": "*IDN?"}, 400), ({"id": "nope", "command": "*IDN?"}, 404),
                                       ({"id": "siggen", "command": "*IDN?", "extra": 1}, 400), ({"id": 3, "command": "*IDN?"}, 400)])
def test_command_missing_unknown_and_wrong_fields(connected: Stack, body: dict[str, Any], code: int) -> None:
    r = connected.api("POST", "/api/instruments/command", body)
    assert r.status_code == code and assert_error_body(r.json())


def test_command_requires_connection(pstack: Stack) -> None:
    r = pstack.api("POST", "/api/instruments/command", {"id": "siggen", "command": "*IDN?"})
    assert r.status_code == 409 and assert_error_body(r.json(), "NOT_CONNECTED")


def test_command_timeout_maps_to_504_and_stack_recovers(connected: Stack) -> None:
    connected.scpi("analyzer", "MF:FAULT:TIMEOUT 50,3000")
    t0 = time.monotonic()
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"})
    assert r.status_code == 504 and assert_error_body(r.json(), "TIMEOUT")
    assert time.monotonic() - t0 < 15
    connected.scpi("analyzer", "MF:FAULT:CLEAR")
    ok = connected.command("analyzer", "*IDN?")
    assert ok["response"].startswith("MeasureFlow,VAA-2000"), "no stale response desynchronisation after a timeout"
    assert connected.command("analyzer", "*OPC?")["response"] == "1"


def test_command_disconnect_fault_is_transparently_retried_for_queries(connected: Stack) -> None:
    connected.scpi("analyzer", "MF:FAULT:DISCONNECT 1")
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"})
    assert r.status_code == 200 and r.json()["response"].startswith("MeasureFlow,VAA-2000"), r.text


def test_command_persistent_disconnect_maps_to_502(connected: Stack) -> None:
    connected.scpi("analyzer", "MF:FAULT:DISCONNECT 50")
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"})
    assert r.status_code == 502, r.text
    err = assert_error_body(r.json(), "COMMUNICATION_ERROR")
    assert err["details"] and err["details"].get("kind")
    connected.scpi("analyzer", "MF:FAULT:CLEAR")
    wait_until(lambda: connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"}).status_code == 200,
               timeout=10, what="auto reconnect")


def test_command_oversize_response_is_communication_error(connected: Stack) -> None:
    connected.scpi("analyzer", "MF:FAULT:OVERSIZE 5")        # > attempts (1 + max_retries=1); a single one is retried away
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"}, timeout=40)
    assert r.status_code == 502, r.text
    err = assert_error_body(r.json(), "COMMUNICATION_ERROR")
    assert err["details"] and err["details"].get("kind")
    connected.scpi("analyzer", "MF:FAULT:CLEAR")
    assert connected.command("analyzer", "*OPC?")["response"] == "1", "backend must resynchronise after an oversize response"


def test_command_single_oversize_response_is_retried_transparently(connected: Stack) -> None:
    """*IDN? is idempotent: one oversize response is dropped, the connection resynchronised and the query repeated."""
    connected.scpi("analyzer", "MF:FAULT:OVERSIZE 1")
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"}, timeout=40)
    assert r.status_code == 200, r.text
    assert r.json()["response"].startswith("MeasureFlow,VAA-2000")


def test_command_unanswered_query_does_not_desync_following_commands(connected: Stack) -> None:
    r = connected.api("POST", "/api/instruments/command", {"id": "siggen", "command": "NOSUCH:QUERY?"})
    assert r.status_code in (200, 504, 502), r.text
    if r.status_code == 200:
        assert r.json()["response"] is None and r.json()["error"] is not None
    assert connected.command("siggen", "*IDN?")["response"].startswith("MeasureFlow,VSG-1000")


def test_command_double_response_line_does_not_desync_the_connection(connected: Stack) -> None:
    connected.api("POST", "/api/instruments/command", {"id": "siggen", "command": "*IDN?;*IDN?"})
    assert connected.command("siggen", "*OPC?")["response"] == "1", "a stray second response line must not shift later answers"
    assert connected.command("siggen", "*OPC?")["response"] == "1"


# ================================================================================= configure
def test_configure_siggen_dut_analyzer_and_cross_check_over_scpi(connected: Stack) -> None:
    out = connected.api_json("POST", "/api/instruments/configure",
                             {"id": "siggen", "settings": {"function": "SQU", "frequency_hz": 2500, "amplitude_vpk": 0.2, "output": True}})
    validate(out, INSTRUMENT_ONE, "configure")
    s = out["instrument"]["settings"]
    assert (s["function"], s["frequency_hz"], s["amplitude_vpk"], s["output"]) == ("SQU", 2500, 0.2, True)
    assert connected.scpi("siggen", "MF:SOUR:CONF?") == "SQU,2500,0.2,48000,1"
    out = connected.api_json("POST", "/api/instruments/configure",
                             {"id": "dut", "settings": {"profile": "HIGHTHD", "firmware": "1.2.0", "gain_db": 18}})
    assert out["instrument"]["settings"]["firmware"] == "1.2.0" and out["instrument"]["settings"]["gain_db"] == 18
    assert connected.scpi("dut", "*IDN?").endswith(",1.2.0") and float(connected.scpi("dut", "MF:DUT:GAIN?")) == 18
    out = connected.api_json("POST", "/api/instruments/configure", {"id": "analyzer", "settings": {"points": 8192}})
    assert out["instrument"]["settings"]["points"] == 8192 and connected.scpi("analyzer", "MF:ACQ:POIN?") == "8192"
    assert connected.instruments()["analyzer"]["settings"]["points"] == 8192


@pytest.mark.parametrize("iid,key,lo,hi,bad_lo,bad_hi", [
    ("siggen", "frequency_hz", 10, 20000, 9.99, 20000.01), ("siggen", "amplitude_vpk", 0, 5, -0.01, 5.01),
    ("siggen", "sample_rate_hz", 8000, 192000, 7999, 192001),
    ("dut", "gain_db", -20, 60, -20.1, 60.1), ("dut", "hpf_hz", 20, 1000, 19, 1001), ("dut", "lpf_hz", 1000, 20000, 999, 20001),
    ("dut", "noise_dbv", -140, 0, -141, 0.5), ("dut", "hd2", 0, 1, -0.01, 1.01), ("dut", "hd3", 0, 1, -0.01, 1.01),
    ("dut", "clip_vpk", 0.01, 10, 0.009, 10.5),
])
def test_configure_range_boundaries(connected: Stack, iid: str, key: str, lo: float, hi: float, bad_lo: float, bad_hi: float) -> None:
    for v in (lo, hi):
        out = connected.api_json("POST", "/api/instruments/configure", {"id": iid, "settings": {key: v}})
        assert out["instrument"]["settings"][key] == pytest.approx(v)
    before = connected.instruments()[iid]["settings"]
    for v in (bad_lo, bad_hi):
        r = connected.api("POST", "/api/instruments/configure", {"id": iid, "settings": {key: v}})
        assert r.status_code == 400, f"{iid}.{key}={v}: {r.status_code} {r.text}"
        assert assert_error_body(r.json(), "INVALID_ARGUMENT")["details"]["field"] in (key, f"settings.{key}")
    assert connected.instruments()[iid]["settings"] == before, "rejected configure must not change state"


@pytest.mark.parametrize("iid,settings", [
    ("siggen", {"frequency_hz": "1000"}), ("siggen", {"output": "true"}), ("siggen", {"output": 1}), ("siggen", {"function": "TRI"}),
    ("siggen", {"function": 5}), ("siggen", {"points": 1024}), ("siggen", {"bogus": 1}), ("siggen", {"frequency_hz": None}),
    ("analyzer", {"points": 3000}), ("analyzer", {"points": 512}), ("analyzer", {"points": 131072}), ("analyzer", {"points": 4096.5}),
    ("analyzer", {"sample_rate_hz": 44100}), ("analyzer", {"acquisition_stored": True}), ("analyzer", {"points": "4096"}),
    ("dut", {"profile": "SUPERB"}), ("dut", {"firmware": "9.9.9"}), ("dut", {"profile": 3}), ("dut", {"frequency_hz": 1}),
])
def test_configure_rejects_invalid_settings(connected: Stack, iid: str, settings: dict[str, Any]) -> None:
    before = connected.instruments()[iid]["settings"]
    r = connected.api("POST", "/api/instruments/configure", {"id": iid, "settings": settings})
    assert r.status_code == 400 and assert_error_body(r.json(), "INVALID_ARGUMENT"), r.text
    assert connected.instruments()[iid]["settings"] == before


def test_configure_is_atomic_when_one_field_is_invalid(connected: Stack) -> None:
    before = connected.instruments()["siggen"]["settings"]
    r = connected.api("POST", "/api/instruments/configure",
                      {"id": "siggen", "settings": {"frequency_hz": 3333, "amplitude_vpk": 99}})
    assert r.status_code == 400
    assert connected.instruments()["siggen"]["settings"] == before, "valid fields must not be applied when another field is invalid"
    assert connected.scpi("siggen", "SOUR:FREQ?") == f"{before['frequency_hz']:.9g}"


@pytest.mark.parametrize("body,code", [({"id": "siggen"}, 400), ({"settings": {}}, 400), ({"id": "nope", "settings": {"frequency_hz": 5}}, 404),
                                       ({"id": "siggen", "settings": []}, 400), ({"id": "siggen", "settings": "x"}, 400),
                                       ({"id": "siggen", "settings": {"frequency_hz": 100}, "extra": 1}, 400)])
def test_configure_structure_validation(connected: Stack, body: dict[str, Any], code: int) -> None:
    r = connected.api("POST", "/api/instruments/configure", body)
    assert r.status_code == code and assert_error_body(r.json())


def test_configure_requires_connection(pstack: Stack) -> None:
    r = pstack.api("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"frequency_hz": 500}})
    assert r.status_code == 409 and assert_error_body(r.json(), "NOT_CONNECTED")


# ================================================================================= live measurement
def test_live_measurement_shape_values_and_decimation(connected: Stack) -> None:
    connected.api_json("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"function": "SIN", "frequency_hz": 1000, "amplitude_vpk": 0.05, "output": True}})
    m = connected.api_json("GET", "/api/measurements/live", params={"points": 512, "bins": 1024})
    validate(m, LIVE, "live")
    assert len(m["waveform"]["samples"]) == 512 and m["waveform"]["sample_rate_hz"] == 48000
    sp = m["spectrum"]
    assert len(sp["freq_hz"]) == len(sp["magnitude"]) <= 1024
    assert sp["freq_hz"] == sorted(sp["freq_hz"]) and sp["df_hz"] == pytest.approx(sp["sample_rate_hz"] / sp["nfft"], rel=1e-3)
    assert len(set(m["waveform"]["samples"])) > 100, "waveform must not be constant"
    exp = ta.expected_metrics("NORMAL", "1.0.0", 1000, 0.05)
    k = max(range(len(sp["magnitude"])), key=lambda i: sp["magnitude"][i])
    assert sp["magnitude"][k] == pytest.approx(20 * math.log10(0.5), abs=0.35), "max-hold decimation must preserve the peak"
    assert abs(sp["freq_hz"][k] - 1000) <= 2 * sp["df_hz"] * math.ceil((sp["nfft"] / 2 + 1) / 1024)
    mt = m["metrics"]
    assert mt["gain_db"] == pytest.approx(exp["gain_db"], abs=0.1) and mt["thd_percent"] == pytest.approx(exp["thd_percent"], rel=0.1, abs=0.01)
    assert mt["rms_v"] == pytest.approx(exp["rms_v"], rel=0.01) and mt["snr_db"] == pytest.approx(exp["snr_db"], abs=1.0)
    assert mt["noise_floor_dbv"] == pytest.approx(exp["noise_floor_dbv"], abs=1.0)
    assert {k_: m["stimulus"][k_] for k_ in ("function", "frequency_hz", "amplitude_vpk", "output")} == \
        {"function": "SIN", "frequency_hz": 1000, "amplitude_vpk": 0.05, "output": True}
    assert m["warnings"] == [] and m["duration_ms"] > 0


def test_live_measurement_with_output_off_nulls_sine_metrics_and_warns(connected: Stack) -> None:
    connected.api_json("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"output": False}})
    m = connected.api_json("GET", "/api/measurements/live")
    validate(m, LIVE, "live")
    for k in ("gain_db", "thd_percent", "snr_db"):
        assert m["metrics"][k] is None
    assert m["metrics"]["rms_v"] is not None and m["warnings"] and all(isinstance(w, str) and w for w in m["warnings"])
    assert len(m["waveform"]["samples"]) == 512


def test_live_measurement_non_sine_stimulus_warns(connected: Stack) -> None:
    connected.api_json("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"function": "SQU", "output": True}})
    m = connected.api_json("GET", "/api/measurements/live")
    assert m["metrics"]["gain_db"] is None and m["warnings"]


@pytest.mark.parametrize("params,ok", [({"points": 16}, True), ({"points": 4096}, True), ({"bins": 16}, True), ({"bins": 8192}, True),
                                       ({"points": 15}, False), ({"points": 4097}, False), ({"points": 0}, False), ({"points": -5}, False),
                                       ({"points": "abc"}, False), ({"points": 512.5}, False), ({"bins": 15}, False), ({"bins": 8193}, False),
                                       pytest.param({"bins": ""}, False, marks=pytest.mark.xfail(strict=True, reason="QA-004: empty query value treated as absent (docs/QA_REVIEW.md)")),
                                       pytest.param({"points": ""}, False, marks=pytest.mark.xfail(strict=True, reason="QA-004: empty query value treated as absent (docs/QA_REVIEW.md)"))])
def test_live_parameter_bounds(connected: Stack, params: dict[str, Any], ok: bool) -> None:
    connected.api_json("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"function": "SIN", "output": True}})
    r = connected.api("GET", "/api/measurements/live", params=params)
    if ok:
        assert r.status_code == 200, r.text
        if "points" in params:
            assert len(r.json()["waveform"]["samples"]) == params["points"]
        if "bins" in params:
            assert len(r.json()["spectrum"]["magnitude"]) <= params["bins"]
    else:
        assert r.status_code == 400 and assert_error_body(r.json(), "INVALID_ARGUMENT")


def test_live_measurement_requires_all_three_instruments(pstack: Stack) -> None:
    pstack.connect_all()
    pstack.api_json("POST", "/api/instruments/disconnect", {"id": "dut"})
    r = pstack.api("GET", "/api/measurements/live")
    assert r.status_code == 409 and assert_error_body(r.json(), "NOT_CONNECTED")


# ================================================================================= sequences
def test_sequences_match_config_files(pstack: Stack, repo_root: Any) -> None:
    body = pstack.api_json("GET", "/api/sequences")
    validate(body, SEQUENCES, "sequences")
    files = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (repo_root / "configs" / "sequences").glob("*.json")}
    got = {s["id"]: s for s in body["sequences"]}
    assert set(got) == set(files) and len(files) == 7
    for sid, cfg in files.items():
        g = got[sid]
        assert (g["name"], g["version"], g["description"], g["dut"]) == (cfg["name"], cfg["version"], cfg["description"], cfg["dut"])
        assert [s["id"] for s in g["steps"]] == [s["id"] for s in cfg["steps"]]
        assert [s["type"] for s in g["steps"]] == [s["type"] for s in cfg["steps"]]
        params = {p["key"]: p for p in g["parameters"]}
        assert set(params) == set(cfg["parameters"])
        for k, spec in cfg["parameters"].items():
            assert all(params[k][f] == spec[f] for f in ("label", "unit", "default", "min", "max"))


# ================================================================================= tests/run validation
RUN_BAD = [
    ({}, 400), ({"sequence_id": 5}, 400), ({"sequence_id": "nope"}, 404), ({"sequence_id": "gain_verification", "bogus": 1}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"bogus": 1}}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"frequency_hz": 19}}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"frequency_hz": 20001}}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"frequency_hz": "1000"}}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"amplitude_vpk": 0}}, 400),
    ({"sequence_id": "gain_verification", "parameters": {"amplitude_vpk": 1.01}}, 400),
    ({"sequence_id": "gain_verification", "parameters": []}, 400), ({"sequence_id": "gain_verification", "parameters": "x"}, 400),
    ({"sequence_id": "thd_measurement", "parameters": {"gain_min_db": 1}}, 400),         # declared by *another* sequence
    ({"sequence_id": "gain_verification", "retries": -1}, 400), ({"sequence_id": "gain_verification", "retries": 6}, 400),
    ({"sequence_id": "gain_verification", "retries": 1.5}, 400), ({"sequence_id": "gain_verification", "retries": "2"}, 400),
    ({"sequence_id": "gain_verification", "label": "x" * 65}, 400), ({"sequence_id": "gain_verification", "label": 5}, 400),
    ({"sequence_id": "gain_verification", "dut": {"profile": "SUPERB"}}, 400), ({"sequence_id": "gain_verification", "dut": {"firmware": "9.9.9"}}, 400),
    ({"sequence_id": "gain_verification", "dut": {"profile": "NORMAL", "x": 1}}, 400), ({"sequence_id": "gain_verification", "dut": "NORMAL"}, 400),
]


@pytest.mark.parametrize("body,code", RUN_BAD)
def test_run_request_validation_and_no_run_is_created(pstack: Stack, body: dict[str, Any], code: int) -> None:
    n_before = pstack.api_json("GET", "/api/tests/runs")["total"]
    r = pstack.api("POST", "/api/tests/run", body)
    assert r.status_code == code, f"{body}: {r.status_code} {r.text}"
    assert_error_body(r.json(), "NOT_FOUND" if code == 404 else "INVALID_ARGUMENT")
    assert pstack.api_json("GET", "/api/tests/runs")["total"] == n_before, "rejected request must not create a run"


@pytest.mark.parametrize("extra", [{"retries": 0}, {"retries": 5}, {"label": "x" * 64}, {"label": ""},
                                   {"parameters": {"frequency_hz": 20, "amplitude_vpk": 0.001}},
                                   {"parameters": {"frequency_hz": 20000, "amplitude_vpk": 1.0}}])
def test_run_request_boundary_values_are_accepted(pstack: Stack, extra: dict[str, Any]) -> None:
    run = pstack.start_run("gain_verification", **{k: v for k, v in extra.items()})
    validate({"run": run}, RUN_ENVELOPE, "run summary")
    done = pstack.wait_run(run["run_id"], 60)
    assert done["status"] in ("PASS", "FAIL"), done["status"]
    if "retries" in extra:
        assert done["retries"] == extra["retries"]
    if "label" in extra:
        assert done["label"] == (extra["label"] or None) or done["label"] == extra["label"]


def test_run_summary_defaults_and_echo(pstack: Stack) -> None:
    run = pstack.start_run("gain_verification", label="echo me", retries=3, dut={"profile": "NOISY", "firmware": "1.1.0"})
    validate({"run": run}, RUN_ENVELOPE, "run summary")
    assert run["sequence_id"] == "gain_verification" and run["sequence_name"] == "Gain Verification"
    assert run["label"] == "echo me" and run["retries"] == 3 and run["dut"] == {"profile": "NOISY", "firmware": "1.1.0"}
    assert run["status"] in ("PENDING", "RUNNING") and run["cancel_requested"] is False
    done = pstack.wait_run(run["run_id"], 30)
    default = pstack.run_sequence("gain_verification")
    assert default["retries"] == 1, "default task retries is 1"
    assert default["dut"] == {"profile": "NORMAL", "firmware": "1.0.0"} and default["label"] in (None, "")
    assert done["parameters"]["frequency_hz"] == 1000 and done["parameters"]["gain_min_db"] == 19.0, "defaults filled in"


def test_run_label_is_stored_verbatim_including_unicode_and_markup(pstack: Stack) -> None:
    for label in ["<script>alert(1)</script>", "Prüfung ✓ 测试", 'a"b\'c\\d', "line with spaces  ", "%s%n{}${x}"]:
        run = pstack.run_sequence("gain_verification", label=label)
        assert run["label"] == label
        assert pstack.run_status(run["run_id"])["label"] == label


# ================================================================================= status / results / runs
def test_status_endpoint_variants(pstack: Stack) -> None:
    run = pstack.run_sequence("full_pipeline", label="status-test")
    d = pstack.api_json("GET", "/api/tests/status", params={"run_id": run["run_id"], "log_tail": 5})
    validate(d, STATUS_ENVELOPE, "status")
    assert d["run"]["run_id"] == run["run_id"] and len(d["run"]["log"]) <= 5
    assert pstack.api_json("GET", "/api/tests/status", params={"run_id": run["run_id"], "log_tail": 0})["run"]["log"] == []
    latest = pstack.api_json("GET", "/api/tests/status")["run"]
    assert latest["run_id"] == run["run_id"], "default = most recently finished run"
    assert len(latest["tasks"]) == 13 and [s["id"] for s in latest["steps"]][0] == "init"
    r = pstack.api("GET", "/api/tests/status", params={"run_id": "run-20000101-000000-ffff"})
    assert r.status_code == 404 and assert_error_body(r.json(), "NOT_FOUND")


def test_status_on_empty_history_is_null_run(make_stack: Any) -> None:
    st: Stack = make_stack()
    assert st.api_json("GET", "/api/tests/status") == {"run": None}
    assert st.api_json("GET", "/api/tests/results") == {"total": 0, "limit": 100, "offset": 0, "results": []}
    runs = st.api_json("GET", "/api/tests/runs")
    assert runs["total"] == 0 and runs["runs"] == []
    s = st.api_json("GET", "/api/reports/summary")
    validate(s, SUMMARY, "empty summary")
    assert s["tasks"]["total"] == 0 and s["runs"]["total"] == 0 and s["trend"] == [] and s["by_firmware"] == []
    assert st.api_json("GET", "/api/reports") == {"reports": []}


@pytest.mark.parametrize("params", [{"log_tail": -1}, {"log_tail": "x"}, {"run_id": "../../etc/passwd"}, {"run_id": "a b"}, {"run_id": "x" * 65}])
def test_status_rejects_bad_parameters(pstack: Stack, params: dict[str, Any]) -> None:
    r = pstack.api("GET", "/api/tests/status", params=params)
    assert r.status_code in (400, 404), f"{params}: {r.status_code} {r.text[:200]}"
    assert_error_body(r.json())


def test_results_pagination_ordering_and_filters_match_independent_filtering(pstack: Stack, history: dict[str, str]) -> None:
    allrows = pstack.all_results()
    body = pstack.api_json("GET", "/api/tests/results", params={"limit": 7, "offset": 3})
    validate(body, RESULTS, "results")
    assert body["total"] == len(allrows) and body["limit"] == 7 and body["offset"] == 3
    assert [t["task_id"] for t in body["results"]] == [t["task_id"] for t in allrows[3:10]], "paging must be a slice of the full list"
    stamps = [ts(t["timestamp"]) for t in allrows]
    assert stamps == sorted(stamps, reverse=True), "newest first"
    assert len({t["task_id"] for t in allrows}) == len(allrows), "task ids unique across history"
    for t in allrows:
        assert_task_semantics(t)
    beyond = pstack.api_json("GET", "/api/tests/results", params={"limit": 5, "offset": len(allrows) + 10})
    assert beyond["results"] == [] and beyond["total"] == len(allrows)
    filters = [{"status": "FAIL"}, {"status": "PASS"}, {"status": "ERROR"}, {"kind": "thd"}, {"firmware": "1.2.0"}, {"profile": "LOWGAIN"},
               {"sequence_id": "full_pipeline"}, {"run_id": history["normal"]}, {"kind": "freq_sweep", "firmware": "1.0.0"},
               {"status": "FAIL", "profile": "HIGHTHD"}]
    runs = {r["run_id"]: r for r in pstack.all_runs()}
    for f in filters:
        want = [t for t in allrows
                if all((t["status"] == v if k == "status" else t["kind"] == v if k == "kind" else t["dut_firmware"] == v if k == "firmware"
                        else t["dut_profile"] == v if k == "profile" else t["run_id"] == v if k == "run_id"
                        else runs[t["run_id"]]["sequence_id"] == v) for k, v in f.items())]
        got = pstack.all_results(**f)
        assert [t["task_id"] for t in got] == [t["task_id"] for t in want], f"filter {f}"
        assert want, f"history fixture must contain rows for {f}"
    assert {t["status"] for t in pstack.all_results(status="ERROR")} == {"ERROR"}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1001}, {"limit": -1}, {"limit": "x"}, {"limit": 1.5}, {"offset": -1}, {"offset": "x"}])
def test_results_bad_paging_parameters(pstack: Stack, params: dict[str, Any]) -> None:
    r = pstack.api("GET", "/api/tests/results", params=params)
    assert r.status_code == 400 and assert_error_body(r.json(), "INVALID_ARGUMENT")


def test_results_limit_boundaries_accepted(pstack: Stack, history: dict[str, str]) -> None:
    assert len(pstack.api_json("GET", "/api/tests/results", params={"limit": 1})["results"]) == 1
    assert pstack.api_json("GET", "/api/tests/results", params={"limit": 1000})["limit"] == 1000


def test_runs_endpoint_filters_pagination_and_consistency(pstack: Stack, history: dict[str, str]) -> None:
    runs = pstack.all_runs()
    validate({"total": len(runs), "runs": runs}, RUNS, "runs")
    stamps = [ts(r["created_at"]) for r in runs]
    assert stamps == sorted(stamps, reverse=True)
    assert len({r["run_id"] for r in runs}) == len(runs)
    assert pstack.api_json("GET", "/api/tests/runs", params={"limit": 3, "offset": 2})["runs"] == runs[2:5]
    for st_ in ("PASS", "FAIL", "ERROR"):
        sub = pstack.all_runs(status=st_)
        assert [r["run_id"] for r in sub] == [r["run_id"] for r in runs if r["status"] == st_] and sub
    assert {r["sequence_id"] for r in pstack.all_runs(sequence_id="thd_measurement")} == {"thd_measurement"}
    rows = pstack.all_results()
    for r in runs:                                  # run counts == persisted task rows
        mine = [t for t in rows if t["run_id"] == r["run_id"]]
        for s_ in ("PASS", "FAIL", "ERROR", "CANCELLED"):
            assert r["counts"][s_] == sum(1 for t in mine if t["status"] == s_), (r["run_id"], s_)
    assert pstack.api("GET", "/api/tests/runs", params={"limit": 0}).status_code == 400


def test_history_fixture_outcomes_match_expectations(pstack: Stack, history: dict[str, str]) -> None:
    by = {r["run_id"]: r for r in pstack.all_runs()}
    st = {k: by[v]["status"] for k, v in history.items()}
    assert st == {"normal": "PASS", "lowgain": "FAIL", "fw110": "PASS", "fw120": "FAIL", "highthd": "FAIL", "noisy": "FAIL",
                  "sweep": "PASS", "gain": "PASS", "timeout": "ERROR", "recovered": "PASS"}, st


# ================================================================================= reports
def test_reports_list_and_downloads(pstack: Stack, history: dict[str, str]) -> None:
    body = pstack.api_json("GET", "/api/reports")
    validate(body, REPORTS, "reports")
    runs = {r["run_id"]: r for r in pstack.all_runs()}
    reps = body["reports"]
    assert {r["run_id"] for r in reps} == set(runs), "a report must exist for every finished run"
    stamps = [ts(r["created_at"]) for r in reps]
    assert stamps == sorted(stamps, reverse=True)
    for r in reps:
        assert r["counts"] == runs[r["run_id"]]["counts"] and r["status"] == runs[r["run_id"]]["status"]
        for ext in ("csv", "html", "pdf"):
            assert r["files"][ext] == f"/api/reports/{r['run_id']}.{ext}"
    rid = history["normal"]
    ctypes = {"csv": "text/csv", "html": "text/html", "pdf": "application/pdf"}
    for ext, ct in ctypes.items():
        resp = pstack.api("GET", f"/api/reports/{rid}.{ext}")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].lower().startswith(ct), resp.headers["Content-Type"]
        if ext == "html":
            assert "charset=utf-8" in resp.headers["Content-Type"].lower()
        assert resp.headers["Content-Disposition"] == f'attachment; filename="{rid}.{ext}"'
        assert int(resp.headers["Content-Length"]) == len(resp.content) > 100
    assert pstack.api("GET", f"/api/reports/{rid}.pdf").content.startswith(b"%PDF-")
    assert pstack.api("GET", f"/api/reports/{rid}.pdf").content.rstrip().endswith(b"%%EOF")
    on_disk = (pstack.reports_dir / f"{rid}.csv").read_bytes()
    assert pstack.api("GET", f"/api/reports/{rid}.csv").content == on_disk


@pytest.mark.parametrize("name", ["run-20000101-000000-ffff.csv", "run-20000101-000000-ffff.html", "run-20000101-000000-ffff.pdf",
                                  "unknown.csv", "run-x.pdf"])
def test_report_unknown_id_is_404(pstack: Stack, name: str) -> None:
    r = pstack.api("GET", f"/api/reports/{name}")
    assert r.status_code == 404 and assert_error_body(r.json(), "NOT_FOUND")


def test_report_wrong_extension_or_missing_extension(pstack: Stack, history: dict[str, str]) -> None:
    rid = history["normal"]
    for suffix in (".xml", ".txt", "", ".csv.bak", ".CSV", ".json", "."):
        r = pstack.api("GET", f"/api/reports/{rid}{suffix}")
        assert r.status_code in (400, 404), f"{suffix!r}: {r.status_code}"
        assert_error_body(r.json())


TRAVERSAL = ["../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..%5c..%5cetc%5cpasswd",
             "%252e%252e%252f%252e%252e%252fetc%252fpasswd", "....//....//etc/passwd", "..", ".", "%00", "run-1%00",
             "a/b", "a%2fb", "a%20b", "a*", "x" * 65, "%C3%BC", "..%c0%af..%c0%afetc%c0%afpasswd", "run-20000101-000000-ffff/../../../etc/passwd"]


@pytest.mark.parametrize("payload", TRAVERSAL)
@pytest.mark.parametrize("ext", ["csv", "pdf"])
def test_report_download_path_traversal_is_rejected(pstack: Stack, payload: str, ext: str) -> None:
    status, headers, body = raw(pstack, "GET", f"/api/reports/{payload}.{ext}")
    assert status in (400, 404), f"{payload}: {status}"
    assert b"root:" not in body and b"/bin/" not in body
    if headers.get("content-type", "").startswith("application/json"):
        assert_error_body(json.loads(body))
    # the same payload must not be reachable through the run_id parameters either
    for path in (f"/api/tests/status?run_id={payload}", f"/api/tests/cancel"):
        if path.endswith("cancel"):
            s2, h2, b2 = raw(pstack, "POST", path, json.dumps({"run_id": payload.replace('%', '')}).encode(), {"Content-Type": "application/json"})
        else:
            s2, h2, b2 = raw(pstack, "GET", path)
        assert s2 in (400, 404, 409), f"{path} -> {s2}"
        assert b"root:" not in b2


@pytest.mark.parametrize("path", ["/../../../../etc/passwd", "/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "/assets/..%2f..%2f..%2fetc%2fpasswd",
                                  "/..%2f..%2f..%2fetc%2fpasswd", "/static/../../../../etc/passwd", "//etc/passwd", "/%5c..%5c..%5cetc%5cpasswd",
                                  "/..\\..\\..\\etc\\passwd", "/index.html/../../../../../etc/passwd"])
def test_static_file_serving_does_not_traverse(pstack: Stack, path: str) -> None:
    status, headers, body = raw(pstack, "GET", path)
    assert b"root:" not in body, "static handler leaked a file outside frontend/dist"
    assert b"nobody:" not in body
    assert status in (200, 400, 403, 404)
    if status == 200:            # SPA fallback is fine, but then it must be the index page
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()


def test_static_index_and_spa_fallback_when_frontend_is_present(pstack: Stack, repo_root: Any) -> None:
    dist = repo_root / "frontend" / "dist" / "index.html"
    if not dist.is_file():
        pytest.skip("frontend/dist not built")
    r = pstack.api("GET", "/")
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("text/html") and r.content == dist.read_bytes()
    spa = pstack.api("GET", "/sequences")
    assert spa.status_code == 200 and spa.content == dist.read_bytes(), "client-side routes must fall back to index.html"
    assert pstack.api("GET", "/api/definitely-not-there").headers["Content-Type"].startswith("application/json"), "API 404s must stay JSON"


# ---- summary statistics ------------------------------------------------------------------------------------
def _stat_close(a: Optional[float], b: Optional[float], tol: float = 2e-4) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def test_summary_statistics_equal_independent_recomputation(pstack: Stack, history: dict[str, str]) -> None:
    rows = pstack.all_results()
    runs = pstack.all_runs()
    s = pstack.api_json("GET", "/api/reports/summary")
    validate(s, SUMMARY, "summary")
    # runs
    assert s["runs"]["total"] == len(runs)
    for k in ("PASS", "FAIL", "ERROR", "CANCELLED"):
        assert s["runs"][k] == sum(1 for r in runs if r["status"] == k), f"runs.{k}"
    # tasks
    n = len(rows)
    assert s["tasks"]["total"] == n
    for k in ("PASS", "FAIL", "ERROR", "CANCELLED"):
        assert s["tasks"][k] == sum(1 for t in rows if t["status"] == k), f"tasks.{k}"
    assert _stat_close(s["tasks"]["pass_rate"], sum(1 for t in rows if t["status"] == "PASS") / n, 1e-3), "pass_rate = PASS / total"

    def agg(sub: list[dict[str, Any]]) -> dict[str, Any]:
        vals = [t["measured"]["value"] for t in sub if t["measured"] is not None]
        return {"count": len(sub), "pass": sum(t["status"] == "PASS" for t in sub), "fail": sum(t["status"] == "FAIL" for t in sub),
                "error": sum(t["status"] == "ERROR" for t in sub), "vals": vals}

    def check_stats(stats: dict[str, Any], sub: list[dict[str, Any]], where: str) -> None:
        a = agg(sub)
        assert stats["count"] in (a["count"], a["pass"] + a["fail"] + a["error"]), f"{where}: count"
        if "pass" in stats:
            assert (stats["pass"], stats["fail"], stats["error"]) == (a["pass"], a["fail"], a["error"]), f"{where}: pass/fail/error"
        v = a["vals"]
        assert _stat_close(stats["mean"], statistics.fmean(v)), f"{where}: mean {stats['mean']} vs {statistics.fmean(v)}"
        assert _stat_close(stats["min"], min(v)) and _stat_close(stats["max"], max(v)), f"{where}: min/max"
        sample, pop = statistics.stdev(v), statistics.pstdev(v)
        assert _stat_close(stats["std"], sample) or _stat_close(stats["std"], pop), f"{where}: std {stats['std']} vs sample {sample} / population {pop}"
        assert stats["unit"] == ta.KIND_UNIT[sub[0]["kind"]], f"{where}: unit {stats['unit']}"

    kinds = sorted({t["kind"] for t in rows})
    assert set(s["by_kind"]) == set(kinds), f"by_kind keys {set(s['by_kind'])} vs task kinds {set(kinds)}"
    for k in kinds:
        sub = [t for t in rows if t["kind"] == k]
        assert len([t for t in sub if t["measured"]]) >= 2
        check_stats(s["by_kind"][k], sub, f"by_kind[{k}]")
    fws = {t["dut_firmware"] for t in rows}
    assert {f["firmware"] for f in s["by_firmware"]} == fws
    for f in s["by_firmware"]:
        sub = [t for t in rows if t["dut_firmware"] == f["firmware"]]
        assert f["tasks"] == len(sub)
        assert (f["pass"], f["fail"], f["error"]) == tuple(sum(t["status"] == k for t in sub) for k in ("PASS", "FAIL", "ERROR"))
        assert _stat_close(f["pass_rate"], f["pass"] / len(sub), 1e-3)
        for k, st_ in f["by_kind"].items():
            sk = [t for t in sub if t["kind"] == k]
            vals = [t["measured"]["value"] for t in sk if t["measured"]]
            assert st_["count"] in (len(sk), len(vals)) and _stat_close(st_["mean"], statistics.fmean(vals)), f"fw {f['firmware']} {k}"
    # failure reasons = histogram of error_code over non-PASS tasks
    hist: dict[str, int] = {}
    for t in rows:
        if t["error_code"]:
            hist[t["error_code"]] = hist.get(t["error_code"], 0) + 1
    assert {r["reason"]: r["count"] for r in s["failure_reasons"]} == hist
    counts = [r["count"] for r in s["failure_reasons"]]
    assert counts == sorted(counts, reverse=True), "failure reasons sorted by count"
    # recovery
    retried = [t for t in rows if t["attempts"] > 1]
    rec = s["recovery"]
    assert rec["tasks_with_retry"] == len(retried)
    assert rec["recovered"] == sum(t["status"] in ("PASS", "FAIL") for t in retried)
    assert rec["unrecovered"] == sum(t["status"] == "ERROR" for t in retried)
    assert rec["tasks_with_retry"] >= 2, "history fixture must contain recovered and unrecovered retries"
    assert _stat_close(rec["recovery_rate"], rec["recovered"] / rec["tasks_with_retry"], 1e-3)
    # trend: last 500 measured tasks, oldest first
    measured = sorted((t for t in rows if t["measured"] is not None), key=lambda t: (t["timestamp"], t["task_id"]))[-500:]
    assert len(s["trend"]) == len(measured) <= 500
    assert [p["timestamp"] for p in s["trend"]] == [t["timestamp"] for t in measured], "trend must be oldest-first"
    assert [p["run_id"] for p in s["trend"]] == [t["run_id"] for t in measured]
    assert all(_stat_close(p["value"], t["measured"]["value"], 1e-6) for p, t in zip(s["trend"], measured))


def test_summary_sequence_filter_and_unknown_parameters(pstack: Stack, history: dict[str, str]) -> None:
    rows = [t for t in pstack.all_results() if t["run_id"] == history["highthd"]]
    s = pstack.api_json("GET", "/api/reports/summary", params={"sequence_id": "thd_measurement"})
    runs = pstack.all_runs(sequence_id="thd_measurement")
    assert s["runs"]["total"] == len(runs) and s["tasks"]["total"] == len([t for t in pstack.all_results() if t["kind"] == "thd" and
                                                                           any(r["run_id"] == t["run_id"] for r in runs)])
    assert rows and set(s["by_kind"]) == {"thd"}
    r = pstack.api("GET", "/api/reports/summary", params={"sequence_id": "nope"})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.json()["tasks"]["total"] == 0


# ================================================================================= logs
def test_logs_shape_ordering_filters_and_pagination(connected: Stack) -> None:
    connected.command("siggen", "SOUR:FREQ 1234"); connected.command("siggen", "SOUR:FREQ?")
    body = connected.api_json("GET", "/api/logs", params={"limit": 1000})
    validate(body, LOGS, "logs")
    seqs = [e["seq"] for e in body["logs"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "oldest first, unique seq"
    assert body["last_seq"] >= seqs[-1]
    # SCPI log fields
    sc = [e for e in body["logs"] if e["source"] == "scpi" and (e["fields"] or {}).get("instrument") == "siggen"]
    sc = [e for e in sc if "direction" in e["fields"]]        # connection-level entries carry only the instrument
    tx = [e for e in sc if e["fields"]["direction"] == "TX" and e["fields"]["text"] in ("SOUR:FREQ 1234", "SOUR:FREQ?")]
    rx = [e for e in sc if e["fields"]["direction"] == "RX" and e["fields"]["text"] == "1234"]
    assert len(tx) >= 2 and rx, "TX/RX of the API commands must be logged with instrument/direction/text"
    assert all(isinstance(e["fields"]["duration_ms"], (int, float)) for e in rx)
    # since_seq: only newer entries
    mark = body["last_seq"]
    connected.command("siggen", "*OPC?")
    newer = connected.api_json("GET", "/api/logs", params={"since_seq": mark, "limit": 1000})
    assert newer["logs"] and all(e["seq"] > mark for e in newer["logs"])
    assert any((e["fields"] or {}).get("text") == "*OPC?" for e in newer["logs"] if e["source"] == "scpi")
    assert connected.api_json("GET", "/api/logs", params={"since_seq": newer["last_seq"]})["logs"] == []
    # `limit` returns the NEWEST `limit` entries after since_seq, still oldest-first
    page = connected.api_json("GET", "/api/logs", params={"since_seq": 0, "limit": 5})
    seqs5 = [e["seq"] for e in page["logs"]]
    assert len(seqs5) == 5 and seqs5 == sorted(seqs5)
    assert seqs5[-1] == page["last_seq"] or page["last_seq"] > seqs5[-1]
    assert seqs5[0] > body["logs"][0]["seq"], "tail semantics: older entries are cut, not newer ones"
    # filters
    only = connected.api_json("GET", "/api/logs", params={"source": "scpi", "limit": 1000})["logs"]
    assert only and {e["source"] for e in only} == {"scpi"}
    errs = connected.api_json("GET", "/api/logs", params={"level": "error", "limit": 1000})["logs"]
    assert all(e["level"] == "error" for e in errs)


def test_comm_errors_are_logged_with_level_error_and_kind(connected: Stack) -> None:
    connected.scpi("analyzer", "MF:FAULT:TIMEOUT 50,3000")
    mark = connected.logs_since(0, 1)["last_seq"]
    r = connected.api("POST", "/api/instruments/command", {"id": "analyzer", "command": "*IDN?"})
    assert r.status_code == 504
    errs = [e for e in connected.logs_since(mark, 500, level="error")["logs"] if e["source"] in ("scpi", "api", "system")]
    assert errs and any((e["fields"] or {}).get("kind") for e in errs), errs[:3]
    connected.scpi("analyzer", "MF:FAULT:CLEAR")


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"limit": "x"}, {"since_seq": -1}, {"since_seq": "x"}])
def test_logs_parameter_validation(pstack: Stack, params: dict[str, Any]) -> None:
    r = pstack.api("GET", "/api/logs", params=params)
    assert r.status_code == 400 and assert_error_body(r.json(), "INVALID_ARGUMENT")


@pytest.mark.parametrize("params", [{"level": "bogus"}, {"source": "bogus"}])
def test_logs_unknown_filter_values_never_return_unrelated_entries(pstack: Stack, params: dict[str, Any]) -> None:
    r = pstack.api("GET", "/api/logs", params=params)
    assert r.status_code == 400 or (r.status_code == 200 and r.json()["logs"] == []), r.text[:200]
    if r.status_code == 400:
        assert_error_body(r.json(), "INVALID_ARGUMENT")


def test_logs_are_also_persisted_as_json_lines(connected: Stack) -> None:
    connected.command("siggen", "*OPC?")
    p = connected.results_dir / "logs" / "measureflow.jsonl"
    wait_until(lambda: p.is_file() and p.stat().st_size > 0, what="jsonl log")
    lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert lines and all({"seq", "ts", "level", "source", "message"} <= set(x) for x in lines[:50])


# ================================================================================= protocol-level behaviour
@pytest.mark.parametrize("method,path", [("GET", "/api/nope"), ("GET", "/api/"), ("GET", "/api/instruments/nope"), ("POST", "/api/health"),
                                         ("GET", "/api/tests/run"), ("GET", "/api/instruments/connect"), ("PUT", "/api/instruments/connect"),
                                         ("DELETE", "/api/tests/results"), ("POST", "/api/instruments"), ("PATCH", "/api/health"),
                                         ("GET", "/api/tests/cancel"), ("POST", "/api/sequences"), ("POST", "/api/reports/summary")])
def test_unknown_routes_and_wrong_methods_use_unified_error_body(pstack: Stack, method: str, path: str) -> None:
    r = pstack.api(method, path, json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code in (404, 405), f"{method} {path}: {r.status_code}"
    assert r.headers["Content-Type"].startswith("application/json"), "error responses must be JSON"
    assert_error_body(r.json())


@pytest.mark.parametrize("endpoint", ["/api/instruments/connect", "/api/instruments/disconnect", "/api/instruments/command",
                                      "/api/instruments/configure", "/api/tests/run"])
@pytest.mark.parametrize("body", [b"", b"{", b'{"id":', b"nul", b"[]", b'"str"', b"42", b"null", b'{"id":"siggen",}', b"{'id':'siggen'}",
                                  b'{"id": NaN}', b"\xef\xbb\xbf{}", b"\xff\xfe", b'{"a":' * 50])
def test_malformed_json_bodies_are_400_invalid_argument(pstack: Stack, endpoint: str, body: bytes) -> None:
    r = post_raw(pstack, endpoint, body)
    assert r.status_code == 400, f"{endpoint} {body[:30]!r}: {r.status_code} {r.text[:200]}"
    assert_error_body(r.json(), "INVALID_ARGUMENT")


def test_deeply_nested_json_does_not_crash_the_server(pstack: Stack) -> None:
    depth = 20000
    body = ("[" * depth + "]" * depth).encode()
    try:
        r = post_raw(pstack, "/api/tests/run", body)
        assert r.status_code in (400, 413)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"server dropped the connection / crashed on deeply nested JSON: {exc!r}")
    assert pstack.api("GET", "/api/health").status_code == 200 and pstack.backend_pid is not None


SIMPLE_CTYPES = ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", None, "application/xml"]


@pytest.mark.parametrize("ctype", SIMPLE_CTYPES)
def test_cross_site_simple_requests_are_refused_and_have_no_side_effect(pstack: Stack, ctype: Optional[str]) -> None:
    """CSRF: a hostile page can send 'simple' cross-origin POSTs (no pre-flight). The browser always attaches ``Origin``;
    the backend must refuse foreign origins before acting, whatever the content type."""
    runs0 = len(pstack.all_runs())
    for path, body in (("/api/instruments/connect", b'{"id":"siggen"}'),
                       ("/api/tests/run", b'{"sequence_id":"gain_verification"}'),
                       ("/api/instruments/command", b'{"id":"siggen","command":"OUTP ON"}')):
        h = {"Origin": "http://evil.example"}
        if ctype:
            h["Content-Type"] = ctype
        r = pstack.api("POST", path, data=body, headers=h)
        # multipart bodies are rejected by the HTTP layer as a malformed request (400) before the origin check
        refused = (400, 403) if (ctype or "").startswith("multipart/") else (403,)
        assert r.status_code in refused, f"{path} {ctype!r}: {r.status_code} {r.text[:200]}"
        assert_error_body(r.json())
    assert inst_state(pstack, "siggen") == "disconnected"
    assert len(pstack.all_runs()) == runs0


@pytest.mark.parametrize("ctype", SIMPLE_CTYPES)
def test_non_json_content_type_without_origin_is_either_rejected_or_harmless(pstack: Stack, ctype: Optional[str]) -> None:
    """The contract says bodies are JSON but does not require 415 (see QA_REVIEW QA-005): both behaviours are accepted,
    but a rejection must carry the unified error body and then have no side effect."""
    r = post_raw(pstack, "/api/instruments/connect", b'{"id":"siggen"}', ctype)
    assert r.status_code in (200, 400, 415), f"{ctype!r}: {r.status_code}"
    if r.status_code != 200:
        assert_error_body(r.json())
        assert inst_state(pstack, "siggen") == "disconnected"


@pytest.mark.parametrize("ctype", ["application/json", "application/json; charset=utf-8", "Application/JSON", "application/json;charset=UTF-8"])
def test_json_content_type_variants_are_accepted(pstack: Stack, ctype: str) -> None:
    r = post_raw(pstack, "/api/instruments/connect", b'{"id":"siggen"}', ctype)
    assert r.status_code == 200, f"{ctype}: {r.status_code} {r.text}"


@pytest.mark.parametrize("endpoint", ["/api/tests/run", "/api/instruments/command", "/api/instruments/connect"])
def test_huge_request_bodies_are_rejected_and_server_survives(pstack: Stack, endpoint: str) -> None:
    huge = b'{"sequence_id":"' + b"A" * (12 * 1024 * 1024) + b'"}'
    try:
        r = post_raw(pstack, endpoint, huge)
        assert r.status_code in (400, 413), f"{r.status_code}"
        assert_error_body(r.json())
    except Exception as exc:  # noqa: BLE001
        import requests
        if not isinstance(exc, requests.ConnectionError):
            raise
        # connection reset while uploading is an acceptable way to refuse - but the server must live
    assert pstack.api("GET", "/api/health").status_code == 200


def test_many_long_header_and_url_do_not_crash(pstack: Stack) -> None:
    status, _, _ = raw(pstack, "GET", "/api/health?" + "a=1&" * 5000)
    assert status in (200, 400, 414, 431)
    status, _, _ = raw(pstack, "GET", "/api/health", headers={"X-Long": "v" * 70000})
    assert status in (200, 400, 431)
    assert pstack.api("GET", "/api/health").status_code == 200


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_cors_allowed_origins_get_exact_echo(pstack: Stack, origin: str) -> None:
    r = pstack.api("GET", "/api/health", headers={"Origin": origin})
    assert r.headers.get("Access-Control-Allow-Origin") == origin
    assert r.headers.get("Access-Control-Allow-Origin") != "*"
    err = pstack.api("GET", "/api/nope", headers={"Origin": origin})
    assert err.headers.get("Access-Control-Allow-Origin") == origin, "error responses must carry CORS headers too"
    pre = pstack.api("OPTIONS", "/api/tests/run", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                          "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code in (200, 204)
    assert pre.headers.get("Access-Control-Allow-Origin") == origin
    assert "POST" in pre.headers.get("Access-Control-Allow-Methods", "").upper()
    assert "content-type" in pre.headers.get("Access-Control-Allow-Headers", "").lower()


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_cors_other_origins_are_not_allowed(pstack: Stack, origin: str) -> None:
    for method, path, extra in [("GET", "/api/health", {}), ("OPTIONS", "/api/tests/run", {"Access-Control-Request-Method": "POST"})]:
        r = pstack.api(method, path, headers={"Origin": origin, **extra})
        acao = r.headers.get("Access-Control-Allow-Origin")
        assert acao not in (origin, "*"), f"{method} {path} from {origin!r} got ACAO {acao!r}"


def test_cors_no_origin_header_means_no_cors_headers_needed(pstack: Stack) -> None:
    r = pstack.api("GET", "/api/health")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") != "*"


def test_bind_address_is_loopback_only(pstack: Stack) -> None:
    pid = pstack.backend_pid
    assert pid is not None
    listening = []
    for proto in ("tcp", "tcp6"):
        try:
            lines = open(f"/proc/net/{proto}").read().splitlines()[1:]
        except FileNotFoundError:
            continue
        for ln in lines:
            f = ln.split()
            local, state = f[1], f[3]
            if state != "0A":
                continue
            addr_hex, port_hex = local.rsplit(":", 1)
            if int(port_hex, 16) == pstack.backend_port:
                listening.append((proto, addr_hex))
    assert listening, "backend listening socket not found"
    for proto, addr in listening:
        assert addr in ("0100007F", "00000000000000000000000001000000"), f"backend bound to non-loopback address {proto}:{addr}"


def test_backend_refuses_non_loopback_bind_without_flag(pstack: Stack, backend_bin: Any, tmp_path: Any) -> None:
    import subprocess
    try:
        p = subprocess.run([str(backend_bin), "--root", str(pstack.mf_root), "--host", "0.0.0.0", "--port", "0"],
                           capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pytest.fail("backend started on 0.0.0.0 without --unsafe-bind")
    assert p.returncode != 0, "must refuse to bind 0.0.0.0 without --unsafe-bind"
    assert "unsafe" in (p.stdout + p.stderr).lower() or "loopback" in (p.stdout + p.stderr).lower()
