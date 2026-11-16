"""E03 - Out-of-tolerance detection: do verdicts agree with the analytic expectation (truth vs limits)?
Part A: five DUT profiles x three stimulus frequencies through full_pipeline.
Part B: threshold-proximity study - limits placed at truth +- d to find the resolution of the decision."""
from __future__ import annotations

from typing import Any

import truth_adapter as ta
from common import Ctx, error_stats, outcome_class, rate, summarize

PROFILES = ["NORMAL", "LOWGAIN", "HIGHTHD", "NOISY", "CLIPPING"]
FREQS = [500, 1000, 2000]
DELTAS = [0.02, 0.05, 0.1, 0.5]


def run(ctx: Ctx) -> dict[str, Any]:
    freqs = [1000] if ctx.quick else FREQS
    n_seeds = 3 if ctx.quick else 10
    seeds = [ctx.seed + 1000 + i for i in range(n_seeds)]
    tasks_raw: list[dict[str, Any]] = []
    prox: list[dict[str, Any]] = []
    with ctx.stack() as st:
        ctx.write_config({"profiles": PROFILES, "frequencies_hz": freqs, "sequence": "full_pipeline", "firmware": "1.0.0",
                          "limits": "sequence defaults (configs/sequences/full_pipeline.json)",
                          "uncertainty_budget": {"relative": [k for k, v in ta.UNCERTAINTY_IS_RELATIVE.items() if v], "values": ta.UNCERTAINTY},
                          "borderline_rule": "|truth - nearest limit| <= uncertainty -> task is 'borderline' and not judged",
                          "proximity": {"deltas_db": DELTAS, "seeds": seeds, "stimulus": "NORMAL, 1000 Hz, 0.05 Vpk, gain_verification",
                                        "limit_cases": ["min=T+d (expect FAIL low)", "min=T-d (expect PASS)", "max=T-d (expect FAIL high)", "max=T+d (expect PASS)"]},
                          "versions": st.versions()})
        # ---------------- part A
        for prof in PROFILES:
            for f in freqs:
                ctx.log(f"full_pipeline {prof} @ {f} Hz")
                run = st.run_sequence("full_pipeline", parameters={"frequency_hz": f}, dut={"profile": prof, "firmware": "1.0.0"}, retries=0)
                for t in run["tasks"]:
                    exp = ta.task_expectation(t)
                    val = None if t["measured"] is None else t["measured"]["value"]
                    border = exp.margin <= 0
                    tasks_raw.append({"run_id": run["run_id"], "profile": prof, "frequency_hz": f, "test_name": t["test_name"], "kind": t["kind"],
                                      "task_frequency_hz": t["inputs"]["frequency_hz"], "expected_value": exp.expected, "measured": val,
                                      "limit_min": t["limits"]["min"], "limit_max": t["limits"]["max"], "expected_status": exp.status,
                                      "margin": exp.margin, "borderline": border, "actual_status": t["status"], "error_code": t["error_code"],
                                      "class": outcome_class(exp.status, t["status"], False, border)})
        # ---------------- part B
        T = ta.expected_metrics("NORMAL", "1.0.0", 1000, 0.05)["gain_db"]
        for seed in seeds:
            st.restart_simulator(seed)
            st.disconnect_all()
            st.connect_all()
            for d in DELTAS:
                for case, (lo, hi, expect) in {"min=T+d": (T + d, 60.0, "FAIL"), "min=T-d": (T - d, 60.0, "PASS"),
                                               "max=T-d": (-20.0, T - d, "FAIL"), "max=T+d": (-20.0, T + d, "PASS")}.items():
                    run = st.run_sequence("gain_verification", parameters={"gain_min_db": lo, "gain_max_db": hi}, retries=0)
                    t = run["tasks"][0]
                    prox.append({"seed": seed, "delta_db": d, "case": case, "truth_gain_db": T, "limit_min": lo, "limit_max": hi,
                                 "measured": None if t["measured"] is None else t["measured"]["value"], "expected_status": expect,
                                 "actual_status": t["status"], "error_code": t["error_code"], "correct": t["status"] == expect})
    ctx.write_raw_json({"profile_matrix": tasks_raw, "proximity": prox})

    # ------------------------------------------------------------------ metrics from raw
    judged = [r for r in tasks_raw if not r["borderline"]]
    conf: dict[str, dict[str, int]] = {e: {a: 0 for a in ("PASS", "FAIL", "ERROR", "CANCELLED")} for e in ("PASS", "FAIL")}
    for r in judged:
        conf[r["expected_status"]][r["actual_status"]] = conf[r["expected_status"]].get(r["actual_status"], 0) + 1
    classes: dict[str, int] = {}
    for r in tasks_raw:
        classes[r["class"]] = classes.get(r["class"], 0) + 1
    m: dict[str, Any] = {
        "tasks_total": len(tasks_raw), "tasks_judged": len(judged), "tasks_borderline": len(tasks_raw) - len(judged),
        "confusion_matrix_expected_vs_actual": conf,
        "detection_accuracy": rate(sum(1 for r in judged if r["expected_status"] == r["actual_status"]), len(judged)),
        "false_pass": sum(1 for r in judged if r["expected_status"] == "FAIL" and r["actual_status"] == "PASS"),
        "false_fail": sum(1 for r in judged if r["expected_status"] == "PASS" and r["actual_status"] == "FAIL"),
        "errors_on_clean_runs": sum(1 for r in tasks_raw if r["actual_status"] == "ERROR"),
        "outcome_classes": classes,
        "actual_pass_rate": rate(sum(1 for r in tasks_raw if r["actual_status"] == "PASS"), len(tasks_raw)),
        "expected_pass_rate": rate(sum(1 for r in tasks_raw if r["expected_status"] == "PASS"), len(tasks_raw)),
        "per_kind_accuracy": {}, "per_profile": {}, "value_error_vs_truth": {},
    }
    for k in sorted({r["kind"] for r in judged}):
        sub = [r for r in judged if r["kind"] == k]
        m["per_kind_accuracy"][k] = {"n": len(sub), "accuracy": rate(sum(1 for r in sub if r["expected_status"] == r["actual_status"]), len(sub))}
        # CLIPPING snr / noise_floor have no analytic truth (see truth_adapter.INDETERMINATE): excluded from the error statistics
        sub_all = [r for r in tasks_raw if r["kind"] == k and r["measured"] is not None and (r["profile"].upper(), k) not in ta.INDETERMINATE]
        m["value_error_vs_truth"][k] = error_stats([r["measured"] - r["expected_value"] for r in sub_all])
    for p in PROFILES:
        sub = [r for r in tasks_raw if r["profile"] == p]
        m["per_profile"][p] = {"tasks": len(sub), "expected_fail": sum(1 for r in sub if r["expected_status"] == "FAIL"),
                               "actual_fail": sum(1 for r in sub if r["actual_status"] == "FAIL"),
                               "actual_pass": sum(1 for r in sub if r["actual_status"] == "PASS"),
                               "agreement": rate(sum(1 for r in sub if r["expected_status"] == r["actual_status"] and not r["borderline"]),
                                                 sum(1 for r in sub if not r["borderline"]))}
    m["proximity"] = {"n_runs": len(prox), "by_delta_db": {}, "measured_gain_minus_truth_db": error_stats([r["measured"] - r["truth_gain_db"] for r in prox if r["measured"] is not None and r["case"] == "min=T-d" and r["delta_db"] == DELTAS[0]]),
                      "per_seed_measured_gain": summarize(r["measured"] for r in prox if r["case"] == "min=T-d" and r["delta_db"] == DELTAS[0] and r["measured"] is not None)}
    resolution = None
    for d in DELTAS:
        sub = [r for r in prox if r["delta_db"] == d]
        acc = rate(sum(r["correct"] for r in sub), len(sub))
        m["proximity"]["by_delta_db"][str(d)] = {"n": len(sub), "accuracy": acc, "wrong": [{k: r[k] for k in ("seed", "case", "measured", "actual_status")} for r in sub if not r["correct"]][:5],
                                                  "errors": sum(1 for r in sub if r["actual_status"] == "ERROR")}
        if acc == 1.0 and resolution is None:
            resolution = d
    m["proximity"]["resolution_db"] = resolution
    if m["false_pass"] or m["false_fail"]:
        ctx.defect("high", "verdict disagrees with analytic expectation", f"false_pass={m['false_pass']} false_fail={m['false_fail']}")
    if m["errors_on_clean_runs"]:
        ctx.defect("high", "ERROR tasks without fault injection", f"{m['errors_on_clean_runs']} tasks")
    ctx.write_metrics(m)
    return {"accuracy": m["detection_accuracy"], "false_pass": m["false_pass"], "false_fail": m["false_fail"], "resolution_db": resolution}
