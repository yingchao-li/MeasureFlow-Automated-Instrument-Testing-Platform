"""E02 - Measurement accuracy: instrument measurements vs analytic truth (mfsim.truth) over a
frequency x amplitude x profile grid, repeatability, and independent NumPy time-domain cross-checks."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

import truth_adapter as ta
from common import Ctx, error_stats, rate, summarize

FREQS = [100, 200, 500, 1000, 2000, 4000, 6000, 8000]
AMPS = [0.01, 0.05, 0.1]
PROFILES = ["NORMAL", "HIGHTHD", "NOISY"]
# INTERFACE.md guideline (section 3.3): gain error < 0.05 dB, THD within +-2 % relative (or +-0.005 %-points),
# SNR/noise within +-0.5 dB. RMS has no guideline; 0.5 % is used here.
GUIDE = {"gain_db": ("abs", 0.05), "thd_percent": ("rel_or_abs", 0.02, 0.005), "snr_db": ("abs", 0.5),
         "noise_floor_dbv": ("abs", 0.5), "rms_v": ("rel", 0.005)}
QUERY = {"rms_v": "MEAS:RMS?", "gain_db": "MEAS:GAIN?", "thd_percent": "MEAS:THD?", "snr_db": "MEAS:SNR?", "noise_floor_dbv": "MEAS:NOIS?"}


def within_guideline(kind: str, meas: float, truth: float) -> bool:
    g = GUIDE[kind]
    err = abs(meas - truth)
    if g[0] == "abs":
        return err <= g[1]
    if g[0] == "rel":
        return err <= g[1] * abs(truth)
    return err <= g[1] * abs(truth) or err <= g[2]


def sine_fit_amplitude(x: np.ndarray, f_hz: float, fs: float) -> float:
    """Least-squares amplitude of a sine at known frequency (independent of the analyzer's FFT)."""
    n = np.arange(x.size)
    a = np.column_stack([np.sin(2 * np.pi * f_hz * n / fs), np.cos(2 * np.pi * f_hz * n / fs), np.ones(x.size)])
    coef, *_ = np.linalg.lstsq(a, x, rcond=None)
    return float(math.hypot(coef[0], coef[1]))


def run(ctx: Ctx) -> dict[str, Any]:
    freqs, amps = (FREQS[::3], AMPS[:2]) if ctx.quick else (FREQS, AMPS)
    n_rep = 8 if ctx.quick else 30
    rows: list[dict[str, Any]] = []
    cross: list[dict[str, Any]] = []
    rep: list[dict[str, Any]] = []
    with ctx.stack(with_backend=False) as st:
        ctx.write_config({"frequencies_hz": freqs, "amplitudes_vpk": amps, "profiles": PROFILES, "firmware": "1.0.0",
                          "repeatability": {"n": n_rep, "frequency_hz": 1000, "amplitude_vpk": 0.05, "profile": "NORMAL"},
                          "guideline": GUIDE, "points": 16384, "sample_rate_hz": 48000,
                          "method": "direct SCPI on the simulator; each point: MF:ACQ:INIT then MEAS:*? on the same stored buffer; truth from mfsim.truth via experiments/truth_adapter.py",
                          "cross_check": "MF:ACQ:WAV? 16384 (6 significant digits) -> numpy time-domain RMS and least-squares sine-fit gain", "versions": st.versions()})
        sig, ana, dut = st.scpi_client("siggen"), st.scpi_client("analyzer", 15.0), st.scpi_client("dut")
        for c in (sig, ana, dut):
            c.write("*RST")
        sig.write("SOUR:FUNC SIN")
        sig.write("OUTP ON")
        sig.query("MF:FAULT?")            # barrier: setters on one connection are not ordered against other connections
        for prof in PROFILES:
            dut.write(f"MF:DUT:PROF {prof}")
            dut.query("MF:FAULT?")
            for f in freqs:
                for a in amps:
                    sig.write(f"SOUR:FREQ {f}")
                    sig.write(f"SOUR:VOLT {a}")
                    sig.query("MF:FAULT?")
                    ana.write("MF:ACQ:INIT")
                    ana.query("*OPC?")
                    truth = ta.expected_metrics(prof, "1.0.0", f, a)
                    meas = {k: float(ana.query(q)) for k, q in QUERY.items()}
                    for k, q in QUERY.items():
                        rows.append({"profile": prof, "frequency_hz": f, "amplitude_vpk": a, "kind": k, "measured": meas[k],
                                     "truth": truth[k], "error": meas[k] - truth[k],
                                     "rel_error_pct": (meas[k] - truth[k]) / truth[k] * 100 if truth[k] else None,
                                     "within_guideline": within_guideline(k, meas[k], truth[k])})
                    # independent time-domain cross-check on the same stored buffer
                    wav = np.array([float(v) for v in ana.query("MF:ACQ:WAV? 16384", timeout=15).split(",")])
                    rms_np = float(np.sqrt(np.mean(wav ** 2)))
                    amp_fit = sine_fit_amplitude(wav, f, 48000.0)
                    cross.append({"profile": prof, "frequency_hz": f, "amplitude_vpk": a, "n_samples": int(wav.size),
                                  "rms_scpi": meas["rms_v"], "rms_numpy": rms_np, "rms_rel_diff": (meas["rms_v"] - rms_np) / rms_np,
                                  "gain_scpi": meas["gain_db"], "gain_numpy_fit": 20 * math.log10(amp_fit / a),
                                  "gain_truth": truth["gain_db"]})
        # repeatability at 1 kHz / 0.05 / NORMAL
        dut.write("MF:DUT:PROF NORMAL"); sig.write("SOUR:FREQ 1000"); sig.write("SOUR:VOLT 0.05")
        dut.query("MF:FAULT?"); sig.query("MF:FAULT?")
        for i in range(n_rep):
            ana.write("MF:ACQ:INIT")
            rep.append({"i": i, **{k: float(ana.query(q)) for k, q in QUERY.items()}})
        for c in (sig, ana, dut):
            c.close()
    ctx.write_raw_json({"grid": rows, "cross_check": cross, "repeatability": rep})

    # ------------------------------------------------------------------ metrics from raw
    kinds = list(QUERY)
    m: dict[str, Any] = {"grid_points": len(rows) // len(kinds), "by_kind": {}, "by_kind_profile": {}, "worst_cases": {}}
    for k in kinds:
        sub = [r for r in rows if r["kind"] == k]
        rel = [r["rel_error_pct"] for r in sub if r["rel_error_pct"] is not None]
        m["by_kind"][k] = {"abs_error": error_stats([r["error"] for r in sub]), "rel_error_pct": error_stats(rel),
                           "within_guideline_rate": rate(sum(r["within_guideline"] for r in sub), len(sub)), "guideline": GUIDE[k]}
        for p in PROFILES:
            sp = [r for r in sub if r["profile"] == p]
            m["by_kind_profile"][f"{k}|{p}"] = {"abs_error": error_stats([r["error"] for r in sp]),
                                                "rel_error_pct": error_stats([r["rel_error_pct"] for r in sp if r["rel_error_pct"] is not None]),
                                                "within_guideline_rate": rate(sum(r["within_guideline"] for r in sp), len(sp))}
        worst = sorted(sub, key=lambda r: -abs(r["rel_error_pct"] if k in ("rms_v", "thd_percent") and r["rel_error_pct"] is not None else r["error"]))[:5]
        m["worst_cases"][k] = [{kk: r[kk] for kk in ("profile", "frequency_hz", "amplitude_vpk", "measured", "truth", "error", "rel_error_pct")} for r in worst]
    m["by_frequency_gain_abs_error"] = {str(f): error_stats([r["error"] for r in rows if r["kind"] == "gain_db" and r["frequency_hz"] == f]) for f in freqs}
    m["repeatability_1khz"] = {}
    for k in kinds:
        vals = [r[k] for r in rep]
        t = ta.expected_metrics("NORMAL", "1.0.0", 1000, 0.05)[k]
        s = summarize(vals)
        m["repeatability_1khz"][k] = {**s, "truth": t, "bias_vs_truth": s["mean"] - t, "std_rel_pct": s["std"] / abs(s["mean"]) * 100 if s["mean"] else None}
    rd = [abs(c["rms_rel_diff"]) for c in cross]
    gd = [c["gain_scpi"] - c["gain_numpy_fit"] for c in cross]
    gt = [c["gain_numpy_fit"] - c["gain_truth"] for c in cross]
    m["cross_check"] = {"n": len(cross), "rms_scpi_vs_numpy_rel_diff": {"max_abs": max(rd), "mean_abs": sum(rd) / len(rd)},
                        "gain_scpi_minus_numpy_fit_db": error_stats(gd), "gain_numpy_fit_minus_truth_db": error_stats(gt)}
    # defect detection: anything outside guideline is reported honestly (not tuned away)
    for k in ("gain_db", "snr_db", "noise_floor_dbv", "thd_percent"):
        r = m["by_kind"][k]["within_guideline_rate"]
        if r is not None and r < 1.0:
            ctx.log(f"note: {k}: {100 * r:.1f} % of grid points within the INTERFACE.md guideline")
    ctx.write_metrics(m)
    return {"gain_mae_db": m["by_kind"]["gain_db"]["abs_error"]["mae"], "thd_within_guideline": m["by_kind"]["thd_percent"]["within_guideline_rate"],
            "rms_cross_check_max_rel": m["cross_check"]["rms_scpi_vs_numpy_rel_diff"]["max_abs"]}
