"""Signal-processing kernels: DUT filter design and the analyzer's spectral estimators.

Window choice
-------------
The analyzer uses the 7-term cosine **flat-top window HFT144D** (Heinzel, Rüdiger, Schilling,
"Spectrum and spectral density estimation by the DFT", 2002).  Candidates were compared on
16384 points with a non-coherent tone (see ``tests/test_dsp.py`` for the regression checks):

=================== ============ ================= ======================================
window              ENBW [bins]  peak scalloping    total leakage outside +-8 bins [dBc]
=================== ============ ================= ======================================
scipy ``flattop``   3.77         0.010 dB          -81  (end points != 0)
Blackman-Harris 4   2.00         0.826 dB          -92
HFT144D (chosen)    4.54         0.002 dB          -137 (end points == 0)
=================== ============ ================= ======================================

* A flat-top is required so that a sine of peak amplitude ``A`` reads ``A`` in the displayed
  spectrum (``MF:ACQ:FFT?``) for *any* frequency; Blackman-Harris would misread by up to 0.83 dB.
* scipy's 5-term flat-top does not taper to zero at the ends; its broadband skirt (-81 dBc in
  total) would add ~0.5 dB to the in-band noise estimate of a 0.5 V tone over an -80 dBV
  noise floor (71 dB SNR, 110 dB tone-to-noise-bin ratio).  HFT144D keeps the bias far below 0.01 dB.

Estimators
----------
With window ``w`` and ``X = rfft(x*w)`` the *variance in bin k* (single-sided) is
``var[k] = 2*|X[k]|^2 / (N*sum(w^2))``.  Parseval makes the sum of ``var`` over the bins of a
spectral component equal to that component's mean-square value, independent of where the
frequency falls between bins ("bin-power summation"), and white noise of variance ``s^2`` gives
``E[var[k]] = 2*s^2/N`` per bin.  Hence

* a tone of peak amplitude ``A``: ``A = sqrt(2 * sum(var over its lobe))`` (lobe = +-8 bins),
* in-band noise: mean ``var`` of the bins that are not tone/harmonic lobes, times the analytic
  number of bins in the band (so the noise hidden under the excluded lobes is accounted for),
* the displayed spectrum uses the coherent gain instead: ``2*|X[k]|/sum(w)``.

Limits: lines closer than 17 bins to DC, to Nyquist or to each other cannot be separated; such
harmonics are ignored by THD (see :func:`harmonic_bins`), so THD of fundamentals below
about 17 bins (50 Hz at 16384 points / 48 kHz; raise ``MF:ACQ:POIN`` to resolve lower tones) reads low.
The usable dynamic range is about 130 dB (window leakage -137 dBc).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property, lru_cache

import numpy as np
from scipy.signal import butter, sos2zpk, sosfreqz

BAND_LO_HZ = 20.0
BAND_HI_HZ = 20_000.0
MAX_HARMONIC = 10
LOBE_HALF_WIDTH = 8
"""Bins on each side of a spectral line that belong to it (main lobe of HFT144D is +-7 bins)."""

WINDOW_NAME = "FLATTOP"
_FLOOR_V = 1e-15
_SETTLE_RESIDUAL = 1e-9
_MAX_SETTLE = 400_000
_HFT144D = (1.0, 1.96760033, 1.57983607, 0.81123644, 0.22583558, 0.02773848, 0.00090360)


# --------------------------------------------------------------------------------------------
# DUT filters
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FilterChain:
    """High-pass (2nd order) followed by low-pass (4th order) Butterworth as second-order sections.

    Attributes:
        sos: ``(sections, 6)`` coefficients; zero rows when both filters are bypassed.
        settle_samples: number of samples after which the start-up transient of the slowest pole
            has decayed below ``1e-9`` of its initial amplitude (the DUT is rendered with this
            much pre-roll so that the analysed window is steady state).
    """

    sos: np.ndarray
    settle_samples: int

    def response(self, freq_hz: np.ndarray, sample_rate_hz: float) -> np.ndarray:
        """Complex frequency response of the digital chain at ``freq_hz``."""
        if self.sos.shape[0] == 0:
            return np.ones(np.shape(freq_hz), dtype=complex)
        _, h = sosfreqz(self.sos, worN=np.atleast_1d(freq_hz), fs=sample_rate_hz)
        return h


@lru_cache(maxsize=128)
def design_chain(hpf_hz: float, lpf_hz: float, sample_rate_hz: float) -> FilterChain:
    """Design (and cache) the DUT filter chain.

    The bilinear transform with frequency pre-warping puts the -3 dB points exactly at the
    configured corners.  A corner at or above 99 % of Nyquist cannot be realised and is bypassed.
    """
    nyquist = sample_rate_hz / 2.0
    sections = []
    if hpf_hz < 0.99 * nyquist:
        sections.append(butter(2, hpf_hz, btype="highpass", fs=sample_rate_hz, output="sos"))
    if lpf_hz < 0.99 * nyquist:
        sections.append(butter(4, lpf_hz, btype="lowpass", fs=sample_rate_hz, output="sos"))
    if not sections:
        return FilterChain(np.empty((0, 6)), 0)
    sos = np.vstack(sections)
    pole_radius = float(np.max(np.abs(sos2zpk(sos)[1])))
    settle = math.ceil(math.log(_SETTLE_RESIDUAL) / math.log(pole_radius))
    return FilterChain(sos, min(settle, _MAX_SETTLE))


# --------------------------------------------------------------------------------------------
# Window and spectrum geometry
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Window:
    """Analysis window with the sums needed for amplitude and power scaling."""

    samples: np.ndarray
    sum_w: float
    sum_w2: float


@lru_cache(maxsize=8)
def flattop_window(n: int) -> Window:
    """Periodic HFT144D flat-top window of length ``n`` (peak normalised to 1)."""
    phase = 2.0 * np.pi * np.arange(n) / n
    w = np.zeros(n)
    for i, a in enumerate(_HFT144D):
        w += (-1.0) ** i * a * np.cos(i * phase)
    w /= w.max()
    return Window(w, float(w.sum()), float(np.dot(w, w)))


def fold_frequency(position: float, period: float) -> float:
    """Alias a frequency into ``[0, period/2]``.

    ``period`` is the sample rate when ``position`` is in Hz, or the DFT length when it is in bins.
    """
    r = position % period
    return period - r if r > period / 2 else r


def harmonic_bins(fundamental_bin: float, n: int) -> list[tuple[int, float]]:
    """Harmonics H2..H10 whose spectral lines can be separated from the others.

    Harmonics above Nyquist alias exactly like the sampled DUT output does, so they are located
    at their folded position.  A harmonic is *resolvable* when its +-8 bin lobe lies inside bins
    ``1 .. n/2-1`` and does not overlap the lobe of the fundamental or of an earlier harmonic.

    Returns:
        ``[(h, folded_position_in_bins), ...]`` in ascending ``h``.
    """
    accepted = [round(fundamental_bin)]
    found: list[tuple[int, float]] = []
    for h in range(2, MAX_HARMONIC + 1):
        pos = fold_frequency(h * fundamental_bin, n)
        k = round(pos)
        if k - LOBE_HALF_WIDTH < 1 or k + LOBE_HALF_WIDTH > n // 2 - 1:
            continue
        if any(abs(k - other) <= 2 * LOBE_HALF_WIDTH for other in accepted):
            continue
        accepted.append(k)
        found.append((h, pos))
    return found


def inband_bins(n: int, sample_rate_hz: float) -> tuple[int, int, float]:
    """Index range ``(k_lo, k_hi)`` and bandwidth in Hz of the 20 Hz ... 20 kHz noise band.

    The band is cut at Nyquist for low sample rates.
    """
    df = sample_rate_hz / n
    f_hi = min(BAND_HI_HZ, sample_rate_hz / 2.0)
    k_lo = math.ceil(BAND_LO_HZ / df)
    k_hi = min(math.floor(f_hi / df), n // 2 - 1)
    return k_lo, k_hi, f_hi - BAND_LO_HZ


# --------------------------------------------------------------------------------------------
# Spectral analysis of one buffer
# --------------------------------------------------------------------------------------------
class SpectralAnalysis:
    """Windowed spectrum of one real buffer and the audio measurements derived from it.

    All methods assume ``samples`` are finite; the analyzer checks that first.
    """

    def __init__(self, samples: np.ndarray, sample_rate_hz: float) -> None:
        n = int(samples.size)
        win = flattop_window(n)
        spectrum = np.fft.rfft(samples * win.samples)
        self._power = spectrum.real ** 2 + spectrum.imag ** 2
        self._win = win
        self.n = n
        self.sample_rate_hz = float(sample_rate_hz)
        self.bin_hz = self.sample_rate_hz / n
        self._var = self._power * (2.0 / (n * win.sum_w2))
        self._noise_cache: dict[bool, np.ndarray] = {}

    # -- displayed spectrum ---------------------------------------------------------------
    def amplitude_dbv(self) -> np.ndarray:
        """Single-sided peak-amplitude spectrum in dBV (coherent-gain compensated).

        A sine of peak amplitude ``A`` reads ``20*log10(A)`` within 0.002 dB at any frequency.
        DC and Nyquist bins are not doubled.  Empty bins are floored at -300 dBV.
        """
        amp = np.sqrt(self._power) * (2.0 / self._win.sum_w)
        amp[0] *= 0.5
        amp[-1] *= 0.5
        return 20.0 * np.log10(np.maximum(amp, _FLOOR_V))

    # -- line geometry --------------------------------------------------------------------
    def _lobe(self, k: int) -> tuple[int, int]:
        return max(1, k - LOBE_HALF_WIDTH), min(self.n // 2 - 1, k + LOBE_HALF_WIDTH)

    @cached_property
    def _peak(self) -> tuple[int, float]:
        """Strongest bin and the power centroid of its lobe (an unbiased frequency estimate,
        because the squared window response is symmetric about the true frequency)."""
        k0 = 2 + int(np.argmax(self._var[2:self.n // 2 - 1]))
        lo, hi = self._lobe(k0)
        v = self._var[lo:hi + 1]
        total = float(v.sum())
        return k0, (float(np.dot(np.arange(lo, hi + 1), v)) / total if total > 0.0 else float(k0))

    @property
    def frequency_hz(self) -> float:
        """Estimated frequency of the strongest spectral line in Hz."""
        return self._peak[1] * self.bin_hz

    # -- noise ----------------------------------------------------------------------------
    def _noise_bins(self, exclude_tone: bool) -> np.ndarray:
        """Variances of the in-band bins that do not belong to the tone or H2..H10."""
        cached = self._noise_cache.get(exclude_tone)
        if cached is not None:
            return cached
        k_lo, k_hi, _ = inband_bins(self.n, self.sample_rate_hz)
        keep = np.ones(k_hi - k_lo + 1, dtype=bool)
        if exclude_tone:
            for h in range(1, MAX_HARMONIC + 1):
                a, z = self._lobe(round(fold_frequency(h * self._peak[1], self.n)))
                a, z = max(a, k_lo), min(z, k_hi)
                if a <= z:
                    keep[a - k_lo:z - k_lo + 1] = False
        selected = self._var[k_lo:k_hi + 1][keep]
        self._noise_cache[exclude_tone] = selected
        return selected

    def _noise_per_bin(self, exclude_tone: bool) -> float:
        """Mean variance per bin of the noise bins (the definition of the in-band noise power)."""
        selected = self._noise_bins(exclude_tone)
        return float(selected.mean()) if selected.size else math.nan

    @cached_property
    def _robust_noise_per_bin(self) -> float:
        """Noise variance per bin that ignores spurious lines: ``median / ln 2``.

        The bins of white noise are exponentially distributed (chi-square, 2 degrees of freedom),
        whose median is ``ln 2`` times the mean.  Used to remove the noise that sits inside a
        harmonic's lobe, so that an unrelated in-band spur cannot cancel a small harmonic.
        """
        selected = self._noise_bins(True)
        return float(np.median(selected)) / math.log(2.0) if selected.size else 0.0

    def inband_noise_variance(self, exclude_tone: bool) -> float:
        """In-band (20 Hz ... 20 kHz) noise power in V^2, tone and H2..H10 lobes excluded if asked."""
        _, _, band_hz = inband_bins(self.n, self.sample_rate_hz)
        return self._noise_per_bin(exclude_tone) * band_hz / self.bin_hz

    def noise_dbv(self, exclude_tone: bool) -> float:
        """In-band noise level in dBV RMS."""
        variance = self.inband_noise_variance(exclude_tone)
        return 10.0 * math.log10(variance) if variance > 0 else -math.inf

    # -- tone and harmonics ---------------------------------------------------------------
    def _line_amplitude(self, k: int) -> float:
        """Peak amplitude of the line centred at bin ``k``, noise-power corrected."""
        lo, hi = self._lobe(k)
        power = float(self._var[lo:hi + 1].sum()) - self._robust_noise_per_bin * (hi - lo + 1)
        return math.sqrt(2.0 * max(power, 0.0))

    @property
    def fundamental_amplitude(self) -> float:
        """Peak amplitude of the strongest spectral line in V."""
        return self._line_amplitude(self._peak[0])

    def harmonic_amplitudes(self) -> dict[int, float]:
        """Peak amplitudes of the resolvable harmonics H2..H10 in V."""
        return {h: self._line_amplitude(round(pos)) for h, pos in harmonic_bins(self._peak[1], self.n)}

    def thd_percent(self) -> float:
        """Total harmonic distortion in percent: ``100*sqrt(sum Hh^2)/H1`` for h = 2..10."""
        harmonics = self.harmonic_amplitudes()
        return 100.0 * math.sqrt(sum(a * a for a in harmonics.values())) / self.fundamental_amplitude

    def snr_db(self) -> float:
        """Fundamental power over in-band noise power (tone and harmonics excluded) in dB."""
        signal = 0.5 * self.fundamental_amplitude ** 2
        noise = self.inband_noise_variance(True)
        if signal <= 0.0 or noise <= 0.0:
            return -math.inf if signal <= 0.0 else math.inf
        return 10.0 * math.log10(signal / noise)
