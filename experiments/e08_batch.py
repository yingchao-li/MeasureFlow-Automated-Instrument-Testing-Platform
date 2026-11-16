"""E08 - Batch execution of 500 test cases (one case = one measurement task).

A fixed-seed plan mixes full_pipeline (13 tasks), frequency_sweep (8 tasks) and single-measurement sequences over random
DUT profiles / firmware / stimulus; ~6 % of the single-task runs carry an injected communication fault (known plan).
Expected status per task: analytic truth vs limits (``truth_adapter``); for injected faults: ERROR.
Outcome classes: pass | expected_measurement_fail | expected_injected_fault | unexpected_software_error | false_pass |
false_fail | missed_fault | borderline | other_mismatch (see common.outcome_class).
"""
from __future__ import annotations

import random
import time
from collections import Counter
from typing import Any

import truth_adapter as ta
from common import Ctx, outcome_class, rate, summarize

TOTAL = 500
SINGLES = ["gain_verification", "thd_measurement", "snr_measurement", "noise_floor", "rms_measurement"]
PROFILES = (["NORMAL"] * 6 + ["LOWGAIN", "HIGHTHD", "NOISY", "CLIPPING"])
FAULTS = [("timeout", "MF:FAULT:TIMEOUT 40,400"), ("disconnect", "MF:FAULT:DISCONNECT 40"), ("garbage", "MF:FAULT:GARBAGE 40")]


def make_plan(seed: int, total: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    plan: list[dict[str, Any]] = []
    n = 0
    while n < total:
        rem = total - n
        u = rng.random()
        if rem >= 13 and u < 0.12:
            seq, k = "full_pipeline", 13
        elif rem >= 8 and u < 0.22:
            seq, k = "frequency_sweep", 8
        else:
            seq, k = rng.choice(SINGLES), 1
        item: dict[str, Any] = {"sequence": seq, "tasks": k, "profile": rng.choice(PROFILES), "firmware": rng.choice(["1.0.0", "1.0.0", "1.1.0"]),
                                "frequency_hz": rng.choice([250, 500, 1000, 2000, 4000]), "amplitude_vpk": rng.choice([0.02, 0.05, 0.1]), "fault": None}
        if k == 1 and rng.random() < 0.06:
            item["fault"] = rng.choice(FAULTS)
        plan.append(item)
        n += k
    return plan


def run(ctx: Ctx) -> dict[str, Any]:
    total = 60 if ctx.quick else TOTAL
    plan = make_plan(ctx.seed, total)
    rows: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    with ctx.stack(with_proxy=True, overrides={"analyzer": {"timeout_ms": 150}}) as st:
        ctx.write_config({"cases": total, "plan_seed": ctx.seed, "runs_planned": len(plan), "fault_share_of_single_runs": 0.06,
                          "faults": [f[0] for f in FAULTS], "task_retries": 1, "analyzer_timeout_ms": 150, "profiles_weights": Counter(PROFILES),
                          "plan": plan, "versions": st.versions()})
        st.connect_all()
        warm = st.proc_stats()
        t_start = time.perf_counter()
        for i, p in enumerate(plan):
            st.proxy.reset()
            if p["fault"]:
                st.proxy.arm("analyzer", p["fault"][1], match=r"^MEAS:", nth=1, times=1)
            r = st.run_sequence(p["sequence"], parameters={"frequency_hz": p["frequency_hz"], "amplitude_vpk": p["amplitude_vpk"]},
                                dut={"profile": p["profile"], "firmware": p["firmware"]}, retries=1, timeout=120)
            runs.append({"i": i, "run_id": r["run_id"], "sequence": p["sequence"], "status": r["status"], "duration_ms": r["duration_ms"],
                         "fault": p["fault"] and p["fault"][0], "planned_tasks": p["tasks"], "executed_tasks": len(r["tasks"]),
                         "error": r.get("error")})
            if p["fault"]:
                st.reset_simulator_state()      # fault counters live in the simulator and would poison the next run's init
            for t in r["tasks"]:
                injected = bool(p["fault"])
                exp = ta.task_expectation(t)
                expected = "ERROR" if injected else exp.status
                cls = outcome_class(expected, t["status"], injected, border=exp.margin <= 0)
                rows.append({"plan_index": i, "run_id": r["run_id"], "sequence": p["sequence"], "profile": p["profile"], "firmware": p["firmware"],
                             "kind": t["kind"], "test_name": t["test_name"], "injected_fault": p["fault"] and p["fault"][0], "expected_status": expected,
                             "status": t["status"], "error_code": t["error_code"], "attempts": t["attempts"], "duration_ms": t["duration_ms"],
                             "value": None if t["measured"] is None else t["measured"]["value"], "class": cls})
            if i % 20 == 0:
                ctx.log(f"run {i + 1}/{len(plan)}, tasks so far {len(rows)}")
        elapsed = time.perf_counter() - t_start
        end = st.proc_stats()
        alive = st.api("GET", "/api/health").status_code == 200
    ctx.write_raw_csv(rows)
    (ctx.dir / "runs.json").write_text(__import__("json").dumps(runs, indent=1))

    cls = Counter(r["class"] for r in rows)
    judged = [r for r in rows if r["class"] != "borderline"]
    measured = [r for r in rows if not r["injected_fault"]]
    m = {"cases_planned": total, "cases_executed": len(rows), "runs": len(runs), "backend_alive_at_end": alive,
         "task_completion_rate": rate(sum(r["status"] in ("PASS", "FAIL", "ERROR") for r in rows), total),
         "outcome_classes": dict(cls),
         "expected_status_accuracy": rate(sum(r["status"] == r["expected_status"] for r in judged), len(judged)), "borderline_not_judged": cls.get("borderline", 0),
         "actual_test_success_rate": {"definition": "non-injected tasks that produced a valid measurement (PASS or FAIL, not ERROR)",
                                      "value": rate(sum(r["status"] in ("PASS", "FAIL") for r in measured), len(measured))},
         "unexpected_task_errors": cls.get("unexpected_software_error", 0),
         "unexpected_run_errors": sum(1 for x in runs if x["status"] == "ERROR" and not x["fault"]),
         "unexpected_software_errors": cls.get("unexpected_software_error", 0) + sum(1 for x in runs if x["status"] == "ERROR" and not x["fault"]),
         "tasks_not_executed": total - len(rows),
         "injected_fault_tasks": sum(1 for r in rows if r["injected_fault"]),
         "fault_recovery_rate_note": "persistent faults are expected to end in ERROR (recovery is measured in E04/E05)",
         "task_duration_ms": summarize(r["duration_ms"] for r in rows), "task_duration_ms_non_fault": summarize(r["duration_ms"] for r in measured),
         "run_duration_ms": summarize(x["duration_ms"] for x in runs), "wall_time_s": elapsed, "throughput_tasks_per_s": len(rows) / elapsed,
         "backend_resources": {"after_warmup": warm, "at_end": end},
         "mismatches": [{k: r[k] for k in ("plan_index", "test_name", "profile", "firmware", "expected_status", "status", "error_code", "class")}
                        for r in rows if r["class"] in ("false_pass", "false_fail", "other_mismatch", "unexpected_software_error", "missed_fault")][:30]}
    if m["unexpected_software_errors"]:
        ctx.defect("high", "unexpected software errors in batch", f"{m['unexpected_software_errors']} tasks")
    ctx.write_metrics(m)
    return {"cases": len(rows), "accuracy": m["expected_status_accuracy"], "unexpected_errors": m["unexpected_software_errors"]}
