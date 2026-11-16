"""Shared pieces of the golden-baseline regression suite (baseline generation and comparison).

Baseline = the numeric results of *real* full_pipeline runs (fixed simulator seed) for the NORMAL/1.0.0
reference and for the four fault profiles plus firmware 1.1.0 / 1.2.0. ``baseline.json`` is created by
``update_baseline.py`` from the running stack and is never edited by hand.

Tolerances (per task ``kind``) - chosen so that real numeric drift is caught while the benign noise of a
different noise realisation (different simulator seed, different acquisition counter) is not:

==============  ==========================================  =====================================================
kind            tolerance                                   rationale
==============  ==========================================  =====================================================
rms             0.5 % relative                              noise contributes < 0.01 % to the RMS of a 0.35 V tone
gain, freq_sweep  0.02 dB absolute                          fundamental amplitude estimate, seed spread < 0.003 dB
thd             5 % relative + 0.005 %-points               harmonic/fundamental ratio, seed spread ~1-2 %
snr             0.7 dB absolute                             measured seed-to-seed sigma ~0.15 dB (tolerance >= 4 sigma)
noise_floor     0.6 dB absolute                             measured seed-to-seed sigma ~0.12 dB (tolerance >= 4 sigma)
==============  ==========================================  =====================================================

A task fails the comparison when ``|fresh - baseline| > rel*|baseline| + abs``. Verdicts (PASS/FAIL), error
codes, task order, names and limits must match exactly.
"""
from __future__ import annotations

from typing import Any

# kind -> (relative, absolute)
TOLERANCES: dict[str, tuple[float, float]] = {
    "rms": (0.005, 1e-4),
    "gain": (0.0, 0.02),
    "freq_sweep": (0.0, 0.02),
    "thd": (0.05, 0.005),
    "snr": (0.0, 0.7),
    "noise_floor": (0.0, 0.6),
}

CASES: list[dict[str, Any]] = [
    {"key": "normal_1.0.0", "profile": "NORMAL", "firmware": "1.0.0"},
    {"key": "lowgain_1.0.0", "profile": "LOWGAIN", "firmware": "1.0.0"},
    {"key": "highthd_1.0.0", "profile": "HIGHTHD", "firmware": "1.0.0"},
    {"key": "noisy_1.0.0", "profile": "NOISY", "firmware": "1.0.0"},
    {"key": "clipping_1.0.0", "profile": "CLIPPING", "firmware": "1.0.0"},
    {"key": "normal_1.1.0", "profile": "NORMAL", "firmware": "1.1.0"},
    {"key": "normal_1.2.0", "profile": "NORMAL", "firmware": "1.2.0"},
]
SEQUENCE = "full_pipeline"
SEED = 12345


def summarise_run(run: dict[str, Any]) -> dict[str, Any]:
    """Reduce a run detail to the comparable essentials."""
    return {
        "status": run["status"],
        "counts": {k: run["counts"][k] for k in ("PASS", "FAIL", "ERROR", "CANCELLED")},
        "dut": run["dut"],
        "tasks": [
            {
                "step_id": t["step_id"], "test_name": t["test_name"], "kind": t["kind"], "status": t["status"],
                "value": None if t["measured"] is None else t["measured"]["value"],
                "unit": None if t["measured"] is None else t["measured"]["unit"],
                "limits": t["limits"], "inputs": {k: t["inputs"][k] for k in ("frequency_hz", "amplitude_vpk")},
                "error_code": t["error_code"], "attempts": t["attempts"],
            }
            for t in run["tasks"]
        ],
    }


def tolerance_for(kind: str, baseline_value: float, tolerances: dict[str, Any] | None = None) -> float:
    tol = tolerances or TOLERANCES
    rel, ab = tol[kind]
    return rel * abs(baseline_value) + ab


def compare_case(baseline: dict[str, Any], fresh: dict[str, Any], tolerances: dict[str, Any] | None = None) -> list[str]:
    """Return a list of human-readable differences (empty = fresh run matches the baseline)."""
    diffs: list[str] = []
    if fresh["status"] != baseline["status"]:
        diffs.append(f"run status {fresh['status']} != baseline {baseline['status']}")
    if fresh["counts"] != baseline["counts"]:
        diffs.append(f"counts {fresh['counts']} != baseline {baseline['counts']}")
    bt, ft = baseline["tasks"], fresh["tasks"]
    if len(bt) != len(ft):
        diffs.append(f"task count {len(ft)} != baseline {len(bt)}")
    for b, f in zip(bt, ft):
        where = f"{b['test_name']} (step {b['step_id']})"
        for key in ("step_id", "test_name", "kind", "status", "error_code"):
            if b[key] != f[key]:
                diffs.append(f"{where}: {key} {f[key]!r} != baseline {b[key]!r}")
        if b["limits"] != f["limits"]:
            diffs.append(f"{where}: limits changed {f['limits']} vs {b['limits']}")
        if b["inputs"] != f["inputs"]:
            diffs.append(f"{where}: inputs changed {f['inputs']} vs {b['inputs']}")
        if (b["value"] is None) != (f["value"] is None):
            diffs.append(f"{where}: measured value presence changed")
        elif b["value"] is not None:
            tol = tolerance_for(b["kind"], b["value"], tolerances)
            if abs(f["value"] - b["value"]) > tol:
                diffs.append(f"{where}: value {f['value']:.6g} differs from baseline {b['value']:.6g} "
                             f"by {f['value'] - b['value']:+.4g} (tolerance {tol:.4g})")
    return diffs
