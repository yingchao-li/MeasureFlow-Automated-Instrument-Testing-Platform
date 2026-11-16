"""Analytic expectations used by tests and experiments (independent of what the instruments measured).

Thin layer over :mod:`mfsim.truth` (closed-form formulas, not the FFT estimators). For the CLIPPING
profile ``mfsim.truth`` raises ``ClippingError`` (no closed form); there the expectation is computed
numerically here from the *definition* of the DUT chain (polynomial -> hard clip -> filters), using only
numpy and the public filter-response function - never the analyzer's estimators.

``expected_status`` derives the verdict a measurement *should* get from the expectation and the limits
alone, plus a ``margin`` (distance of the expectation from the nearest limit relative to a stated
measurement uncertainty) so borderline cases can be treated separately instead of being silently
counted as right or wrong.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "simulator") not in sys.path:
    sys.path.insert(0, str(_ROOT / "simulator"))

import mfsim.truth as truth  # noqa: E402
from mfsim.dsp import MAX_HARMONIC, design_chain, fold_frequency, harmonic_bins  # noqa: E402  (geometry/filters only)

FS = 48000.0
POINTS = 16384

# 1-sigma-ish measurement uncertainty budget (documented in experiment configs): a verdict is only
# "unambiguous" when the expectation is farther than this from the nearest limit.
UNCERTAINTY = {"rms": 0.003, "gain": 0.05, "thd": 0.05, "snr": 0.3, "noise_floor": 0.3, "freq_sweep": 0.05}
UNCERTAINTY_IS_RELATIVE = {"rms": True, "gain": False, "thd": True, "snr": False, "noise_floor": False, "freq_sweep": False}

KIND_TO_METRIC = {"rms": "rms_v", "gain": "gain_db", "thd": "thd_percent", "snr": "snr_db",
                  "noise_floor": "noise_floor_dbv", "freq_sweep": "gain_db"}
KIND_UNIT = {"rms": "V", "gain": "dB", "thd": "%", "snr": "dB", "noise_floor": "dBV", "freq_sweep": "dB"}


def _clipping_expectation(params: Any, f: float, a: float, fs: float = FS, points: int = POINTS) -> dict[str, float]:
    """Numerical expectation for a hard-clipped DUT (no closed form).

    The clipped sine is expanded in a Fourier series (harmonics 1..1000; their power decays ~1/h^4 because the
    clipped sine is continuous). The DUT is a sampled system with a point-wise nonlinearity in front of LTI
    filters, so harmonic ``h`` appears at ``fold(h*f, fs)`` and is shaped by the filter response *there*.
    The analyzer's definition (INTERFACE.md section 3.3) excludes only the resolvable H2..H10 lines from the
    in-band noise; residual distortion above H10 therefore counts as noise - exactly as modelled here.
    """
    u = a * 10 ** (params.gain_db / 20)
    n = 1 << 15
    th = 2 * np.pi * np.arange(n) / n
    x = u * np.sin(th)
    y = np.clip(x + params.hd2 * x ** 2 + params.hd3 * x ** 3, -params.clip_vpk, params.clip_vpk)
    spec = np.fft.rfft(y) * (2.0 / n)
    hmax = 1000
    amp = np.abs(spec[1:hmax + 1])          # amp[h-1] = amplitude of harmonic h
    chain = design_chain(params.hpf_hz, params.lpf_hz, fs)
    folded = np.array([fold_frequency(h * f, fs) for h in range(1, hmax + 1)])
    mag = np.abs(chain.response(folded, fs))
    out = amp * mag                          # out[h-1]
    fund = float(out[0])
    resolvable = {h for h, _ in harmonic_bins(f * points / fs, points)}
    excluded = {h for h in range(2, MAX_HARMONIC + 1) if h in resolvable}
    thd = 100 * math.sqrt(sum(float(out[h - 1]) ** 2 for h in excluded)) / fund
    in_band = (folded >= 20.0) & (folded <= 20000.0)
    resid = sum(0.5 * float(out[h - 1]) ** 2 for h in range(2, hmax + 1) if h not in excluded and in_band[h - 1])
    white_inband = 10 ** (truth.expected_noise_floor_dbv(params, fs) / 10)
    noise_inband = white_inband + resid
    rms = math.sqrt(0.5 * float(np.sum(out ** 2)) + 10 ** (params.noise_dbv / 10))
    return {"rms_v": rms, "gain_db": 20 * math.log10(fund / a), "thd_percent": thd,
            "snr_db": 10 * math.log10(0.5 * fund ** 2 / noise_inband), "noise_floor_dbv": 10 * math.log10(noise_inband)}


def expected_metrics(profile: str, firmware: str, freq_hz: float, amp_vpk: float,
                     fs: float = FS, points: int = POINTS) -> dict[str, float]:
    """Expected ``rms_v, gain_db, thd_percent, snr_db, noise_floor_dbv`` for the named DUT state."""
    p = truth.effective_params(profile, firmware)
    try:
        return {
            "rms_v": truth.expected_rms_v(p, freq_hz, amp_vpk, fs),
            "gain_db": truth.expected_gain_db(p, freq_hz, amp_vpk, fs),
            "thd_percent": truth.expected_thd_percent(p, freq_hz, amp_vpk, fs, points),
            "snr_db": truth.expected_snr_db(p, freq_hz, amp_vpk, fs),
            "noise_floor_dbv": truth.expected_noise_floor_dbv(p, fs),
        }
    except truth.ClippingError:
        return _clipping_expectation(p, freq_hz, amp_vpk, fs, points)


def expected_value(kind: str, profile: str, firmware: str, freq_hz: float, amp_vpk: float) -> float:
    return expected_metrics(profile, firmware, freq_hz, amp_vpk)[KIND_TO_METRIC[kind]]


# Hard clipping has no closed form; the Fourier-series model above agrees with the simulator to a few percent
# (aliasing of high harmonics at high frequencies is not modelled exactly), so wider uncertainty applies.
CLIP_UNCERTAINTY = {"rms": 0.04, "gain": 0.4, "thd": 0.08, "freq_sweep": 0.4}
# In-band noise/SNR of a clipped signal depend on how residual distortion above H10 is aliased: not analytically
# determinable here -> such tasks are always 'borderline' (reported, never judged).
INDETERMINATE = {("CLIPPING", "snr"), ("CLIPPING", "noise_floor")}


def uncertainty(kind: str, value: float, profile: Optional[str] = None) -> float:
    if profile and profile.upper() == "CLIPPING" and kind in CLIP_UNCERTAINTY:
        u = CLIP_UNCERTAINTY[kind]
        return abs(value) * u if UNCERTAINTY_IS_RELATIVE[kind] else u
    u = UNCERTAINTY[kind]
    return abs(value) * u if UNCERTAINTY_IS_RELATIVE[kind] else u


@dataclass
class Expectation:
    status: str              # PASS | FAIL
    expected: float
    margin: float            # distance to nearest limit minus uncertainty (>0 -> unambiguous)
    direction: Optional[str]  # OUT_OF_TOLERANCE_LOW / HIGH for FAIL


def expected_status(kind: str, expected: float, lim_min: Optional[float], lim_max: Optional[float],
                    profile: Optional[str] = None) -> Expectation:
    """Verdict implied by the analytic ``expected`` value and the limits (never uses a measurement)."""
    u = uncertainty(kind, expected, profile)
    dists = []
    if lim_min is not None:
        dists.append(expected - lim_min)
    if lim_max is not None:
        dists.append(lim_max - expected)
    below = lim_min is not None and expected < lim_min
    above = lim_max is not None and expected > lim_max
    margin = (min(abs(d) for d in dists) if dists else math.inf) - u
    if profile and (profile.upper(), kind) in INDETERMINATE:
        margin = -math.inf
    if below:
        return Expectation("FAIL", expected, margin, "OUT_OF_TOLERANCE_LOW")
    if above:
        return Expectation("FAIL", expected, margin, "OUT_OF_TOLERANCE_HIGH")
    return Expectation("PASS", expected, margin, None)


def task_expectation(task: dict[str, Any]) -> Expectation:
    """Expectation for one *persisted task* (uses task inputs, DUT state and limits only)."""
    inp = task["inputs"]
    freq = float(inp["frequency_hz"])
    amp = float(inp["amplitude_vpk"])
    val = expected_value(task["kind"], task["dut_profile"], task["dut_firmware"], freq, amp)
    lim = task["limits"]
    return expected_status(task["kind"], val, lim["min"], lim["max"], task["dut_profile"])


def within_tolerance(kind: str, measured: float, expected: float, profile: Optional[str] = None) -> tuple[bool, float]:
    """Is ``measured`` within the per-kind test tolerance of ``expected``? Returns (ok, error).

    Clean DUT: rms 1 %, gain/sweep 0.1 dB, THD max(10 % rel, 0.01 %-pt), SNR/noise 1 dB.
    CLIPPING (numerical model only): rms 4 %, gain 0.4 dB, THD max(8 % rel, 0.01 %-pt); SNR/noise not judged.
    """
    err = measured - expected
    if profile and profile.upper() == "CLIPPING":
        if (profile.upper(), kind) in INDETERMINATE:
            return True, err
        limit = {"rms": abs(expected) * 0.04, "gain": 0.4, "freq_sweep": 0.4, "thd": max(abs(expected) * 0.08, 0.01)}[kind]
        return abs(err) <= limit, err
    limit = {"rms": abs(expected) * 0.01, "gain": 0.1, "freq_sweep": 0.1, "thd": max(abs(expected) * 0.10, 0.01),
             "snr": 1.0, "noise_floor": 1.0}[kind]
    return abs(err) <= limit, err
