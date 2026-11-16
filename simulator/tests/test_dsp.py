"""Spectral estimators and filter design against signals with known content."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import sosfilt

from mfsim import dsp

FS = 48000.0
N = 16384


def sine(freq: float, amp: float = 1.0, phase: float = 0.0, n: int = N, fs: float = FS) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / fs + phase)


def test_window_properties():
    win = dsp.flattop_window(N)
    assert abs(win.samples[0]) < 1e-12                   # tapers to zero: no broadband skirt
    assert win.samples.max() == pytest.approx(1.0)
    assert win.sum_w == pytest.approx(win.samples.sum())
    assert win.sum_w2 == pytest.approx(float(np.dot(win.samples, win.samples)))
    enbw_bins = N * win.sum_w2 / win.sum_w ** 2
    assert enbw_bins == pytest.approx(4.54, abs=0.01)    # HFT144D
    assert dsp.flattop_window(N) is win                  # cached


def test_displayed_peak_reads_amplitude_for_any_frequency():
    worst = 0.0
    for frac in np.linspace(0.0, 1.0, 21):
        freq = (341 + frac) * FS / N
        spectrum = dsp.SpectralAnalysis(sine(freq, 0.5), FS).amplitude_dbv()
        worst = max(worst, abs(spectrum.max() - 20 * math.log10(0.5)))
    assert worst < 0.003                                  # scalloping error of HFT144D is 0.0021 dB


def test_spectrum_shape_and_floor():
    analysis = dsp.SpectralAnalysis(np.zeros(N), FS)
    spectrum = analysis.amplitude_dbv()
    assert spectrum.shape == (N // 2 + 1,)
    assert np.all(spectrum == -300.0)


@pytest.mark.parametrize("freq", [37.0, 100.0, 997.3, 1000.0, 4321.987, 12000.0, 19999.0])
def test_bin_power_summation_amplitude_and_frequency(freq):
    amp = 0.0123
    analysis = dsp.SpectralAnalysis(sine(freq, amp, phase=1.1), FS)
    assert 20 * math.log10(analysis.fundamental_amplitude / amp) == pytest.approx(0.0, abs=1e-4)
    assert analysis.frequency_hz == pytest.approx(freq, abs=0.005)


def test_white_noise_level_is_unbiased_with_and_without_tone():
    sigma = 1e-3
    errors = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        x = sine(1234.5, 0.5) + sigma * rng.standard_normal(N)
        analysis = dsp.SpectralAnalysis(x, FS)
        expected = 20 * math.log10(sigma) + 10 * math.log10(19980 / 24000)
        errors.append(analysis.noise_dbv(exclude_tone=True) - expected)
        # without exclusion the tone dominates
        assert analysis.noise_dbv(exclude_tone=False) > analysis.noise_dbv(exclude_tone=True) + 20
    assert abs(np.mean(errors)) < 0.1
    assert np.std(errors) < 0.2 and max(abs(e) for e in errors) < 0.5


def test_leakage_of_a_strong_tone_does_not_bias_the_noise_floor():
    """71 dB tone-to-noise: the window skirt must stay far below the noise (HFT144D, not scipy flattop)."""
    sigma = 1e-4
    rng = np.random.default_rng(1)
    x = sine(1000.0, 0.5) + sigma * rng.standard_normal(N)
    expected = 20 * math.log10(sigma) + 10 * math.log10(19980 / 24000)
    assert dsp.SpectralAnalysis(x, FS).noise_dbv(True) == pytest.approx(expected, abs=0.3)


def test_thd_recovers_known_harmonics():
    f = 1000.0
    x = sine(f, 1.0) + sine(2 * f, 0.002, 0.3) + sine(3 * f, 0.001, 1.0) + sine(5 * f, 0.0005, 2.0)
    analysis = dsp.SpectralAnalysis(x, FS)
    harmonics = analysis.harmonic_amplitudes()
    assert harmonics[2] == pytest.approx(0.002, rel=2e-3)
    assert harmonics[3] == pytest.approx(0.001, rel=2e-3)
    assert harmonics[5] == pytest.approx(0.0005, rel=2e-3)
    assert harmonics[4] == pytest.approx(0.0, abs=1e-6)
    expected = 100 * math.sqrt(0.002 ** 2 + 0.001 ** 2 + 0.0005 ** 2)
    assert analysis.thd_percent() == pytest.approx(expected, rel=2e-3)


def test_thd_includes_harmonic_up_to_h10_only():
    f = 1000.0
    x = sine(f) + sine(10 * f, 0.01) + sine(11 * f, 0.5)
    assert dsp.SpectralAnalysis(x, FS).thd_percent() == pytest.approx(1.0, rel=2e-3)


def test_thd_counts_aliased_harmonic_at_folded_frequency():
    f = 10_000.0                                           # 3f = 30 kHz folds to 18 kHz
    x = sine(f) + sine(18_000.0, 0.01)
    assert dsp.SpectralAnalysis(x, FS).harmonic_amplitudes()[3] == pytest.approx(0.01, rel=2e-3)


def test_snr_of_tone_in_noise():
    sigma = 2e-3
    x = sine(2000.0, 1.0) + sigma * np.random.default_rng(5).standard_normal(N)
    expected = 10 * math.log10(0.5 / (sigma ** 2 * 19980 / 24000))
    assert dsp.SpectralAnalysis(x, FS).snr_db() == pytest.approx(expected, abs=0.4)


def test_degenerate_signals_do_not_raise():
    silent = dsp.SpectralAnalysis(np.zeros(N), FS)
    assert silent.noise_dbv(True) == -math.inf
    assert silent.snr_db() == -math.inf
    assert silent.fundamental_amplitude == 0.0


def test_harmonic_bins_rules():
    n = N
    b = 1000.0 * n / FS
    assert [h for h, _ in dsp.harmonic_bins(b, n)] == list(range(2, 11))
    # fundamental close to DC: low harmonics overlap the fundamental's lobe and are dropped
    low = [h for h, _ in dsp.harmonic_bins(20.0 * n / FS, n)]
    assert 2 not in low and low                            # 6.8 bins spacing < 2 * lobe width
    # 8 kHz: H3 sits exactly on Nyquist, outside the usable bins
    assert 3 not in [h for h, _ in dsp.harmonic_bins(8000.0 * n / FS, n)]
    # 10 kHz: H3 aliases to 18 kHz and is reported there
    pos = dict(dsp.harmonic_bins(10_000.0 * n / FS, n))[3]
    assert pos * FS / n == pytest.approx(18_000.0)
    # fs/4: H5 aliases onto the fundamental and must be dropped
    assert 5 not in [h for h, _ in dsp.harmonic_bins(12_000.0 * n / FS, n)]


def test_fold_frequency():
    assert dsp.fold_frequency(30_000.0, FS) == 18_000.0
    assert dsp.fold_frequency(1000.0, FS) == 1000.0
    assert dsp.fold_frequency(48_000.0, FS) == 0.0
    assert dsp.fold_frequency(72_000.0, FS) == 24_000.0


def test_inband_bins():
    k_lo, k_hi, width = dsp.inband_bins(N, FS)
    assert (k_lo, k_hi, width) == (7, 6826, 19980.0)
    k_lo, k_hi, width = dsp.inband_bins(N, 8000.0)         # band is cut at Nyquist
    assert k_hi == N // 2 - 1 and width == 3980.0


def test_filter_chain_corners_and_order():
    chain = dsp.design_chain(100.0, 8000.0, FS)
    assert chain.sos.shape == (3, 6)                       # 1 biquad (2nd order) + 2 biquads (4th order)
    mag = np.abs(chain.response(np.array([100.0, 8000.0, 1000.0, 10.0, 16000.0]), FS))
    assert 20 * np.log10(mag[0]) == pytest.approx(-3.01, abs=0.01)
    assert 20 * np.log10(mag[1]) == pytest.approx(-3.01, abs=0.01)
    assert 20 * np.log10(mag[2]) == pytest.approx(0.0, abs=0.01)
    assert 20 * np.log10(mag[3]) == pytest.approx(-40.0, abs=0.3)      # 12 dB/oct high-pass
    assert 20 * np.log10(mag[4]) < -24.0                                # 24 dB/oct low-pass
    assert dsp.design_chain(100.0, 8000.0, FS) is chain               # cached


def test_filter_chain_bypasses_corners_beyond_nyquist():
    chain = dsp.design_chain(100.0, 8000.0, 8000.0)        # LPF 8 kHz >= Nyquist of 4 kHz
    assert chain.sos.shape[0] == 1
    none = dsp.design_chain(5000.0, 8000.0, 8000.0)
    assert none.sos.shape[0] == 0 and none.settle_samples == 0
    assert np.all(none.response(np.array([100.0, 1000.0]), 8000.0) == 1.0)


@pytest.mark.parametrize("hpf", [20.0, 100.0, 1000.0])
def test_settle_samples_cover_the_start_up_transient(hpf):
    chain = dsp.design_chain(hpf, 8000.0, FS)
    step = np.ones(chain.settle_samples + 2000)
    out = sosfilt(chain.sos, step)                        # steady state of a step is 0 (high-pass)
    assert np.max(np.abs(out[chain.settle_samples:])) < 1e-8
    assert np.max(np.abs(out[: chain.settle_samples // 4])) > 1e-3
