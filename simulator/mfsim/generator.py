"""Signal-generator model: state and sample rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

FREQ_RANGE_HZ = (10.0, 20_000.0)
AMPLITUDE_RANGE_V = (0.0, 5.0)
SAMPLE_RATE_RANGE_HZ = (8_000.0, 192_000.0)
DEFAULT_SAMPLE_RATE_HZ = 48_000.0
NOISE_CREST_FACTOR = 3.0
"""``NOIS`` is Gaussian with sigma = amplitude / 3, clipped at +-amplitude."""


@dataclass
class SigGenState:
    """Configuration of the virtual signal generator (defaults are the ``*RST`` state).

    Samples are generated directly at ``sample_rate_hz`` without an anti-alias filter, so a tone
    above ``sample_rate_hz / 2`` (possible, e.g. 20 kHz at 8 kHz) aliases like on a real DAC.
    """

    function: str = "SIN"
    frequency_hz: float = 1000.0
    amplitude_vpk: float = 0.05
    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ
    output_on: bool = False
    chirp_start_hz: float = 20.0

    def render(self, n: int, preroll: int, noise_rng: Callable[[], np.random.Generator]) -> np.ndarray:
        """Render ``preroll + n`` samples; sample ``preroll`` is the first sample of the window.

        Periodic waveforms (``SIN``, ``SQU``) continue backwards into the pre-roll, so the
        analysed window always starts at phase 0 while the DUT filters are already in steady
        state.  The chirp sweeps linearly from ``chirp_start_hz`` at the first window sample
        to ``frequency_hz`` at the end of the window and is silent before it.  ``NOIS`` draws
        the window first, so the window does not depend on the pre-roll length.  With the
        output off the generator delivers zeros.

        Args:
            n: window length in samples.
            preroll: samples rendered before the window (DUT settling time).
            noise_rng: factory of the noise generator, called only for ``NOIS``.
        """
        total = preroll + n
        if not self.output_on or self.amplitude_vpk == 0.0:
            return np.zeros(total)
        amp = self.amplitude_vpk
        index = np.arange(-preroll, n, dtype=float)
        if self.function == "SIN":
            cycles = index * (self.frequency_hz / self.sample_rate_hz)
            return amp * np.sin(2.0 * np.pi * (cycles - np.floor(cycles)))
        if self.function == "SQU":
            cycles = index * (self.frequency_hz / self.sample_rate_hz)
            return np.where(cycles - np.floor(cycles) < 0.5, amp, -amp)
        if self.function == "CHIR":
            duration = n / self.sample_rate_hz
            t = np.maximum(index, 0.0) / self.sample_rate_hz
            sweep_rate = (self.frequency_hz - self.chirp_start_hz) / duration
            cycles = self.chirp_start_hz * t + 0.5 * sweep_rate * t * t
            chirp = amp * np.sin(2.0 * np.pi * cycles)
            chirp[:preroll] = 0.0
            return chirp
        rng = noise_rng()
        sigma = amp / NOISE_CREST_FACTOR
        window = np.clip(rng.standard_normal(n) * sigma, -amp, amp)
        lead = np.clip(rng.standard_normal(preroll) * sigma, -amp, amp)
        return np.concatenate((lead, window))
