"""Analytic expectations of the DUT measurements (INTERFACE.md section 3.5).

Everything here is a closed-form formula in the DUT parameters.  None of it uses the FFT
estimators of the analyzer, so it is an independent ground truth for comparing what the
instruments report.

Physics (no clipping)
---------------------
A sine of peak amplitude ``a`` enters the DUT and becomes ``U = a * 10^(gain_db/20)`` after the
gain stage.  The polynomial ``y = u + hd2*u^2 + hd3*u^3`` turns ``U*sin(t)`` into::

    DC          hd2*U^2/2                 (removed by the high-pass)
    fundamental U + 3/4*hd3*U^3  =  U*(1 + 3/4*hd3*U^2)     (gain compression/expansion)
    2nd harmonic hd2*U^2/2           ->  HD2 = hd2*U/2        relative to U
    3rd harmonic hd3*U^3/4           ->  HD3 = hd3*U^2/4      relative to U

Each component is then multiplied by the magnitude response ``|H(f)|`` of the digital
high-pass/low-pass chain at *its own* frequency; harmonics above Nyquist alias to the folded
frequency exactly as in the sampled DUT.  The additive white noise has RMS ``10^(noise_dbv/20)``
over ``0 ... fs/2``, so the noise inside the 20 Hz ... 20 kHz band is lower by
``10*log10(band_width / (fs/2))``.

Every function takes *effective* parameters (profile after firmware modifications), obtained
with :func:`effective_params`::

    p = effective_params("NORMAL", "1.0.0")
    expected_gain_db(p, 1000.0, 0.05)        # 20.016 dB
"""

from __future__ import annotations

import math

import numpy as np

from .dsp import BAND_HI_HZ, BAND_LO_HZ, MAX_HARMONIC, design_chain, fold_frequency, harmonic_bins
from .firmware import FIRMWARE, apply_firmware, effective_params
from .generator import DEFAULT_SAMPLE_RATE_HZ
from .profiles import PROFILES, DutParams

__all__ = [
    "DutParams", "PROFILES", "FIRMWARE", "ClippingError", "apply_firmware", "effective_params",
    "filter_gain_db", "expected_fundamental_v", "expected_harmonic_v", "expected_gain_db",
    "expected_hd2_percent", "expected_hd3_percent", "expected_thd_percent",
    "expected_noise_floor_dbv", "expected_snr_db", "expected_rms_v",
]

_DEFAULT_POINTS = 16384
_PEAK_GRID = 4096


class ClippingError(ValueError):
    """Raised when the hard clip is reached, where the closed-form expectations do not apply."""


def filter_gain_db(params: DutParams, freq_hz: float,
                   sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Magnitude response of the DUT high-pass x low-pass chain at ``freq_hz`` in dB.

    Uses ``scipy.signal.sosfreqz`` on the very filters the DUT runs, i.e. the exact digital
    response (bilinear transform), not the analog prototype.
    """
    return 20.0 * math.log10(_filter_magnitude(params, freq_hz, sample_rate_hz))


def _filter_magnitude(params: DutParams, freq_hz: float, sample_rate_hz: float) -> float:
    chain = design_chain(params.hpf_hz, params.lpf_hz, sample_rate_hz)
    return float(np.abs(chain.response(np.array([freq_hz]), sample_rate_hz))[0])


def _post_gain_amplitude(params: DutParams, amplitude_vpk: float) -> float:
    return amplitude_vpk * 10.0 ** (params.gain_db / 20.0)


def _check_linear(params: DutParams, u: float) -> None:
    theta = np.linspace(0.0, 2.0 * np.pi, _PEAK_GRID)
    x = u * np.sin(theta)
    peak = float(np.max(np.abs(x + params.hd2 * x ** 2 + params.hd3 * x ** 3)))
    if peak > params.clip_vpk:
        raise ClippingError(
            f"peak {peak:.4g} V before the clip exceeds clip_vpk={params.clip_vpk:g} V; "
            "no closed-form expectation exists")


def expected_fundamental_v(params: DutParams, freq_hz: float, amplitude_vpk: float,
                           sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Peak amplitude of the fundamental at the DUT output: ``|H(f)| * U * (1 + 3/4*hd3*U^2)``."""
    u = _post_gain_amplitude(params, amplitude_vpk)
    _check_linear(params, u)
    return _filter_magnitude(params, freq_hz, sample_rate_hz) * u * (1.0 + 0.75 * params.hd3 * u * u)


def expected_harmonic_v(params: DutParams, freq_hz: float, amplitude_vpk: float,
                        sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> dict[int, float]:
    """Peak amplitudes of H2 and H3 at the DUT output, keyed by harmonic number.

    The polynomial has no terms above the cube, so H4..H10 are exactly zero without clipping.
    Each harmonic is attenuated by the chain at its (folded) frequency ``fold(h*f)``.
    """
    u = _post_gain_amplitude(params, amplitude_vpk)
    _check_linear(params, u)
    raw = {2: 0.5 * params.hd2 * u * u, 3: 0.25 * params.hd3 * u ** 3}
    folded = {h: fold_frequency(h * freq_hz, sample_rate_hz) for h in raw}
    return {h: a * _filter_magnitude(params, folded[h], sample_rate_hz) for h, a in raw.items()}


def expected_gain_db(params: DutParams, freq_hz: float, amplitude_vpk: float,
                     sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Expected ``MEAS:GAIN?``: fundamental out over fundamental in, dB."""
    out = expected_fundamental_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    return 20.0 * math.log10(out / amplitude_vpk)


def _harmonic_percent(params: DutParams, freq_hz: float, amplitude_vpk: float,
                      sample_rate_hz: float, harmonic: int) -> float:
    fundamental = expected_fundamental_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    return 100.0 * expected_harmonic_v(params, freq_hz, amplitude_vpk, sample_rate_hz)[harmonic] / fundamental


def expected_hd2_percent(params: DutParams, freq_hz: float, amplitude_vpk: float,
                         sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Second harmonic relative to the fundamental at the output, percent."""
    return _harmonic_percent(params, freq_hz, amplitude_vpk, sample_rate_hz, 2)


def expected_hd3_percent(params: DutParams, freq_hz: float, amplitude_vpk: float,
                         sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Third harmonic relative to the fundamental at the output, percent."""
    return _harmonic_percent(params, freq_hz, amplitude_vpk, sample_rate_hz, 3)


def expected_thd_percent(params: DutParams, freq_hz: float, amplitude_vpk: float,
                         sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
                         points: int = _DEFAULT_POINTS) -> float:
    """Expected ``MEAS:THD?`` in percent: ``100*sqrt(sum_{h=2..10} Hh^2)/H1``.

    Only harmonics the analyzer can resolve are summed (see
    :func:`mfsim.dsp.harmonic_bins`); ``points`` is the acquisition length that sets the bin
    width.  For tones above about fs/6 the aliased H3 is included at its folded frequency.
    """
    harmonics = expected_harmonic_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    fundamental = expected_fundamental_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    fundamental_bin = freq_hz * points / sample_rate_hz
    resolvable = {h for h, _ in harmonic_bins(fundamental_bin, points)}
    power = sum(a * a for h, a in harmonics.items() if h in resolvable and h <= MAX_HARMONIC)
    return 100.0 * math.sqrt(power) / fundamental


def expected_noise_floor_dbv(params: DutParams,
                             sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Expected ``MEAS:NOIS?`` (tone excluded) in dBV RMS for a distortion-free output.

    ``noise_dbv + 10*log10((min(20 kHz, fs/2) - 20 Hz) / (fs/2))``; 48 kHz gives ``-0.796 dB``.
    """
    top = min(BAND_HI_HZ, sample_rate_hz / 2.0)
    return params.noise_dbv + 10.0 * math.log10((top - BAND_LO_HZ) / (sample_rate_hz / 2.0))


def expected_snr_db(params: DutParams, freq_hz: float, amplitude_vpk: float,
                    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Expected ``MEAS:SNR?``: fundamental power over in-band noise power, dB."""
    fundamental = expected_fundamental_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    noise_dbv = expected_noise_floor_dbv(params, sample_rate_hz)
    return 10.0 * math.log10(0.5 * fundamental ** 2) - noise_dbv


def expected_rms_v(params: DutParams, freq_hz: float, amplitude_vpk: float,
                   sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> float:
    """Expected ``MEAS:RMS?``: root of (fundamental^2/2 + harmonics^2/2 + full-band noise power)."""
    fundamental = expected_fundamental_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    harmonics = expected_harmonic_v(params, freq_hz, amplitude_vpk, sample_rate_hz)
    noise_power = 10.0 ** (params.noise_dbv / 10.0)
    return math.sqrt(0.5 * fundamental ** 2 + 0.5 * sum(a * a for a in harmonics.values()) + noise_power)
