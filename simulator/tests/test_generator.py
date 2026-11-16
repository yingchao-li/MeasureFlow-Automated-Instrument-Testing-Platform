"""Signal generator: rendered samples checked by FFT and by direct inspection."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mfsim import dsp
from mfsim.generator import SigGenState


def render(state: SigGenState, n: int = 16384, preroll: int = 0, seed: int = 1) -> np.ndarray:
    return state.render(n, preroll, lambda: np.random.default_rng(seed))


@pytest.mark.parametrize("freq,amp,fs", [(1000, 0.05, 48000), (20, 1.0, 48000), (19999, 2.5, 48000),
                                         (440.5, 5.0, 96000), (3000, 0.001, 8000), (300, 0.3, 192000)])
def test_sine_frequency_and_amplitude_by_fft(freq, amp, fs):
    state = SigGenState("SIN", freq, amp, fs, True)
    analysis = dsp.SpectralAnalysis(render(state), fs)
    assert analysis.frequency_hz == pytest.approx(freq, abs=0.01 * freq / 1000 + 0.01)
    if freq >= 100:                                       # below that the DC image overlaps the lobe
        assert analysis.fundamental_amplitude == pytest.approx(amp, rel=1e-4)
    assert np.max(np.abs(render(state))) <= amp * (1 + 1e-12)


def test_ten_hertz_sine_in_the_time_domain():
    x = render(SigGenState("SIN", 10.0, 0.3, 48000, True))
    crossings = np.flatnonzero(np.diff(np.signbit(x))) + 1
    assert np.all(np.abs(np.diff(crossings) - 2400) <= 1)  # half period = 2400 samples
    assert np.max(x) == pytest.approx(0.3, rel=1e-4)


def test_sine_starts_at_phase_zero_rising():
    x = render(SigGenState("SIN", 1000, 0.5, 48000, True))
    assert x[0] == 0.0 and x[1] > 0.0
    assert x[1] == pytest.approx(0.5 * math.sin(2 * math.pi * 1000 / 48000))
    assert x[12] == pytest.approx(0.5 * math.sin(2 * math.pi * 12 * 1000 / 48000))


def test_preroll_continues_the_waveform_backwards():
    state = SigGenState("SIN", 1234.5, 0.5, 48000, True)
    plain = render(state, 4096, 0)
    padded = render(state, 4096, 777)
    assert padded.size == 4096 + 777
    np.testing.assert_allclose(padded[777:], plain, atol=1e-12)
    # the pre-roll is the same sine at negative time
    assert padded[776] == pytest.approx(-0.5 * math.sin(2 * math.pi * 1234.5 / 48000))


def test_output_off_or_zero_amplitude_gives_silence():
    assert not render(SigGenState("SIN", 1000, 0.5, 48000, False)).any()
    assert not render(SigGenState("SIN", 1000, 0.0, 48000, True)).any()
    assert not render(SigGenState("NOIS", 1000, 0.5, 48000, False), preroll=10).any()


def test_square_wave_levels_duty_and_harmonics():
    state = SigGenState("SQU", 1000, 0.7, 48000, True)
    x = render(state)
    assert set(np.unique(x)) == {-0.7, 0.7}
    assert abs(np.mean(x > 0) - 0.5) < 0.01
    assert x[0] == 0.7                                    # starts with the positive half period
    analysis = dsp.SpectralAnalysis(x, 48000.0)
    assert analysis.fundamental_amplitude == pytest.approx(0.7 * 4 / math.pi, rel=0.01)
    assert analysis.harmonic_amplitudes()[3] == pytest.approx(0.7 * 4 / math.pi / 3, rel=0.02)
    assert analysis.harmonic_amplitudes()[2] < 0.01 * analysis.fundamental_amplitude


def test_chirp_sweeps_linearly_from_start_to_stop_frequency():
    n, fs = 16384, 48000.0
    state = SigGenState("CHIR", 8000.0, 1.0, fs, True, chirp_start_hz=500.0)
    x = render(state, n)
    assert x[0] == 0.0 and np.max(np.abs(x)) <= 1.0
    # instantaneous frequency from zero-crossing spacing near the start and near the end
    def local_frequency(lo: int, hi: int) -> float:
        seg = x[lo:hi]
        crossings = np.flatnonzero(np.diff(np.signbit(seg)))
        return 0.5 * fs / np.mean(np.diff(crossings))
    t_mid_early, t_mid_late = 1024, n - 1024
    for centre in (t_mid_early, t_mid_late):
        expected = 500.0 + (8000.0 - 500.0) * centre / n
        assert local_frequency(centre - 256, centre + 256) == pytest.approx(expected, rel=0.03)
    # plain (rectangular) FFT: a linear chirp has a flat spectrum between start and stop frequency
    magnitude = 20 * np.log10(np.abs(np.fft.rfft(x)))
    freqs = np.arange(magnitude.size) * fs / n
    in_sweep = magnitude[(freqs > 1000) & (freqs < 7500)]
    assert in_sweep.max() - in_sweep.min() < 6.0
    assert magnitude[freqs > 9500].max() < in_sweep.min() - 12.0     # rectangular-window skirt
    assert magnitude[freqs < 250].max() < in_sweep.min() - 12.0
    # the flat-top weights the sweep in time, so the analyzer's spectrum peaks at the sweep centre
    windowed = dsp.SpectralAnalysis(x, fs)
    assert windowed.frequency_hz == pytest.approx(4250.0, rel=0.05)


def test_chirp_is_silent_in_the_preroll_and_independent_of_it():
    state = SigGenState("CHIR", 5000.0, 0.8, 48000.0, True)
    padded = render(state, 2048, 500)
    assert not padded[:500].any()
    np.testing.assert_allclose(padded[500:], render(state, 2048, 0))


def test_noise_statistics_and_whiteness():
    amp = 0.9
    x = render(SigGenState("NOIS", 1000, amp, 48000, True), 65536)
    assert np.max(np.abs(x)) <= amp                       # clipped at +-amplitude
    assert np.std(x) == pytest.approx(amp / 3, rel=0.02)
    assert abs(np.mean(x)) < 0.005
    spectrum = 10 ** (dsp.SpectralAnalysis(x, 48000.0).amplitude_dbv() / 10)
    low, high = spectrum[200:5000].mean(), spectrum[10000:30000].mean()
    assert low == pytest.approx(high, rel=0.1)            # white


def test_noise_is_reproducible_and_window_independent_of_preroll():
    state = SigGenState("NOIS", 1000, 1.0, 48000, True)
    a, b = render(state, 1000, 0, seed=7), render(state, 1000, 0, seed=7)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, render(state, 1000, 0, seed=8))
    np.testing.assert_array_equal(render(state, 1000, 300, seed=7)[300:], a)
