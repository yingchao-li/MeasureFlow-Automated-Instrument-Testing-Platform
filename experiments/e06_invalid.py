"""E06 - Invalid response handling.

Faults are injected on ``MEAS:GAIN?`` of ``gain_verification`` (analyzer client: ``max_retries=0`` and task
``retries=0`` so that the *mapping* fault -> error code is observed without recovery masking it). Expectations are
fixed before the run from the protocol contract (docs/INTERFACE.md section 6), not from the outcome:

  GARBAGE -> ERROR COMM_INVALID_RESPONSE      NAN / DUT NaN samples -> ERROR MEASUREMENT_NAN
  INF     -> ERROR MEASUREMENT_INF            OVERSIZE (> 2 MiB)    -> ERROR COMM_RESPONSE_TOO_LARGE
  FRAGMENT-> PASS (valid reply in chunks)     empty line            -> ERROR COMM_INVALID_RESPONSE
  truncated (no terminator) -> ERROR COMM_TIMEOUT
  GARBAGE with default retries (transient) -> PASS (client retry recovers)
No case may ever produce FAIL, and the backend must stay healthy and run a clean measurement afterwards.
"""
from __future__ import annotations

from typing import Any

from common import Ctx, rate

M = r"^MEAS:GAIN\?"
CASES: list[dict[str, Any]] = [
    {"name": "garbage", "inject": "MF:FAULT:GARBAGE 1", "expect": ("ERROR", {"COMM_INVALID_RESPONSE"})},
    {"name": "nan", "inject": "MF:FAULT:NAN 1", "expect": ("ERROR", {"MEASUREMENT_NAN"})},
    {"name": "inf", "inject": "MF:FAULT:INF 1", "expect": ("ERROR", {"MEASUREMENT_INF"})},
    {"name": "oversize", "inject": "MF:FAULT:OVERSIZE 1", "expect": ("ERROR", {"COMM_RESPONSE_TOO_LARGE"})},
    {"name": "fragment", "inject": "MF:FAULT:FRAGMENT 1", "expect": ("PASS", {None})},
    {"name": "empty_line", "inject": None, "replace": b"\n", "expect": ("ERROR", {"COMM_INVALID_RESPONSE"})},
    {"name": "truncated", "inject": None, "replace": b"19.9", "expect": ("ERROR", {"COMM_TIMEOUT"})},
    {"name": "dut_nan_samples", "inject": "MF:DUT:FAULT NAN", "target": "dut", "match": r"^MF:ACQ:INIT", "expect": ("ERROR", {"MEASUREMENT_NAN"})},
    {"name": "dut_inf_samples", "inject": "MF:DUT:FAULT INF", "target": "dut", "match": r"^MF:ACQ:INIT", "expect": ("ERROR", {"MEASUREMENT_NAN", "MEASUREMENT_INF"})},
]
REPEATS = 5


def _one(st: Any, case: dict[str, Any], retries: int) -> dict[str, Any]:
    st.proxy.reset()
    st.proxy.arm("analyzer", case["inject"] or [], match=case.get("match", M), nth=1, times=1,
                 target=case.get("target"), replace=case.get("replace"))
    r = st.run_sequence("gain_verification", retries=retries, timeout=60)
    t = r["tasks"][0] if r["tasks"] else {}
    st.proxy.reset()
    st.reset_simulator_state()
    h = st.get("/api/health")
    clean = st.run_sequence("gain_verification", retries=0, timeout=60)
    return {"case": case["name"], "status": t.get("status"), "run_status": r["status"], "error_code": t.get("error_code"),
            "message": t.get("message"), "health_http": h.status_code, "health": h.json().get("status"),
            "clean_run_after": clean["status"], "duration_ms": r["duration_ms"]}


def run(ctx: Ctx) -> dict[str, Any]:
    reps = 2 if ctx.quick else REPEATS
    rows: list[dict[str, Any]] = []
    with ctx.stack(with_proxy=True, overrides={"analyzer": {"timeout_ms": 300, "max_retries": 0}}) as st:
        ctx.write_config({"sequence": "gain_verification", "analyzer_max_retries": 0, "analyzer_timeout_ms": 300, "task_retries": 0,
                          "repeats": reps, "cases": [{k: (v.decode() if isinstance(v, bytes) else v) for k, v in c.items()} for c in CASES],
                          "versions": st.versions()})
        for c in CASES:
            for i in range(reps):
                row = _one(st, c, 0)
                row["repeat"] = i
                es, codes = c["expect"]
                row["expected_status"], row["expected_codes"] = es, sorted(x or "" for x in codes)
                row["correct"] = row["status"] == es and (row["error_code"] in codes)
                rows.append(row)
                ctx.log(f"{c['name']}#{i}: {row['status']} {row['error_code']} correct={row['correct']}")
    # transient garbage with the default retry policy -> must recover
    with ctx.stack(with_proxy=True) as st:
        for i in range(reps):
            row = _one(st, {"name": "garbage_transient_default_retries", "inject": "MF:FAULT:GARBAGE 1"}, 2)
            row.update(repeat=i, expected_status="PASS", expected_codes=[""], correct=row["status"] == "PASS")
            rows.append(row)
    ctx.write_raw_json(rows)

    by: dict[str, Any] = {}
    for name in dict.fromkeys(r["case"] for r in rows):
        sub = [r for r in rows if r["case"] == name]
        by[name] = {"n": len(sub), "mapping_accuracy": rate(sum(r["correct"] for r in sub), len(sub)),
                    "codes_seen": sorted({str(r["error_code"]) for r in sub}), "statuses_seen": sorted({str(r["status"]) for r in sub})}
    m = {"cases": len(rows), "error_mapping_accuracy": rate(sum(r["correct"] for r in rows), len(rows)),
         "fail_status_count": sum(1 for r in rows if r["status"] == "FAIL"),
         "backend_healthy_after_rate": rate(sum(1 for r in rows if r["health_http"] == 200 and r["health"] in ("ok", "degraded")), len(rows)),
         "clean_run_after_pass_rate": rate(sum(1 for r in rows if r["clean_run_after"] == "PASS"), len(rows)), "by_case": by}
    if m["fail_status_count"]:
        ctx.defect("high", "invalid response reported as FAIL", f"{m['fail_status_count']} cases")
    ctx.write_metrics(m)
    return {"mapping_accuracy": m["error_mapping_accuracy"], "healthy_after": m["backend_healthy_after_rate"]}
