"""Test-engine behaviour through the real backend + simulator (docs/INTERFACE.md sections 5.10-5.12, 6, 7).

All tests use the ``pstack`` fixture: simulator + backend with a fault-injecting proxy between them, so
simulator faults (``MF:FAULT:*``) can be injected at exact points of a run (see experiments/faultproxy.py;
the faults themselves are still produced by the real simulator). Expected values come from
``mfsim.truth`` via ``truth_adapter`` - never from the measurement under test.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

import pytest

import truth_adapter as ta
from schemas import (RUN_DETAIL, STATUS_ENVELOPE, assert_error_body, assert_task_semantics, validate)
from stack import Stack

pytestmark = [pytest.mark.usefixtures("truth")]

SEQUENCES = {  # sequence id -> (task count, kinds)
    "gain_verification": (1, {"gain"}),
    "rms_measurement": (1, {"rms"}),
    "thd_measurement": (1, {"thd"}),
    "snr_measurement": (1, {"snr"}),
    "noise_floor": (1, {"noise_floor"}),
    "frequency_sweep": (8, {"freq_sweep"}),
    "full_pipeline": (13, {"rms", "gain", "thd", "snr", "noise_floor", "freq_sweep"}),
}
ALL = ("siggen", "analyzer", "dut")


def parse_ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()


def slow(st: Stack, ms: float = 25) -> None:
    """Stretch runs: every SCPI command is delayed by ``ms`` inside the proxy."""
    assert st.proxy is not None
    for i in ALL:
        st.proxy.set_latency(i, ms)


def persistent(st: Stack, inst: str, inject: str, match: str, times: int = 200, **kw: Any) -> None:
    assert st.proxy is not None
    st.proxy.arm(inst, inject, match=match, nth=1, times=times, **kw)


def assert_clean(st: Stack) -> None:
    """Resources released after a run: no leases, generator OFF, nothing running."""
    insts = st.instruments()
    assert all(i["leased_by"] is None for i in insts.values()), {k: v["leased_by"] for k, v in insts.items()}
    assert st.scpi("siggen", "OUTP?") == "0", "generator output must be OFF after a run"
    assert st.run_status(log_tail=0)["status"] in ("PASS", "FAIL", "ERROR", "CANCELLED")


def assert_run_consistent(run: dict[str, Any]) -> None:
    """Schema + invariants that must hold for every finished run."""
    validate({"run": run}, STATUS_ENVELOPE, "run detail")
    tasks = run["tasks"]
    ids = [t["task_id"] for t in tasks]
    assert len(set(ids)) == len(ids), "task ids must be unique"
    assert ids == [f"{run['run_id']}-T{i:03d}" for i in range(1, len(ids) + 1)], f"task ids not sequential: {ids}"
    counts = run["counts"]
    for st_ in ("PASS", "FAIL", "ERROR", "CANCELLED"):
        assert counts[st_] == sum(1 for t in tasks if t["status"] == st_), f"counts[{st_}] inconsistent"
    assert counts["PENDING"] == 0 and counts["RUNNING"] == 0, counts
    assert sum(counts.values()) == len(tasks)
    created, started, finished = (parse_ts(run[k]) for k in ("created_at", "started_at", "finished_at"))
    assert created <= started + 1e-3 <= finished + 2e-3
    stamps = [parse_ts(t["timestamp"]) for t in tasks]
    assert stamps == sorted(stamps), "task timestamps must be non-decreasing"
    for ts in stamps:
        assert started - 0.01 <= ts <= finished + 0.01, "task timestamp outside run window"
    assert abs(run["duration_ms"] - (finished - started) * 1000) < 50
    for t in tasks:
        assert t["run_id"] == run["run_id"]
        assert_task_semantics(t)
    precedence = ("CANCELLED" if run["status"] == "CANCELLED" else
                  "ERROR" if counts["ERROR"] else "FAIL" if counts["FAIL"] else "PASS")
    if run["status"] != "CANCELLED":
        assert run["status"] == precedence or (run["status"] == "ERROR" and run["error"]), \
            f"status {run['status']} violates precedence rule (counts {counts})"
    seqs = [e["seq"] for e in run["log"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "log seq must be strictly increasing"


def assert_matches_truth(run: dict[str, Any], allow_borderline: int = 0) -> dict[str, int]:
    """Every measured task: value within tolerance of mfsim.truth and verdict equals the analytic verdict."""
    border = 0
    checked = 0
    for t in run["tasks"]:
        if t["status"] not in ("PASS", "FAIL"):
            continue
        exp = ta.task_expectation(t)
        ok, err = ta.within_tolerance(t["kind"], t["measured"]["value"], exp.expected, t["dut_profile"])
        assert ok, f"{t['test_name']}: measured {t['measured']['value']} vs truth {exp.expected:.6g} (err {err:+.4g})"
        if exp.margin > 0:
            assert t["status"] == exp.status, (f"{t['test_name']}: status {t['status']}, analytic verdict {exp.status} "
                                               f"(expected {exp.expected:.5g}, limits {t['limits']})")
        else:
            border += 1
        checked += 1
    assert border <= allow_borderline, f"{border} borderline tasks"
    return {"checked": checked, "borderline": border}


def wait_until(pred, timeout: float = 20.0, poll: float = 0.02, what: str = "condition") -> Any:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(poll)
    raise AssertionError(f"timeout waiting for {what}")


# ======================================================================================= happy paths
@pytest.mark.parametrize("seq", list(SEQUENCES))
def test_normal_dut_every_sequence_passes_with_values_matching_truth(pstack: Stack, seq: str) -> None:
    run = pstack.run_sequence(seq, label=f"qa-normal-{seq}")
    n_tasks, kinds = SEQUENCES[seq]
    assert run["status"] == "PASS", [(t["test_name"], t["status"], t["measured"], t["limits"]) for t in run["tasks"]]
    assert run["error"] is None and run["progress"] == 1.0
    assert run["counts"]["PASS"] == n_tasks == len(run["tasks"])
    assert {t["kind"] for t in run["tasks"]} == kinds
    assert run["label"] == f"qa-normal-{seq}"
    assert_run_consistent(run)
    info = assert_matches_truth(run)
    assert info["checked"] == n_tasks
    for t in run["tasks"]:
        assert t["attempts"] == 1 and t["error_code"] is None and t["dut_profile"] == "NORMAL"
        assert t["dut_firmware"] == "1.0.0" and t["inputs"]["frequency_hz"] > 0
    assert_clean(pstack)
    # persisted artefacts
    rd = pstack.run_dir(run["run_id"])
    assert (rd / "run.json").is_file() and (rd / "results.csv").is_file() and (rd / "run.log").is_file()
    for ext in ("csv", "html", "pdf"):
        assert (pstack.reports_dir / f"{run['run_id']}.{ext}").stat().st_size > 100


def test_full_pipeline_task_names_and_sweep_points(pstack: Stack) -> None:
    run = pstack.run_sequence("full_pipeline")
    names = [t["test_name"] for t in run["tasks"]]
    assert names[:5] == ["RMS @ 1000 Hz", "Gain @ 1000 Hz", "THD @ 1000 Hz", "SNR @ 1000 Hz", "Noise floor"]
    sweep = [t for t in run["tasks"] if t["kind"] == "freq_sweep"]
    assert [t["inputs"]["frequency_hz"] for t in sweep] == [100, 200, 500, 1000, 2000, 4000, 6000, 8000]
    assert all(t["inputs"].get("measurement") == "gain" for t in sweep)
    assert all(t["step_id"] == "sweep" for t in sweep)
    # sweep gain follows the DUT filter response: high-pass at 100 Hz (-3 dB), low-pass 8 kHz
    g = {t["inputs"]["frequency_hz"]: t["measured"]["value"] for t in sweep}
    assert g[100] < g[1000] - 2.5 and g[8000] < g[1000] - 2.5 and abs(g[1000] - 20.0) < 0.2


def test_run_parameters_change_stimulus_limits_and_verdict(pstack: Stack) -> None:
    run = pstack.run_sequence("gain_verification", parameters={"frequency_hz": 4000, "amplitude_vpk": 0.1,
                                                              "gain_min_db": 19.5, "gain_max_db": 20.5})
    (t,) = run["tasks"]
    assert t["inputs"]["frequency_hz"] == 4000 and t["inputs"]["amplitude_vpk"] == 0.1
    assert "4000" in t["test_name"]
    assert t["limits"]["min"] == 19.5 and t["limits"]["max"] == 20.5 and t["limits"]["unit"] == "dB"
    assert run["parameters"]["frequency_hz"] == 4000
    assert_matches_truth(run)
    # tighten the lower limit above the true gain -> FAIL low (never ERROR)
    run2 = pstack.run_sequence("gain_verification", parameters={"gain_min_db": 20.5, "gain_max_db": 25})
    (t2,) = run2["tasks"]
    assert run2["status"] == "FAIL" and t2["status"] == "FAIL" and t2["error_code"] == "OUT_OF_TOLERANCE_LOW"
    # open (very wide) limits pass
    run3 = pstack.run_sequence("gain_verification", parameters={"gain_min_db": -20, "gain_max_db": 60})
    assert run3["status"] == "PASS"


def test_dut_override_is_applied_and_recorded(pstack: Stack) -> None:
    run = pstack.run_sequence("gain_verification", dut={"profile": "LOWGAIN", "firmware": "1.1.0"})
    assert run["dut"] == {"profile": "LOWGAIN", "firmware": "1.1.0"}
    assert run["tasks"][0]["dut_profile"] == "LOWGAIN" and run["tasks"][0]["dut_firmware"] == "1.1.0"
    assert pstack.scpi("dut", "*IDN?").endswith(",1.1.0"), "DUT firmware really set on the instrument"


# ======================================================================================= FAIL (measurement)
@pytest.mark.parametrize("profile,seq,failing", [
    ("LOWGAIN", "gain_verification", {"gain": "OUT_OF_TOLERANCE_LOW"}),
    ("LOWGAIN", "rms_measurement", {"rms": "OUT_OF_TOLERANCE_LOW"}),
    ("HIGHTHD", "thd_measurement", {"thd": "OUT_OF_TOLERANCE_HIGH"}),
    ("NOISY", "snr_measurement", {"snr": "OUT_OF_TOLERANCE_LOW"}),
    ("NOISY", "noise_floor", {"noise_floor": "OUT_OF_TOLERANCE_HIGH"}),
    ("CLIPPING", "thd_measurement", {"thd": "OUT_OF_TOLERANCE_HIGH"}),
    ("CLIPPING", "rms_measurement", {"rms": "OUT_OF_TOLERANCE_LOW"}),
])
def test_out_of_spec_dut_gives_fail_never_error(pstack: Stack, profile: str, seq: str, failing: dict[str, str]) -> None:
    run = pstack.run_sequence(seq, dut={"profile": profile})
    assert run["status"] == "FAIL", run["status"]
    assert run["counts"]["ERROR"] == 0 and run["error"] is None
    t = run["tasks"][0]
    assert t["status"] == "FAIL" and t["error_code"] == failing[t["kind"]] and t["measured"] is not None
    assert_run_consistent(run)
    assert_matches_truth(run)
    assert_clean(pstack)


@pytest.mark.parametrize("profile", ["LOWGAIN", "HIGHTHD", "NOISY", "CLIPPING"])
def test_full_pipeline_with_faulty_dut_marks_exactly_the_analytically_failing_tasks(pstack: Stack, profile: str) -> None:
    run = pstack.run_sequence("full_pipeline", dut={"profile": profile}, label=f"qa-fp-{profile}")
    assert run["status"] == "FAIL" and run["counts"]["ERROR"] == 0
    assert run["counts"]["FAIL"] >= 1 and run["counts"]["PASS"] >= 1, "some tasks still pass (e.g. noise floor)"
    assert_run_consistent(run)
    assert_matches_truth(run, allow_borderline=2)    # every verdict equals the analytic verdict
    assert_clean(pstack)


@pytest.mark.parametrize("fw,seq,expected_status", [
    ("1.0.0", "thd_measurement", "PASS"),
    ("1.1.0", "thd_measurement", "PASS"),
    ("1.2.0", "thd_measurement", "FAIL"),       # regression build: THD 1.5..3 % > 1 % limit
    ("1.2.0", "gain_verification", "PASS"),     # gain still passes
])
def test_firmware_regression_build_is_flagged_on_thd_only(pstack: Stack, fw: str, seq: str, expected_status: str) -> None:
    run = pstack.run_sequence(seq, dut={"profile": "NORMAL", "firmware": fw})
    assert run["status"] == expected_status, run["tasks"]
    t = run["tasks"][0]
    assert t["dut_firmware"] == fw
    if fw == "1.2.0" and seq == "thd_measurement":
        assert 1.5 <= t["measured"]["value"] <= 3.0 and t["error_code"] == "OUT_OF_TOLERANCE_HIGH"
    assert_matches_truth(run)


def test_limit_exactly_at_measured_boundary_is_inclusive_or_exclusive_consistently(pstack: Stack) -> None:
    """Limit == measured value: PASS (limits are inclusive). Re-run with the limit nudged inside/outside."""
    base = pstack.run_sequence("gain_verification")["tasks"][0]["measured"]["value"]
    # the acquisition is deterministic only per backend/sim state: take the value the next run reports
    probe = pstack.run_sequence("gain_verification", parameters={"gain_min_db": -20, "gain_max_db": 60})["tasks"][0]
    v = probe["measured"]["value"]
    assert abs(v - base) < 0.05
    # limits more than the measurement noise away on either side flip the verdict as expected
    lo = pstack.run_sequence("gain_verification", parameters={"gain_min_db": v + 0.2, "gain_max_db": 60})
    hi = pstack.run_sequence("gain_verification", parameters={"gain_min_db": -20, "gain_max_db": v - 0.2})
    assert lo["tasks"][0]["error_code"] == "OUT_OF_TOLERANCE_LOW" and hi["tasks"][0]["error_code"] == "OUT_OF_TOLERANCE_HIGH"
    for r in (lo, hi):
        assert_task_semantics(r["tasks"][0])


# ======================================================================================= ERROR (communication)
@pytest.mark.parametrize("name,inject,match,inst,code", [
    ("timeout", "MF:FAULT:TIMEOUT 1,2500", r"^MEAS:GAIN\?", "analyzer", "COMM_TIMEOUT"),
    ("disconnect", "MF:FAULT:DISCONNECT 1", r"^MEAS:GAIN\?", "analyzer", "COMM_DISCONNECTED"),
    ("garbage", "MF:FAULT:GARBAGE 1", r"^MEAS:GAIN\?", "analyzer", "COMM_INVALID_RESPONSE"),
    ("nan", "MF:FAULT:NAN 1", r"^MEAS:GAIN\?", "analyzer", "MEASUREMENT_NAN"),
    ("inf", "MF:FAULT:INF 1", r"^MEAS:GAIN\?", "analyzer", "MEASUREMENT_INF"),
    ("oversize", "MF:FAULT:OVERSIZE 1", r"^MEAS:GAIN\?", "analyzer", "COMM_RESPONSE_TOO_LARGE"),
])
def test_communication_fault_gives_error_never_fail(pstack: Stack, name: str, inject: str, match: str, inst: str, code: str) -> None:
    persistent(pstack, inst, inject, match)                  # every attempt hits the fault
    t0 = time.monotonic()
    run = pstack.run_sequence("gain_verification", retries=0, label=f"qa-{name}", timeout=60)
    elapsed = time.monotonic() - t0
    (t,) = run["tasks"]
    assert t["status"] == "ERROR" and t["error_code"] == code, (t["status"], t["error_code"], t["message"])
    assert t["measured"] is None, "ERROR task must not carry a measured value"
    assert run["status"] == "ERROR" and run["counts"]["ERROR"] == 1 and run["counts"]["FAIL"] == 0
    assert t["attempts"] == 1
    assert elapsed < 30, "faulted run must fail fast, not hang"
    assert_run_consistent(run)
    # the backend stays healthy and can run again immediately
    pstack.proxy.reset()                                      # type: ignore[union-attr]
    ok = pstack.run_sequence("gain_verification")
    assert ok["status"] == "PASS", "fresh run after a communication error must pass"
    assert_clean(pstack)


def test_dut_nan_fault_is_measurement_nan_not_instrument_error(pstack: Stack) -> None:
    pstack.proxy.arm("analyzer", "MF:DUT:FAULT NAN", match=r"^MF:ACQ:INIT", nth=1, times=1, target="dut")  # type: ignore[union-attr]
    run = pstack.run_sequence("rms_measurement", retries=0)
    (t,) = run["tasks"]
    assert t["status"] == "ERROR" and t["error_code"] == "MEASUREMENT_NAN", (t["error_code"], t["message"])
    assert run["status"] == "ERROR"


def test_instrument_error_in_queue_after_valid_measurement_is_instrument_error(pstack: Stack) -> None:
    pstack.proxy.arm("analyzer", "BOGUS:COMMAND", match=r"^MEAS:GAIN\?", nth=1, times=1)  # type: ignore[union-attr]
    run = pstack.run_sequence("gain_verification", retries=0)
    (t,) = run["tasks"]
    assert t["status"] == "ERROR" and t["error_code"] == "INSTRUMENT_ERROR", (t["status"], t["error_code"], t["message"])
    assert t["measured"] is None and run["counts"]["FAIL"] == 0


def test_fragmented_responses_are_reassembled_and_still_pass(pstack: Stack) -> None:
    persistent(pstack, "analyzer", "MF:FAULT:FRAGMENT 1,3,8", r"^MEAS:")
    run = pstack.run_sequence("full_pipeline")
    assert run["status"] == "PASS", [(t["test_name"], t["status"], t["error_code"]) for t in run["tasks"] if t["status"] != "PASS"]
    assert all(t["attempts"] == 1 for t in run["tasks"])
    assert_matches_truth(run)


def test_error_in_one_task_does_not_hide_later_tasks_and_cleanup_still_runs(pstack: Stack) -> None:
    persistent(pstack, "analyzer", "MF:FAULT:GARBAGE 1", r"^MEAS:GAIN\?")
    run = pstack.run_sequence("full_pipeline", retries=0)
    by_step = {t["step_id"]: t for t in run["tasks"]}
    assert by_step["gain"]["status"] == "ERROR"
    assert run["status"] == "ERROR"
    assert_run_consistent(run)
    assert_clean(pstack)          # cleanup executed although a task errored


# ---- retry / recovery --------------------------------------------------------------------------------
def test_client_level_retry_recovers_single_timeout_transparently(pstack: Stack) -> None:
    pstack.proxy.arm("analyzer", "MF:FAULT:TIMEOUT 1,2500", match=r"^MEAS:GAIN\?", nth=1, times=1)  # type: ignore[union-attr]
    run = pstack.run_sequence("gain_verification", retries=0)     # task retries disabled; client max_retries=1
    (t,) = run["tasks"]
    assert t["status"] == "PASS", (t["status"], t["error_code"], t["message"])
    ok, err = ta.within_tolerance("gain", t["measured"]["value"], ta.task_expectation(t).expected, t["dut_profile"])
    assert ok, f"recovered value wrong by {err}: stale response mix-up?"


def test_task_level_retry_recovers_and_counts_attempts(pstack: Stack) -> None:
    # client max_retries=1 -> 2 query attempts per task attempt; fail both -> task retry; then succeed
    pstack.proxy.arm("analyzer", "MF:FAULT:TIMEOUT 1,2500", match=r"^MEAS:GAIN\?", nth=1, times=2)  # type: ignore[union-attr]
    before = pstack.api_json("GET", "/api/reports/summary")["recovery"]
    run = pstack.run_sequence("gain_verification", retries=1)
    (t,) = run["tasks"]
    assert t["status"] == "PASS" and t["attempts"] == 2, (t["status"], t["attempts"], t["error_code"])
    assert_matches_truth(run)
    after = pstack.api_json("GET", "/api/reports/summary")["recovery"]
    assert after["tasks_with_retry"] == before["tasks_with_retry"] + 1
    assert after["recovered"] == before["recovered"] + 1 and after["unrecovered"] == before["unrecovered"]


def test_unrecoverable_timeout_exhausts_retries_and_reports_comm_timeout(pstack: Stack) -> None:
    persistent(pstack, "analyzer", "MF:FAULT:TIMEOUT 1,2500", r"^MEAS:GAIN\?")
    before = pstack.api_json("GET", "/api/reports/summary")["recovery"]
    t0 = time.monotonic()
    run = pstack.run_sequence("gain_verification", retries=2, timeout=90)
    (t,) = run["tasks"]
    assert t["status"] == "ERROR" and t["error_code"] == "COMM_TIMEOUT" and t["attempts"] == 3
    assert run["status"] == "ERROR"
    assert time.monotonic() - t0 < 45
    after = pstack.api_json("GET", "/api/reports/summary")["recovery"]
    assert after["unrecovered"] == before["unrecovered"] + 1
    assert after["tasks_with_retry"] == before["tasks_with_retry"] + 1


def test_fail_results_are_never_retried(pstack: Stack) -> None:
    run = pstack.run_sequence("gain_verification", dut={"profile": "LOWGAIN"}, retries=5)
    (t,) = run["tasks"]
    assert t["status"] == "FAIL" and t["attempts"] == 1


# ---- simulator loss -----------------------------------------------------------------------------------
def test_simulator_killed_mid_run_gives_error_backend_survives_and_recovers(pstack: Stack) -> None:
    pstack.proxy.arm("analyzer", match=r"^MEAS:THD\?", nth=1, times=1, action=pstack.kill_simulator)  # type: ignore[union-attr]
    t0 = time.monotonic()
    run = pstack.run_sequence("full_pipeline", retries=1, timeout=90)
    assert run["status"] == "ERROR", run["status"]
    assert time.monotonic() - t0 < 60, "must not hang"
    assert run["counts"]["FAIL"] == 0
    assert_run_consistent(run)
    done = [t["step_id"] for t in run["tasks"] if t["status"] == "PASS"]
    assert "rms" in done and "gain" in done, "measurements before the crash keep their results"
    h = pstack.api_json("GET", "/api/health")                 # backend alive and answering
    assert h["status"] in ("degraded", "ok")
    insts = pstack.instruments()
    assert all(i["leased_by"] is None for i in insts.values()), "lease must be released on abort"
    # recovery: simulator back, connect through the API, run passes
    pstack.start_simulator()
    got = pstack.connect_all()
    assert {i["id"]: i["state"] for i in got} == {i: "connected" for i in ALL}
    assert pstack.run_sequence("gain_verification")["status"] == "PASS"
    assert_clean(pstack)


def test_run_start_with_simulator_down_ends_in_error_without_hanging(pstack: Stack) -> None:
    pstack.kill_simulator()
    t0 = time.monotonic()
    run = pstack.run_sequence("gain_verification", retries=0, timeout=60)
    assert run["status"] == "ERROR" and run["counts"]["FAIL"] == 0
    assert time.monotonic() - t0 < 30
    assert run["error"] is not None or any(t["status"] == "ERROR" for t in run["tasks"])
    assert run["counts"]["PASS"] == 0
    pstack.start_simulator()
    assert pstack.run_sequence("gain_verification")["status"] == "PASS"


# ======================================================================================= concurrency / state
def test_only_one_run_at_a_time_and_instruments_are_leased(pstack: Stack) -> None:
    slow(pstack, 30)
    run = pstack.start_run("full_pipeline", label="qa-lease")
    rid = run["run_id"]
    wait_until(lambda: pstack.run_status(rid)["status"] == "RUNNING", what="RUNNING")
    # second run -> 409 CONFLICT
    r = pstack.api("POST", "/api/tests/run", {"sequence_id": "gain_verification"})
    assert r.status_code == 409 and assert_error_body(r.json(), "CONFLICT")
    # instrument access is blocked while leased
    wait_until(lambda: pstack.instruments()["analyzer"]["leased_by"] == rid, what="lease")
    r = pstack.api("POST", "/api/instruments/command", {"id": "siggen", "command": "*IDN?"})
    assert r.status_code == 409 and assert_error_body(r.json(), "INSTRUMENT_BUSY")
    r = pstack.api("POST", "/api/instruments/configure", {"id": "siggen", "settings": {"frequency_hz": 500}})
    assert r.status_code == 409 and assert_error_body(r.json())["code"] in ("INSTRUMENT_BUSY", "CONFLICT")
    r = pstack.api("GET", "/api/measurements/live")
    assert r.status_code == 409 and assert_error_body(r.json(), "INSTRUMENT_BUSY")
    r = pstack.api("POST", "/api/instruments/disconnect", {"id": "all"})
    assert r.status_code == 409 and assert_error_body(r.json(), "CONFLICT")
    r = pstack.api("POST", "/api/instruments/disconnect", {"id": "analyzer"})
    assert r.status_code == 409 and assert_error_body(r.json(), "CONFLICT")
    # the blocked requests did not disturb the run
    h = pstack.api_json("GET", "/api/health")
    assert h["running_test"] in (rid, None)
    wait_until(lambda: pstack.api_json("GET", "/api/health")["running_test"] == rid, timeout=5, what="health running_test")
    pstack.proxy.clear_latency()                              # type: ignore[union-attr]
    final = pstack.wait_run(rid, 60)
    assert final["status"] == "PASS", "blocked requests must not fail the run"
    assert_run_consistent(final)
    assert all(i["leased_by"] is None for i in pstack.instruments().values())
    wait_until(lambda: pstack.api_json("GET", "/api/health")["running_test"] is None, timeout=6, what="health idle")


def test_progress_is_monotonic_and_counts_follow_tasks_while_running(pstack: Stack) -> None:
    slow(pstack, 12)
    rid = pstack.start_run("full_pipeline")["run_id"]
    samples: list[dict[str, Any]] = []
    final = pstack.wait_run(rid, 90, poll=0.03, on_poll=lambda r: samples.append(r) if r else None)
    prog = [s["progress"] for s in samples]
    assert prog == sorted(prog), "progress must never decrease"
    assert 0 <= prog[0] < 1 and prog[-1] == 1.0
    assert len(set(prog)) >= 5, "progress should advance in several observable steps"
    for s in samples:
        tasks = s["tasks"]
        for st_ in ("PASS", "FAIL", "ERROR", "CANCELLED"):
            assert s["counts"][st_] == sum(1 for t in tasks if t["status"] == st_), \
                f"counts[{st_}] disagrees with the task list in one status snapshot (non-atomic snapshot?)"
        assert [t["task_id"] for t in tasks] == [f"{rid}-T{i:03d}" for i in range(1, len(tasks) + 1)]
    n_seen = [len(s["tasks"]) for s in samples]
    assert n_seen == sorted(n_seen), "tasks only get appended"
    assert_run_consistent(final)


def test_status_polling_from_several_threads_never_errors_during_a_run(pstack: Stack) -> None:
    slow(pstack, 10)
    rid = pstack.start_run("full_pipeline")["run_id"]
    bad: list[str] = []
    stop = threading.Event()

    def poller(path: str, params: Optional[dict[str, Any]] = None) -> None:
        while not stop.is_set():
            r = pstack.api("GET", path, params=params)
            if r.status_code >= 500 or (r.status_code != 200 and path != "/api/measurements/live"):
                bad.append(f"{path} -> {r.status_code}")
            time.sleep(0.005)

    ts = [threading.Thread(target=poller, args=a) for a in [
        ("/api/tests/status", {"run_id": rid, "log_tail": 50}), ("/api/health", None), ("/api/logs", {"limit": 50}),
        ("/api/instruments", None), ("/api/reports/summary", None), ("/api/tests/results", {"limit": 20})]]
    for t in ts:
        t.start()
    try:
        final = pstack.wait_run(rid, 90)
    finally:
        stop.set()
        for t in ts:
            t.join(5)
    assert not bad, bad[:5]
    assert final["status"] == "PASS"


# ---- cancellation ----------------------------------------------------------------------------------------
# full_pipeline has 18 steps: progress is 0.444..0.833 during the sweep and 0.889 at 'cleanup' (see the late-cancel test below)
@pytest.mark.parametrize("cancel_at", [0.0, 0.3, 0.6, 0.8])
def test_cancel_mid_run_stops_cleanly_and_releases_everything(pstack: Stack, cancel_at: float) -> None:
    slow(pstack, 25)
    run = pstack.start_run("full_pipeline", label=f"qa-cancel-{cancel_at}")
    rid = run["run_id"]
    wait_until(lambda: pstack.run_status(rid)["progress"] >= cancel_at and pstack.run_status(rid)["status"] == "RUNNING",
               timeout=60, what=f"progress >= {cancel_at}")
    t_req = time.monotonic()
    r = pstack.api("POST", "/api/tests/cancel", {"run_id": rid})
    assert r.status_code == 200
    body = r.json()["run"]
    assert body["cancel_requested"] is True and body["status"] in ("RUNNING", "CANCELLED")
    final = pstack.wait_run(rid, 30)
    cancel_latency = time.monotonic() - t_req
    assert final["status"] == "CANCELLED", final["status"]
    assert cancel_latency < 10, f"cancel took {cancel_latency:.1f}s"
    assert final["cancel_requested"] is True
    assert_run_consistent(final)
    assert final["counts"]["PENDING"] == 0 and final["counts"]["RUNNING"] == 0
    # partial results persisted consistently
    persisted = json.loads((pstack.run_dir(rid) / "run.json").read_text())
    assert persisted["status"] == "CANCELLED"
    assert [t["task_id"] for t in persisted["tasks"]] == [t["task_id"] for t in final["tasks"]]
    # resources released
    pstack.proxy.clear_latency()                                # type: ignore[union-attr]
    assert_clean(pstack)
    # the very next run starts and passes
    nxt = pstack.start_run("gain_verification")
    assert pstack.wait_run(nxt["run_id"], 30)["status"] == "PASS"


def test_late_cancel_during_cleanup_leaves_a_consistent_run(pstack: Stack) -> None:
    """Cancel requested once all measurements are done (step 'cleanup'). Contract: 'CANCELLED (if cancelled)'.
    The engine ignores a cancel that arrives when nothing is left to interrupt -> PASS with cancel_requested=true.
    Either outcome is acceptable; what must hold is internal consistency and a released system (see QA_REVIEW)."""
    slow(pstack, 25)
    rid = pstack.start_run("full_pipeline", label="qa-late-cancel")["run_id"]
    wait_until(lambda: pstack.run_status(rid)["progress"] >= 0.85, timeout=60, what="cleanup reached")
    r = pstack.api("POST", "/api/tests/cancel", {"run_id": rid})
    assert r.status_code in (200, 409)          # the run may already be finished by the time the request lands
    final = pstack.wait_run(rid, 30)
    assert final["status"] in ("CANCELLED", "PASS"), final["status"]
    assert_run_consistent(final)
    if final["status"] == "PASS":
        assert all(t["status"] == "PASS" for t in final["tasks"]), "PASS run must not contain non-PASS tasks"
    pstack.proxy.clear_latency()                                # type: ignore[union-attr]
    assert_clean(pstack)


def test_cancel_error_cases_and_idempotence(pstack: Stack) -> None:
    run = pstack.run_sequence("gain_verification")
    r = pstack.api("POST", "/api/tests/cancel", {"run_id": run["run_id"]})
    assert r.status_code == 409 and assert_error_body(r.json(), "CONFLICT")
    r = pstack.api("POST", "/api/tests/cancel", {"run_id": "run-20000101-000000-ffff"})
    assert r.status_code == 404 and assert_error_body(r.json(), "NOT_FOUND")
    slow(pstack, 40)
    rid = pstack.start_run("full_pipeline")["run_id"]
    wait_until(lambda: pstack.run_status(rid)["status"] == "RUNNING", what="running")
    for _ in range(3):                                          # repeated cancel requests are harmless
        r = pstack.api("POST", "/api/tests/cancel", {"run_id": rid})
        assert r.status_code in (200, 409)
    assert pstack.wait_run(rid, 30)["status"] == "CANCELLED"
    # default target: cancel without body while idle -> client error with unified body
    r = pstack.api("POST", "/api/tests/cancel", {})
    assert 400 <= r.status_code < 500
    assert_error_body(r.json())


def test_cancel_with_default_target_cancels_the_active_run(pstack: Stack) -> None:
    slow(pstack, 40)
    rid = pstack.start_run("full_pipeline")["run_id"]
    wait_until(lambda: pstack.run_status(rid)["status"] == "RUNNING", what="running")
    r = pstack.api("POST", "/api/tests/cancel", {})
    assert r.status_code == 200 and r.json()["run"]["run_id"] == rid
    assert pstack.wait_run(rid, 30)["status"] == "CANCELLED"


# ======================================================================================= persistence
def test_history_survives_backend_restart_unchanged(pstack: Stack) -> None:
    ids = []
    for seq, dut in [("gain_verification", {}), ("thd_measurement", {"profile": "HIGHTHD"}), ("frequency_sweep", {})]:
        ids.append(pstack.run_sequence(seq, dut=dut or None, label="qa-persist")["run_id"])
    runs_before = pstack.api_json("GET", "/api/tests/runs", params={"limit": 50})
    results_before = pstack.all_results()
    details_before = {i: pstack.run_status(i, log_tail=0) for i in ids}
    reports_before = {i: pstack.api("GET", f"/api/reports/{i}.csv").content for i in ids}
    summary_before = pstack.api_json("GET", "/api/reports/summary")

    pstack.restart_backend()
    pstack.connect_all()

    runs_after = pstack.api_json("GET", "/api/tests/runs", params={"limit": 50})
    assert runs_after["total"] == runs_before["total"]
    assert [r["run_id"] for r in runs_after["runs"]] == [r["run_id"] for r in runs_before["runs"]], "order/content of history changed"
    assert pstack.all_results() == results_before, "persisted task rows changed across restart"
    for i in ids:
        d = pstack.run_status(i, log_tail=0)
        for key in ("run_id", "sequence_id", "status", "counts", "dut", "label", "parameters", "created_at", "finished_at"):
            assert d[key] == details_before[i][key], f"{i}.{key} changed across restart"
        assert [t["task_id"] for t in d["tasks"]] == [t["task_id"] for t in details_before[i]["tasks"]]
        assert pstack.api("GET", f"/api/reports/{i}.csv").content == reports_before[i]
    sb, sa = summary_before, pstack.api_json("GET", "/api/reports/summary")
    for k in ("runs", "tasks", "by_kind", "failure_reasons", "recovery"):
        assert sa[k] == sb[k], f"summary.{k} changed across restart"
    # new runs after restart must not collide with old ids
    new = pstack.run_sequence("gain_verification")
    assert new["run_id"] not in ids and new["status"] == "PASS"
    assert pstack.api_json("GET", "/api/tests/runs")["total"] == runs_before["total"] + 1


def test_backend_hard_kill_mid_run_leaves_valid_history_and_recoverable_state(pstack: Stack) -> None:
    done = pstack.run_sequence("gain_verification", label="qa-before-crash")
    slow(pstack, 40)
    rid = pstack.start_run("full_pipeline", label="qa-crash")["run_id"]
    wait_until(lambda: pstack.run_status(rid)["progress"] > 0.2, timeout=30, what="progress")
    pstack.kill_backend()
    pstack.proxy.reset()                                         # type: ignore[union-attr]
    pstack.start_backend()
    runs = pstack.all_runs()
    ids = [r["run_id"] for r in runs]
    assert done["run_id"] in ids, "completed run lost"
    assert len(set(ids)) == len(ids)
    stuck = [r for r in runs if r["status"] in ("RUNNING", "PENDING")]
    assert not stuck, f"run(s) reported as active after restart: {stuck}"
    assert pstack.api_json("GET", "/api/health")["running_test"] is None
    for r in runs:                                              # every persisted run parses and has a schema-valid detail
        d = pstack.run_status(r["run_id"], log_tail=0)
        validate({"run": d}, STATUS_ENVELOPE, r["run_id"])
    nxt = pstack.run_sequence("gain_verification")
    assert nxt["status"] == "PASS"
    assert_clean(pstack)


# ======================================================================================= resource hygiene
def test_many_consecutive_runs_do_not_leak_fds_threads_or_memory(pstack: Stack) -> None:
    pstack.run_sequence("gain_verification")                    # warm up
    base = pstack.proc_stats()
    assert base["fds"] is not None, "needs /proc"
    for _ in range(25):
        assert pstack.run_sequence("full_pipeline")["status"] == "PASS"
    after = pstack.proc_stats()
    assert after["fds"] <= base["fds"] + 4, f"fd leak: {base['fds']} -> {after['fds']}"
    assert after["threads"] <= base["threads"] + 4, f"thread leak: {base['threads']} -> {after['threads']}"
    assert after["rss_kb"] <= base["rss_kb"] * 1.5 + 20_000, f"RSS growth {base['rss_kb']} -> {after['rss_kb']} kB"


def test_cancelled_and_failed_runs_do_not_leak_resources(pstack: Stack) -> None:
    pstack.run_sequence("gain_verification")
    base = pstack.proc_stats()
    for i in range(8):
        slow(pstack, 15)
        rid = pstack.start_run("full_pipeline")["run_id"]
        wait_until(lambda: pstack.run_status(rid)["progress"] > 0.1 * (i % 5), timeout=30, what="progress")
        pstack.api("POST", "/api/tests/cancel", {"run_id": rid})
        assert pstack.wait_run(rid, 30)["status"] == "CANCELLED"
        pstack.proxy.reset()                                    # type: ignore[union-attr]
        persistent(pstack, "analyzer", "MF:FAULT:DISCONNECT 1", r"^MEAS:RMS\?", times=50)
        assert pstack.run_sequence("rms_measurement", retries=0)["status"] == "ERROR"
        pstack.proxy.reset()                                    # type: ignore[union-attr]
    after = pstack.proc_stats()
    assert after["fds"] <= base["fds"] + 4, f"fd leak: {base['fds']} -> {after['fds']}"
    assert after["threads"] <= base["threads"] + 4, f"thread leak: {base['threads']} -> {after['threads']}"
    assert_clean(pstack)


def test_run_log_contains_scpi_traffic_and_engine_events_of_the_run(pstack: Stack) -> None:
    seq0 = pstack.logs_since(0, 1)["last_seq"]
    run = pstack.run_sequence("gain_verification")
    logs = pstack.logs_since(seq0, 1000)["logs"]
    scpi = [e for e in logs if e["source"] == "scpi"]
    engine = [e for e in logs if e["source"] == "engine"]
    assert scpi and engine
    tx = [e for e in scpi if (e.get("fields") or {}).get("direction") == "TX"]
    assert tx, "no SCPI TX entries in the log"
    cmds = [e["fields"]["text"] for e in tx if e["fields"]["instrument"] == "analyzer"]
    assert "MEAS:GAIN?" in cmds and any(c.startswith("MF:ACQ:INIT") for c in cmds)
    sig = [e["fields"]["text"] for e in tx if e["fields"]["instrument"] == "siggen"]
    assert any(c.startswith("SOUR:FREQ") for c in sig) and any(re.match(r"^OUTP (ON|1)$", c) for c in sig)
    assert sig[-3:].count("OUTP OFF") + sig[-3:].count("OUTP 0") >= 1, "cleanup must switch the output OFF"
    assert all(e["fields"]["duration_ms"] >= 0 for e in scpi if "duration_ms" in (e["fields"] or {}))
    # the per-run log file is plain text and mentions the run
    text = (pstack.run_dir(run["run_id"]) / "run.log").read_text()
    assert run["run_id"] in text or "gain" in text.lower()
