"""The shared test bench: signal path ``SigGen -> DUT -> Analyzer`` and the acquisition model."""

from __future__ import annotations

import math
import threading
from functools import cached_property

import numpy as np

from .dsp import SpectralAnalysis, design_chain
from .dut import DutState, process
from .generator import SigGenState

DEFAULT_SEED = 12345
DEFAULT_POINTS = 16384
POINTS_RANGE = (1024, 65536)
_STREAM_STIMULUS = 0
_STREAM_DUT_NOISE = 1


class Acquisition:
    """One captured buffer: the stimulus reference, the DUT output and the settings they came from.

    Spectral analyses are computed lazily and cached, so repeated ``MEAS:*?`` queries on the same
    acquisition are cheap and return identical values.
    """

    def __init__(self, index: int, sample_rate_hz: float, generator: SigGenState,
                 stimulus: np.ndarray, output: np.ndarray) -> None:
        self.index = index
        self.sample_rate_hz = sample_rate_hz
        self.function = generator.function
        self.frequency_hz = generator.frequency_hz
        self.amplitude_vpk = generator.amplitude_vpk
        self.output_on = generator.output_on
        self.stimulus = stimulus
        self.output = output

    @property
    def tone_present(self) -> bool:
        """True when a sine of non-zero amplitude is applied (gain/THD/SNR preconditions)."""
        return self.function == "SIN" and self.output_on and self.amplitude_vpk > 0.0

    @cached_property
    def finite(self) -> bool:
        """False if the DUT output contains NaN or Inf samples."""
        return bool(np.isfinite(self.output).all())

    @cached_property
    def output_analysis(self) -> SpectralAnalysis:
        """Spectral analysis of the DUT output."""
        return SpectralAnalysis(self.output, self.sample_rate_hz)

    @cached_property
    def stimulus_analysis(self) -> SpectralAnalysis:
        """Spectral analysis of the generator output (the gain reference)."""
        return SpectralAnalysis(self.stimulus, self.sample_rate_hz)

    @cached_property
    def rms_v(self) -> float:
        """Time-domain RMS of the DUT output in volts (all spectral content)."""
        return math.sqrt(float(np.mean(self.output * self.output)))

    @cached_property
    def gain_db(self) -> float:
        """20*log10(fundamental out / fundamental in), both from the same estimator."""
        out = self.output_analysis.fundamental_amplitude
        ref = self.stimulus_analysis.fundamental_amplitude
        if out <= 0.0:
            return -math.inf
        return 20.0 * math.log10(out / ref)


class Bench:
    """State shared by the three instruments, guarded by :attr:`lock`.

    Acquisition ``i`` (``i`` = value of :attr:`counter` before the acquisition) draws its noise
    from ``default_rng([seed, i, stream])``, so identical command sequences give identical
    numbers.  Any configuration change drops the stored acquisition; the next ``MEAS``/``WAV``/
    ``FFT`` query then acquires again.
    """

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self.lock = threading.RLock()
        self.default_seed = seed
        self.siggen = SigGenState()
        self.dut = DutState()
        self.points = DEFAULT_POINTS
        self.seed = seed
        self.counter = 0
        self.stored: Acquisition | None = None

    def invalidate(self) -> None:
        """Drop the stored acquisition (called on every configuration change)."""
        self.stored = None

    def reset_acquisition_state(self) -> None:
        """Restore the default seed, zero the acquisition counter and drop the stored buffer."""
        self.seed = self.default_seed
        self.counter = 0
        self.stored = None

    def _rng(self, index: int, stream: int) -> np.random.Generator:
        return np.random.default_rng([self.seed, index, stream])

    def acquire(self) -> Acquisition:
        """Render a fresh buffer through ``SigGen -> DUT`` and store it."""
        index = self.counter
        fs = self.siggen.sample_rate_hz
        params = self.dut.effective()
        chain = design_chain(params.hpf_hz, params.lpf_hz, fs)
        n = self.points
        stimulus = self.siggen.render(n, chain.settle_samples,
                                      lambda: self._rng(index, _STREAM_STIMULUS))
        output = process(stimulus, params, chain, chain.settle_samples,
                         self._rng(index, _STREAM_DUT_NOISE), self.dut.fault)
        self.counter += 1
        self.stored = Acquisition(index, fs, self.siggen, stimulus[chain.settle_samples:], output)
        return self.stored

    def current(self) -> Acquisition:
        """The stored acquisition, acquiring once if there is none."""
        return self.stored if self.stored is not None else self.acquire()
