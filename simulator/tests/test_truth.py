"""Analytic expectations: formulas, profile/firmware tables and the Butterworth responses."""

from __future__ import annotations

import math

import pytest

from mfsim import truth
from mfsim.firmware import FIRMWARE, effective_params
from mfsim.profiles import PROFILES


@pytest.mark.parametrize("name,row", [
    ("NORMAL", (20, 100, 8000, -80, 0.004, 0.01, 1.5)),
    ("LOWGAIN", (14, 100, 8000, -80, 0.004, 0.01, 1.5)),
    ("HIGHTHD", (20, 100, 8000, -80, 0.10, 0.30, 1.5)),
    ("NOISY", (20, 100, 8000, -50, 0.004, 0.01, 1.5)),
    ("CLIPPING", (20, 100, 8000, -80, 0.004, 0.01, 0.3)),
])
def test_profile_table_matches_interface(name, row):
    p = PROFILES[name]
    assert (p.gain_db, p.hpf_hz, p.lpf_hz, p.noise_dbv, p.hd2, p.hd3, p.clip_vpk) == row


def test_effective_params_firmware_modifications():
    base = PROFILES["NORMAL"]
    assert effective_params("NORMAL", "1.0.0") == base
    v110 = effective_params("normal", "1.1.0")
    assert v110.hd2 == pytest.approx(base.hd2 * 0.8)
    assert v110.noise_dbv == pytest.approx(base.noise_dbv - 1.0)
    assert (v110.hd3, v110.gain_db, v110.clip_vpk) == (base.hd3, base.gain_db, base.clip_vpk)
    v120 = effective_params("NORMAL", "1.2.0")
    assert v120.hd2 == pytest.approx(base.hd2 * FIRMWARE["1.2.0"].hd2_multiplier)
    assert v120.noise_dbv == pytest.approx(base.noise_dbv + 5.0)
    with pytest.raises(KeyError):
        effective_params("NORMAL", "9.9.9")
    with pytest.raises(KeyError):
        effective_params("NOPE", "1.0.0")


def test_gain_matches_hand_calculation_with_analog_butterworth():
    p = effective_params("NORMAL")
    u = 0.05 * 10.0 ** (20 / 20)
    compression = 1 + 0.75 * 0.01 * u * u
    hpf = 1 / math.sqrt(1 + (100 / 1000) ** 4)
    lpf = 1 / math.sqrt(1 + (1000 / 8000) ** 8)
    expected = 20 + 20 * math.log10(compression * hpf * lpf)
    assert truth.expected_gain_db(p, 1000, 0.05) == pytest.approx(expected, abs=0.002)
    assert truth.expected_gain_db(p, 1000, 0.05) == pytest.approx(20.016, abs=0.001)


def test_corner_frequencies_are_minus_3db():
    p = effective_params("NORMAL")
    assert truth.filter_gain_db(p, 100.0) == pytest.approx(-3.0103, abs=0.005)
    assert truth.filter_gain_db(p, 8000.0) == pytest.approx(-3.0103, abs=0.005)
    assert truth.filter_gain_db(p, 2000.0) == pytest.approx(0.0, abs=0.01)
    assert truth.filter_gain_db(p, 10.0) < -39.0          # 2nd order: 40 dB / decade below 100 Hz


def test_harmonic_distortion_formulas():
    p = effective_params("NORMAL")
    u = 0.5
    fundamental = truth.expected_fundamental_v(p, 1000, 0.05)
    harmonics = truth.expected_harmonic_v(p, 1000, 0.05)
    hpf = lambda f: 1 / math.sqrt(1 + (100 / f) ** 4)    # noqa: E731
    lpf = lambda f: 1 / math.sqrt(1 + (f / 8000) ** 8)   # noqa: E731
    assert harmonics[2] == pytest.approx(0.004 * u * u / 2 * hpf(2000) * lpf(2000), rel=1e-3)
    assert harmonics[3] == pytest.approx(0.01 * u ** 3 / 4 * hpf(3000) * lpf(3000), rel=1e-3)
    hd2 = truth.expected_hd2_percent(p, 1000, 0.05)
    hd3 = truth.expected_hd3_percent(p, 1000, 0.05)
    assert hd2 == pytest.approx(100 * harmonics[2] / fundamental)
    assert hd2 == pytest.approx(0.1, rel=0.01) and hd3 == pytest.approx(0.0624, rel=0.01)
    assert truth.expected_thd_percent(p, 1000, 0.05) == pytest.approx(math.hypot(hd2, hd3))


def test_noise_snr_and_rms():
    p = effective_params("NORMAL")
    assert truth.expected_noise_floor_dbv(p) == pytest.approx(-80 + 10 * math.log10(19980 / 24000))
    assert truth.expected_noise_floor_dbv(p) == pytest.approx(-80.796, abs=0.001)
    fundamental = truth.expected_fundamental_v(p, 1000, 0.05)
    snr = 20 * math.log10(fundamental / math.sqrt(2)) - truth.expected_noise_floor_dbv(p)
    assert truth.expected_snr_db(p, 1000, 0.05) == pytest.approx(snr)
    assert 71.5 < snr < 72.0
    rms = truth.expected_rms_v(p, 1000, 0.05)
    assert rms == pytest.approx(0.3542, abs=2e-4)
    assert rms > fundamental / math.sqrt(2)


def test_noise_band_is_cut_at_nyquist_for_low_sample_rates():
    p = effective_params("NORMAL")
    assert truth.expected_noise_floor_dbv(p, 8000.0) == pytest.approx(-80 + 10 * math.log10(3980 / 4000))
    assert truth.expected_noise_floor_dbv(p, 96000.0) == pytest.approx(-80 + 10 * math.log10(19980 / 48000))


@pytest.mark.parametrize("profile,symptom", [
    ("LOWGAIN", lambda p: abs(truth.expected_gain_db(p, 1000, 0.05) - 14.0) < 0.05),
    ("HIGHTHD", lambda p: 2.8 < truth.expected_thd_percent(p, 1000, 0.05) < 3.1),
    ("NOISY", lambda p: 41.0 < truth.expected_snr_db(p, 1000, 0.05) < 42.5
     and abs(truth.expected_noise_floor_dbv(p) + 51) < 0.5),
])
def test_profile_symptoms_in_truth(profile, symptom):
    assert symptom(effective_params(profile))


def test_firmware_1_2_0_regression_thresholds():
    old, new = effective_params("NORMAL", "1.0.0"), effective_params("NORMAL", "1.2.0")
    assert 1.5 <= truth.expected_thd_percent(new, 1000, 0.05) <= 3.0
    assert 4.0 <= truth.expected_noise_floor_dbv(new) - truth.expected_noise_floor_dbv(old) <= 6.0
    assert abs(truth.expected_gain_db(new, 1000, 0.05) - 20.0) < 0.1     # gain still passes
    assert truth.expected_thd_percent(old, 1000, 0.05) < 1.0


def test_firmware_1_1_0_is_a_maintenance_release():
    old, new = effective_params("NORMAL", "1.0.0"), effective_params("NORMAL", "1.1.0")
    assert truth.expected_noise_floor_dbv(new) < truth.expected_noise_floor_dbv(old)
    assert truth.expected_thd_percent(new, 1000, 0.05) < truth.expected_thd_percent(old, 1000, 0.05)


def test_clipping_has_no_closed_form():
    with pytest.raises(truth.ClippingError):
        truth.expected_gain_db(effective_params("CLIPPING"), 1000, 0.05)
    # far below the clip level the same profile is linear again
    assert truth.expected_gain_db(effective_params("CLIPPING"), 1000, 0.001) == pytest.approx(20.0, abs=0.01)


def test_thd_aliasing_and_resolvability():
    p = effective_params("NORMAL")
    # 10 kHz: H3 = 30 kHz aliases to 18 kHz (attenuated by the low-pass), H2 = 20 kHz
    thd = truth.expected_thd_percent(p, 10_000, 0.05)
    h = truth.expected_harmonic_v(p, 10_000, 0.05)
    assert thd == pytest.approx(100 * math.hypot(h[2], h[3]) / truth.expected_fundamental_v(p, 10_000, 0.05))
    # 8 kHz: H3 lands on Nyquist (24 kHz) where it is not resolvable, H2 = 16 kHz is
    thd8 = truth.expected_thd_percent(p, 8_000, 0.05)
    assert thd8 == pytest.approx(100 * h2_only(p, 8_000), rel=1e-6)


def h2_only(p, f):
    return truth.expected_harmonic_v(p, f, 0.05)[2] / truth.expected_fundamental_v(p, f, 0.05)
