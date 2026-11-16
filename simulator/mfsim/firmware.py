"""Simulated DUT firmware versions.

A firmware version modifies the *effective* parameters on top of the loaded profile.  The values
reported by ``MF:DUT:CONF?`` stay those of the profile; only the signal processing (and
:func:`mfsim.truth.effective_params`) sees the modified numbers.

Effect table (all relative to the profile values):

======= ============================ ================ ================ =========================
version role                         noise offset     hd2 multiplier   hd3 multiplier
======= ============================ ================ ================ =========================
1.0.0   baseline                      0 dB             1                1
1.1.0   maintenance release          -1 dB (RMS)      0.8              1
1.2.0   regression build             +5 dB (RMS)      20               3
======= ============================ ================ ================ =========================

Tuning of ``1.2.0`` (NORMAL profile, 1 kHz, 0.05 Vpk, i.e. 0.5 V after the 20 dB gain)::

    HD2 / fundamental = hd2 * U / 2        = 0.004*20 * 0.5 / 2     = 2.0 %
    HD3 / fundamental = hd3 * U^2 / 4      = 0.01*3 * 0.25 / 4      = 0.19 %
    THD               = sqrt(2.0^2 + 0.19^2)                         = 2.0 %   (target 1.5 ... 3 %)

so the regression is dominated by even-order distortion, the gain stays within 0.04 dB of the
baseline (the hd3 compression term ``1 + 3/4*hd3*U^2`` only grows from 1.0019 to 1.0056) and the
noise floor rises by exactly 5 dB (target +4 ... +6 dB).  Multipliers act on the *profile* values, so a
profile that already has strong distortion (HIGHTHD) becomes much worse under 1.2.0; effective
values may therefore exceed the 0 ... 1 range that is accepted for the configured values.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .profiles import PROFILES, DutParams


@dataclass(frozen=True)
class FirmwareEffect:
    """Modification a firmware version applies to the profile values."""

    description: str
    noise_db_offset: float = 0.0
    hd2_multiplier: float = 1.0
    hd3_multiplier: float = 1.0


FIRMWARE: dict[str, FirmwareEffect] = {
    "1.0.0": FirmwareEffect("baseline"),
    "1.1.0": FirmwareEffect("maintenance release: slightly lower noise, less 2nd-harmonic distortion",
                            noise_db_offset=-1.0, hd2_multiplier=0.8),
    "1.2.0": FirmwareEffect("regression build: strong even-order distortion and higher noise floor",
                            noise_db_offset=5.0, hd2_multiplier=20.0, hd3_multiplier=3.0),
}
"""Accepted firmware versions of ``MF:DUT:FW``."""

DEFAULT_FIRMWARE = "1.0.0"


def apply_firmware(params: DutParams, firmware: str) -> DutParams:
    """Return the effective parameters of ``params`` running firmware ``firmware``.

    Raises:
        KeyError: unknown firmware version.
    """
    effect = FIRMWARE[firmware]
    return replace(
        params,
        noise_dbv=params.noise_dbv + effect.noise_db_offset,
        hd2=params.hd2 * effect.hd2_multiplier,
        hd3=params.hd3 * effect.hd3_multiplier,
    )


def effective_params(profile: str, firmware: str = DEFAULT_FIRMWARE) -> DutParams:
    """Effective parameters of a named profile under a firmware version.

    Args:
        profile: key of :data:`mfsim.profiles.PROFILES` (case-insensitive).
        firmware: key of :data:`FIRMWARE`.

    Raises:
        KeyError: unknown profile or firmware.
    """
    return apply_firmware(PROFILES[profile.upper()], firmware)
