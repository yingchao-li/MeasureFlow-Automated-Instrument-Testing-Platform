"""DUT parameter sets (INTERFACE.md section 3.4).

The device under test is a simplified hearing-aid signal chain::

    input -> gain -> y = u + hd2*u^2 + hd3*u^3 -> hard clip at +-clip_vpk
          -> high-pass (2nd order Butterworth) -> low-pass (4th order Butterworth)
          -> + white Gaussian output noise (full Nyquist band)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DutParams:
    """Parameters of the DUT chain.

    Attributes:
        gain_db: linear voltage gain in front of the nonlinearity, dB.
        hpf_hz: -3 dB corner of the 2nd-order Butterworth high-pass, Hz.
        lpf_hz: -3 dB corner of the 4th-order Butterworth low-pass, Hz.
        noise_dbv: RMS of the white output noise over the *full* Nyquist band, dBV.
        hd2: quadratic coefficient of the polynomial (second-harmonic generator).
        hd3: cubic coefficient of the polynomial (third-harmonic generator, gain compression).
        clip_vpk: symmetric hard-clip level after the polynomial, V peak.
    """

    gain_db: float
    hpf_hz: float
    lpf_hz: float
    noise_dbv: float
    hd2: float
    hd3: float
    clip_vpk: float


_BASE = DutParams(gain_db=20.0, hpf_hz=100.0, lpf_hz=8000.0, noise_dbv=-80.0,
                  hd2=0.004, hd3=0.01, clip_vpk=1.5)

PROFILES: dict[str, DutParams] = {
    "NORMAL": _BASE,
    "LOWGAIN": DutParams(14.0, 100.0, 8000.0, -80.0, 0.004, 0.01, 1.5),
    "HIGHTHD": DutParams(20.0, 100.0, 8000.0, -80.0, 0.10, 0.30, 1.5),
    "NOISY": DutParams(20.0, 100.0, 8000.0, -50.0, 0.004, 0.01, 1.5),
    "CLIPPING": DutParams(20.0, 100.0, 8000.0, -80.0, 0.004, 0.01, 0.3),
}
"""Profile table of INTERFACE.md section 3.4, keyed by upper-case profile name."""
