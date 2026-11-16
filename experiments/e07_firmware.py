"""E07 - Firmware regression testing.

``full_pipeline`` (NORMAL profile) on simulated firmware 1.0.0 / 1.1.0 / 1.2.0 over several simulator seeds.
Expected verdicts come from the analytic truth (``truth_adapter``), so 1.2.0 is *expected* to fail the THD limit
and 1.0.0 / 1.1.0 are expected to pass everything. Reported: per-firmware mean +- std per measurement, deltas
vs 1.0.0, regression detection rate, false alarms, verdict accuracy.
"""
from __future__ import annotations

import statistics
from typing import Any

import truth_adapter as ta
from common import Ctx, rate, summarize

FIRMWARE = ["1.0.0", "1.1.0", "1.2.0"]
SEEDS = [1, 2, 3, 4, 5]


def run(ctx: Ctx) -> dict[str, Any]:
    seeds = SEEDS[:2] if ctx.quick else SEEDS
    rows: list[dict[str, Any]] = []
    with ctx.stack() as st:
        ctx.write_config({"sequence": "full_pipeline", "profile": "NORMAL", "firmware": FIRMWARE, "simulator_seeds": seeds,
                          "expected_status_source": "mfsim.truth analytic expectation vs sequence limits (uncertainty budget in truth_adapter)",
                          "versions": st.versions()})
        for seed in seeds:
            st.restart_simulator(seed)
            st.disconnect_all(); st.connect_all()
            for fw in FIRMWARE:
                r = st.run_sequence("full_pipeline", dut={"profile": "NORMAL", "firmware": fw}, retries=0)
                for t in r["tasks"]:
                    exp = ta.task_expectation(t)
                    rows.append({"seed": seed, "firmware": fw, "run_id": r["run_id"], "test_name": t["test_name"], "kind": t["kind"],
                                 "frequency_hz": t["inputs"].get("frequency_hz"), "value": None if t["measured"] is None else t["measured"]["value"],
                                 "unit": t["limits"]["unit"], "expected_value": exp.expected, "expected_status": exp.status,
                                 "borderline": exp.margin <= 0, "status": t["status"], "error_code": t["error_code"]})
                ctx.log(f"seed {seed} fw {fw}: run {r['status']}")
    ctx.write_raw_csv(rows)

    def key(r: dict[str, Any]) -> str:
        return r["test_name"].split(" @ ")[0] if r["kind"] != "freq_sweep" else "gain sweep point"
    by_fw: dict[str, Any] = {}
    for fw in FIRMWARE:
        sub = [r for r in rows if r["firmware"] == fw]
        kinds: dict[str, Any] = {}
        for k in ("rms", "gain", "thd", "snr", "noise_floor"):
            vals = [r["value"] for r in sub if r["kind"] == k and r["value"] is not None]
            kinds[k] = {**summarize(vals), "unit": next((r["unit"] for r in sub if r["kind"] == k), None)}
        by_fw[fw] = {"tasks": len(sub), "pass": sum(r["status"] == "PASS" for r in sub), "fail": sum(r["status"] == "FAIL" for r in sub),
                     "error": sum(r["status"] == "ERROR" for r in sub), "kinds": kinds,
                     "failing_tests": sorted({key(r) for r in sub if r["status"] == "FAIL"})}
    base = by_fw["1.0.0"]["kinds"]
    for fw in FIRMWARE[1:]:
        for k, s in by_fw[fw]["kinds"].items():
            s["delta_vs_1_0_0"] = None if s["mean"] is None or base[k]["mean"] is None else s["mean"] - base[k]["mean"]
    judged = [r for r in rows if not r["borderline"]]
    thd = lambda fw: [r for r in rows if r["firmware"] == fw and r["kind"] == "thd"]  # noqa: E731
    m = {"runs": len(seeds) * len(FIRMWARE), "tasks": len(rows), "by_firmware": by_fw,
         "verdict_accuracy": rate(sum(r["status"] == r["expected_status"] for r in judged), len(judged)), "borderline_not_judged": len(rows) - len(judged),
         "regression_detection": {"firmware": "1.2.0", "thd_fail_rate": rate(sum(r["status"] == "FAIL" for r in thd("1.2.0")), len(thd("1.2.0"))),
                                  "other_tasks_failing": sorted({key(r) for r in rows if r["firmware"] == "1.2.0" and r["status"] == "FAIL" and r["kind"] != "thd"})},
         "false_alarms_1_1_0": sum(r["status"] != "PASS" for r in rows if r["firmware"] == "1.1.0"),
         "false_alarms_1_0_0": sum(r["status"] != "PASS" for r in rows if r["firmware"] == "1.0.0"),
         "thd_1_2_0_over_1_0_0_ratio": (None if not base["thd"]["mean"] else by_fw["1.2.0"]["kinds"]["thd"]["mean"] / base["thd"]["mean"]),
         "seed_to_seed_std_of_means": {fw: statistics.pstdev([statistics.fmean(r["value"] for r in rows if r["firmware"] == fw and r["seed"] == s and r["kind"] == "snr")
                                                              for s in seeds]) for fw in FIRMWARE}}
    ctx.write_metrics(m)
    return {"thd_regression_detected": m["regression_detection"]["thd_fail_rate"], "false_alarms": m["false_alarms_1_0_0"] + m["false_alarms_1_1_0"]}
