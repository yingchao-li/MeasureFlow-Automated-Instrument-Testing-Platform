"""Device-under-test model: configuration state and the signal chain."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import sosfilt

from .dsp import FilterChain
from .firmware import DEFAULT_FIRMWARE, apply_firmware
from .profiles import PROFILES, DutParams

FAULT_MODES = ("NONE", "NAN", "INF")
_FAULT_SAMPLES = 3


@dataclass
class DutState:
    """Configuration of the virtual DUT (defaults are the ``*RST`` state).

    ``profile`` is a key of :data:`mfsim.profiles.PROFILES` or ``"CUSTOM"`` after an individual
    parameter was changed.  ``params`` always holds the *configured* values; the signal
    processing uses :meth:`effective`.
    """

    profile: str = "NORMAL"
    params: DutParams = field(default_factory=lambda: PROFILES["NORMAL"])
    firmware: str = DEFAULT_FIRMWARE
    fault: str = "NONE"

    def effective(self) -> DutParams:
        """Parameters after the firmware modifications."""
        return apply_firmware(self.params, self.firmware)


def process(stimulus: np.ndarray, params: DutParams, chain: FilterChain, preroll: int,
            noise_rng: np.random.Generator, fault: str) -> np.ndarray:
    """Run the hearing-aid chain on ``stimulus`` and return the analysed window.

    ``stimulus`` carries ``preroll`` extra leading samples that let the filters reach steady
    state; they are dropped from the result.  Chain, in order: gain, polynomial
    ``y = u + hd2*u^2 + hd3*u^3``, hard clip, 2nd-order high-pass, 4th-order low-pass, and white
    Gaussian noise whose RMS (``10^(noise_dbv/20)`` V) is spread over the full Nyquist band.
    A ``fault`` of ``NAN`` or ``INF`` overwrites a few output samples with a non-finite value.
    """
    u = stimulus * 10.0 ** (params.gain_db / 20.0)
    y = u * (1.0 + u * (params.hd2 + params.hd3 * u))
    np.clip(y, -params.clip_vpk, params.clip_vpk, out=y)
    if chain.sos.shape[0]:
        y = sosfilt(chain.sos, y)
    out = y[preroll:]
    out += 10.0 ** (params.noise_dbv / 20.0) * noise_rng.standard_normal(out.size)
    if fault != "NONE":
        positions = np.linspace(0, out.size - 1, _FAULT_SAMPLES + 2, dtype=int)[1:-1]
        out[positions] = math.nan if fault == "NAN" else math.inf
    return out
