"""E04 - Timeout & retry capacity.

A SCPI timeout is injected on exactly the first n attempts of ``MEAS:GAIN?`` during ``gain_verification``
(``MF:FAULT:TIMEOUT 1,<delay>`` is written to the simulator by the fault proxy immediately before each of the
first n forwarded ``MEAS:GAIN?`` commands, so every attempt is hit - client retries and task retries alike).

Capacity model (from INTERFACE.md section 6, stated here so it can be refuted):
  * the SCPI client retries an idempotent query ``max_retries`` times  -> 1 + r attempts per task attempt
  * the task is retried ``retries`` times after a reconnect            -> 1 + t task attempts
  * => the measurement is recovered iff n < (1 + t) * (1 + r); the PASS then happens on task attempt
    floor(n / (1 + r)) + 1; otherwise the task ends in ERROR / COMM_TIMEOUT after 1 + t task attempts.
"""
from __future__ import annotations

from typing import Any

import truth_adapter as ta
from common import Ctx, rate, summarize

TASK_RETRIES = [0, 1, 2, 3]
CLIENT_RETRIES = [0, 1, 2]
TIMEOUT_MS = 150
DELAY_MS = 400
HANG_LIMIT_S = 30.0


def run(ctx: Ctx) -> dict[str, Any]:
    t_list = [0, 1] if ctx.quick else TASK_RETRIES
    r_list = [0, 2] if ctx.quick else CLIENT_RETRIES
    rows: list[dict[str, Any]] = []
    truth = ta.expected_metrics("NORMAL", "1.0.0", 1000, 0.05)["gain_db"]
    versions: dict[str, Any] = {}
    for r_c in r_list:
        with ctx.stack(with_proxy=True, overrides={"analyzer": {"timeout_ms": TIMEOUT_MS, "max_retries": r_c}}) as st:
            versions = st.versions()
            for t in t_list:
                cap = (1 + t) * (1 + r_c)
                base_durations: list[float] = []
                for n in range(0, cap + 2):
                    st.proxy.reset()
                    if n:
                        st.proxy.arm("analyzer", f"MF:FAULT:TIMEOUT 1,{DELAY_MS}", match=r"^MEAS:GAIN\?", nth=1, times=n)
                    import time
                    t0 = time.perf_counter()
                    run = st.run_sequence("gain_verification", retries=t, timeout=HANG_LIMIT_S + 10)
                    wall = (time.perf_counter() - t0) * 1000
                    task = run["tasks"][0] if run["tasks"] else {}
                    exp_recovered = n < cap
                    exp_attempts = n // (1 + r_c) + 1 if exp_recovered else 1 + t
                    gains_seen = sum(1 for e in st.proxy.trace("analyzer") if e.text.upper().startswith("MEAS:GAIN?"))
                    val = None if not task or task.get("measured") is None else task["measured"]["value"]
                    rows.append({"client_retries": r_c, "task_retries": t, "n_faults": n, "capacity": cap, "expected_recovered": exp_recovered,
                                 "expected_status": "PASS" if exp_recovered else "ERROR", "expected_error_code": None if exp_recovered else "COMM_TIMEOUT",
                                 "expected_attempts": exp_attempts, "actual_status": run["status"], "task_status": task.get("status"),
                                 "error_code": task.get("error_code"), "attempts": task.get("attempts"), "run_duration_ms": run["duration_ms"],
                                 "wall_ms": wall, "meas_gain_queries_seen": gains_seen, "measured_gain": val,
                                 "value_error_db": None if val is None else val - truth, "hang": wall / 1000 > HANG_LIMIT_S})
                    if n == 0:
                        base_durations.append(run["duration_ms"])
            st.proxy.reset()
    ctx.write_config({"task_retries": t_list, "client_max_retries": r_list, "analyzer_timeout_ms": TIMEOUT_MS, "injected_delay_ms": DELAY_MS,
                      "hang_limit_s": HANG_LIMIT_S, "sequence": "gain_verification (1 kHz, 0.05 Vpk, NORMAL, 1.0.0)",
                      "model": "recovered iff n < (1+task_retries)*(1+client_max_retries); PASS on task attempt n//(1+r)+1; else ERROR COMM_TIMEOUT with 1+t attempts",
                      "truth_gain_db": truth, "versions": versions})
    ctx.write_raw_csv(rows)

    # ------------------------------------------------------------------ metrics
    status_ok = [r for r in rows if r["actual_status"] == r["expected_status"]]
    full_ok = [r for r in rows if r["actual_status"] == r["expected_status"] and r["attempts"] == r["expected_attempts"]
               and (r["expected_recovered"] or r["error_code"] == "COMM_TIMEOUT")]
    rec = [r for r in rows if r["expected_recovered"] and r["n_faults"] > 0]
    fail_rows = [r for r in rows if not r["expected_recovered"]]
    base = {(r["client_retries"], r["task_retries"]): r["run_duration_ms"] for r in rows if r["n_faults"] == 0}
    m: dict[str, Any] = {
        "cases": len(rows), "status_prediction_accuracy": rate(len(status_ok), len(rows)),
        "status_error_code_and_attempts_accuracy": rate(len(full_ok), len(rows)),
        "unexpected_fail_status": sum(1 for r in rows if r["actual_status"] == "FAIL" or r["task_status"] == "FAIL"),
        "hangs": sum(1 for r in rows if r["hang"]),
        "recovered_cases": {"n": len(rec), "pass_rate": rate(sum(1 for r in rec if r["actual_status"] == "PASS"), len(rec)),
                            "max_abs_value_error_db": max((abs(r["value_error_db"]) for r in rec if r["value_error_db"] is not None), default=None),
                            "recovery_time_ms": summarize(r["run_duration_ms"] - base[(r["client_retries"], r["task_retries"])] for r in rec)},
        "unrecoverable_cases": {"n": len(fail_rows), "error_rate": rate(sum(1 for r in fail_rows if r["actual_status"] == "ERROR"), len(fail_rows)),
                                "comm_timeout_code_rate": rate(sum(1 for r in fail_rows if r["error_code"] == "COMM_TIMEOUT"), len(fail_rows)),
                                "time_to_failure_ms": summarize(r["run_duration_ms"] for r in fail_rows)},
        "mismatches": [{k: r[k] for k in ("client_retries", "task_retries", "n_faults", "expected_status", "actual_status", "error_code", "expected_attempts", "attempts")}
                       for r in rows if not (r["actual_status"] == r["expected_status"] and r["attempts"] == r["expected_attempts"])][:20],
        "by_capacity": {},
        "boundary": {},
    }
    for cap in sorted({r["capacity"] for r in rows}):
        sub = [r for r in rows if r["capacity"] == cap]
        m["by_capacity"][str(cap)] = {"n": len(sub), "accuracy": rate(sum(1 for r in sub if r["actual_status"] == r["expected_status"]), len(sub))}
    # sharpness of the recovery boundary: last recovered n and first failing n per (t, r)
    for (r_c, t) in sorted({(r["client_retries"], r["task_retries"]) for r in rows}):
        sub = sorted((r for r in rows if r["client_retries"] == r_c and r["task_retries"] == t), key=lambda r: r["n_faults"])
        last_ok = max((r["n_faults"] for r in sub if r["actual_status"] == "PASS"), default=None)
        first_bad = min((r["n_faults"] for r in sub if r["actual_status"] == "ERROR"), default=None)
        m["boundary"][f"r={r_c},t={t}"] = {"capacity_model": (1 + t) * (1 + r_c), "last_recovered_n": last_ok, "first_failing_n": first_bad,
                                           "predicted_last_recovered_n": (1 + t) * (1 + r_c) - 1}
    if m["unexpected_fail_status"]:
        ctx.defect("high", "timeouts reported as FAIL", f"{m['unexpected_fail_status']} cases")
    if m["hangs"]:
        ctx.defect("high", "run hung under injected timeouts", f"{m['hangs']} cases > {HANG_LIMIT_S}s")
    if m["status_prediction_accuracy"] != 1.0:
        ctx.log(f"note: retry-capacity model mispredicted {len(rows) - len(status_ok)} / {len(rows)} outcomes")
    ctx.write_metrics(m)
    return {"cases": len(rows), "status_accuracy": m["status_prediction_accuracy"], "unexpected_fail": m["unexpected_fail_status"], "hangs": m["hangs"]}
