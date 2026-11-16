"""DUT chain through the bench: measurements against the analytic truth and profile symptoms."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from mfsim import truth
from mfsim.bench import Acquisition, Bench
from mfsim.dsp import design_chain
from mfsim.dut import process
from mfsim.profiles import PROFILES


def make_bench(profile: str = "NORMAL", firmware: str = "1.0.0", freq: float = 1000.0, amp: float = 0.05,
               fs: float = 48000.0, seed: int = 12345) -> Bench:
    bench = Bench(seed)
    bench.dut.profile, bench.dut.firmware = profile, firmware
    bench.dut.params = PROFILES[profile]
    bench.siggen.frequency_hz, bench.siggen.amplitude_vpk = freq, amp
    bench.siggen.sample_rate_hz, bench.siggen.output_on = fs, True
    return bench


def measure(bench: Bench, runs: int = 1) -> dict[str, float]:
    """Mean of each metric over ``runs`` acquisitions."""
    keys = ("gain", "thd", "snr", "noise", "rms", "freq")
    values = {k: [] for k in keys}
    for _ in range(runs):
        acq = bench.acquire()
        an = acq.output_analysis
        for key, value in zip(keys, (acq.gain_db, an.thd_percent(), an.snr_db(), an.noise_dbv(True),
                                     acq.rms_v, an.frequency_hz), strict=True):
            values[key].append(value)
    return {k: float(np.mean(v)) for k, v in values.items()}


def test_normal_profile_matches_truth_at_1khz():
    bench = make_bench()
    p = bench.dut.effective()
    m = measure(bench, runs=20)
    assert m["gain"] == pytest.approx(truth.expected_gain_db(p, 1000, 0.05), abs=0.005)
    assert m["thd"] == pytest.approx(truth.expected_thd_percent(p, 1000, 0.05), rel=0.02)
    assert m["snr"] == pytest.approx(truth.expected_snr_db(p, 1000, 0.05), abs=0.15)
    assert m["noise"] == pytest.approx(truth.expected_noise_floor_dbv(p), abs=0.15)
    assert m["rms"] == pytest.approx(truth.expected_rms_v(p, 1000, 0.05), rel=2e-3)
    assert m["freq"] == pytest.approx(1000.0, abs=0.01)
    # numbers promised by INTERFACE.md section 3.4
    assert 19.9 < m["gain"] < 20.2 and 0.1 <= m["thd"] <= 0.2 and 70 < m["snr"] < 73 and -82 < m["noise"] < -80


@pytest.mark.parametrize("freq,amp", [(100, 0.05), (250, 0.1), (1000, 0.05), (2500, 0.1), (4000, 0.1),
                                      (8000, 0.05), (12000, 0.05), (16000, 0.05)])
def test_gain_thd_and_noise_follow_truth_across_frequency(freq, amp):
    bench = make_bench(freq=freq, amp=amp)
    p = bench.dut.effective()
    m = measure(bench, runs=8)
    assert m["gain"] == pytest.approx(truth.expected_gain_db(p, freq, amp), abs=0.01)
    expected_thd = truth.expected_thd_percent(p, freq, amp)
    assert m["thd"] == pytest.approx(expected_thd, rel=0.03, abs=0.004)
    assert m["noise"] == pytest.approx(truth.expected_noise_floor_dbv(p), abs=0.2)
    assert m["snr"] == pytest.approx(truth.expected_snr_db(p, freq, amp), abs=0.25)


def test_aliased_third_harmonic_is_part_of_thd_at_10khz():
    """H3 = 30 kHz folds to 18 kHz at fs = 48 kHz and must be counted there (wide-open low-pass)."""
    bench = make_bench(freq=10_000.0, amp=0.05)
    bench.dut.params = replace(bench.dut.params, lpf_hz=20_000.0, hd2=0.05, hd3=0.2)
    p = bench.dut.effective()
    thd = measure(bench, runs=6)["thd"]
    h = truth.expected_harmonic_v(p, 10_000, 0.05)
    assert thd == pytest.approx(truth.expected_thd_percent(p, 10_000, 0.05), rel=0.02)
    h2_only = 100 * h[2] / truth.expected_fundamental_v(p, 10_000, 0.05)
    assert thd > 1.3 * h2_only                              # the aliased H3 adds ~40 %


def test_rms_of_non_integer_cycle_window_matches_truth_within_leakage():
    bench = make_bench(freq=100.0)
    rms = measure(bench)["rms"]
    assert rms == pytest.approx(truth.expected_rms_v(bench.dut.effective(), 100.0, 0.05), rel=3e-3)


def test_lowgain_profile_fails_gain_and_rms():
    m = measure(make_bench("LOWGAIN"), runs=4)
    assert m["gain"] == pytest.approx(14.0, abs=0.05)
    assert m["rms"] < 0.318                               # below the RMS lower limit of the sequences
    assert m["thd"] < 0.3


def test_highthd_profile_shows_three_percent_thd():
    m = measure(make_bench("HIGHTHD"), runs=4)
    assert 2.8 < m["thd"] < 3.1
    p = make_bench("HIGHTHD").dut.effective()
    assert m["gain"] == pytest.approx(truth.expected_gain_db(p, 1000, 0.05), abs=0.01)


def test_noisy_profile_shows_low_snr_and_high_noise_floor():
    m = measure(make_bench("NOISY"), runs=6)
    assert m["snr"] == pytest.approx(41.8, abs=0.5)
    assert m["noise"] == pytest.approx(-50.8, abs=0.3)
    assert m["gain"] == pytest.approx(20.016, abs=0.02)
    assert m["thd"] == pytest.approx(0.1177, abs=0.02)    # noise is subtracted from the harmonic bins


def test_clipping_profile_clips_hard():
    bench = make_bench("CLIPPING")
    acq = bench.acquire()
    clip = 0.3
    peak = np.max(np.abs(acq.output))
    assert clip - 0.03 < peak < clip + 0.07                # clipped at 0.3 V, filters add some ringing
    assert peak < 0.5 * 0.8                                # far below the unclipped 0.5 V
    m = measure(bench)
    assert m["thd"] > 10.0                                 # large THD
    assert m["rms"] < 0.30                                 # low RMS (unclipped would be 0.354)
    assert m["gain"] < 20.0 - 2.0


def test_gain_stage_hpf_and_lpf_commands_shape_the_response():
    bench = make_bench(freq=100.0)
    flat = measure(bench)["gain"]
    bench.dut.params = replace(bench.dut.params, hpf_hz=1000.0)
    assert measure(bench)["gain"] < flat - 35.0           # 100 Hz is a decade below a 1 kHz 2nd-order HPF
    bench = make_bench(freq=8000.0)
    assert measure(bench)["gain"] == pytest.approx(20.016 - 3.01, abs=0.05)       # LPF corner


@pytest.mark.parametrize("hpf", [20.0, 100.0, 1000.0])
def test_analysed_window_is_steady_state(hpf):
    """Tripling the pre-roll must not change a single output sample: no start-up transient remains."""
    bench = make_bench()
    bench.dut.params = replace(bench.dut.params, hpf_hz=hpf, hd2=0.05)       # hd2 adds a DC step
    params = bench.dut.effective()
    chain = design_chain(params.hpf_hz, params.lpf_hz, 48000.0)
    outputs = []
    for preroll in (chain.settle_samples, 3 * chain.settle_samples):
        stimulus = bench.siggen.render(4096, preroll, lambda: np.random.default_rng(0))
        outputs.append(process(stimulus, params, chain, preroll, np.random.default_rng(1), "NONE"))
    np.testing.assert_allclose(outputs[0], outputs[1], atol=1e-7)
    assert abs(np.mean(outputs[0])) < 2e-3                  # DC from hd2 is blocked by the high-pass


def test_sample_rate_changes_filters_and_truth():
    bench = make_bench(fs=96000.0, freq=4000.0)
    p = bench.dut.effective()
    m = measure(bench, runs=4)
    assert m["gain"] == pytest.approx(truth.expected_gain_db(p, 4000.0, 0.05, 96000.0), abs=0.01)
    assert m["noise"] == pytest.approx(truth.expected_noise_floor_dbv(p, 96000.0), abs=0.2)


def test_low_sample_rate_bypasses_unrealisable_low_pass():
    bench = make_bench(fs=8000.0, freq=500.0)
    assert design_chain(100.0, 8000.0, 8000.0).sos.shape[0] == 1
    p = bench.dut.effective()
    assert measure(bench)["gain"] == pytest.approx(truth.expected_gain_db(p, 500.0, 0.05, 8000.0), abs=0.01)


def test_firmware_regression_1_2_0_on_normal_profile():
    old = measure(make_bench(firmware="1.0.0"), runs=12)
    new = measure(make_bench(firmware="1.2.0"), runs=12)
    assert 1.5 <= new["thd"] <= 3.0                        # fails the 1 % limit
    assert 4.0 <= new["noise"] - old["noise"] <= 6.0       # noise +4 ... +6 dB
    assert abs(new["gain"] - old["gain"]) < 0.1            # gain still passes
    assert 19.0 < new["gain"] < 21.0
    assert old["thd"] < 1.0


def test_firmware_1_1_0_maintenance_release():
    old = measure(make_bench(firmware="1.0.0"), runs=12)
    new = measure(make_bench(firmware="1.1.0"), runs=12)
    assert new["noise"] == pytest.approx(old["noise"] - 1.0, abs=0.25)
    assert new["thd"] < old["thd"]
    p = make_bench(firmware="1.1.0").dut.effective()
    assert new["thd"] == pytest.approx(truth.expected_thd_percent(p, 1000, 0.05), rel=0.03)


def test_nan_and_inf_faults_corrupt_output_samples():
    for mode, check in (("NAN", np.isnan), ("INF", np.isposinf)):
        bench = make_bench()
        bench.dut.fault = mode
        acq = bench.acquire()
        assert not acq.finite
        assert check(acq.output).sum() == 3
        bench.dut.fault = "NONE"
        assert bench.acquire().finite


def test_acquisitions_are_deterministic_functions_of_seed_and_counter():
    a, b = make_bench(seed=99), make_bench(seed=99)
    first_a, first_b = a.acquire().output.copy(), b.acquire().output.copy()
    np.testing.assert_array_equal(first_a, first_b)
    second_a = a.acquire().output
    assert not np.array_equal(first_a, second_a)           # new noise realisation per acquisition
    a.reset_acquisition_state()
    assert a.seed == a.default_seed and a.counter == 0
    assert a.acquire().output.shape == first_a.shape
    c = make_bench(seed=100)
    assert not np.array_equal(first_a, c.acquire().output)
    d = make_bench(seed=99)
    d.counter = 1
    np.testing.assert_array_equal(d.acquire().output, second_a)


def test_stimulus_reference_is_independent_of_dut_settings():
    a = make_bench("NORMAL")
    b = make_bench("NORMAL")
    b.dut.params = replace(b.dut.params, hpf_hz=20.0)       # longer pre-roll
    np.testing.assert_array_equal(a.acquire().stimulus, b.acquire().stimulus)


def test_gain_of_a_silent_output_is_minus_infinity_instead_of_raising():
    silent = np.zeros(4096)
    reference = np.sin(2 * np.pi * np.arange(4096) / 64)
    acq = Acquisition(0, 48000.0, make_bench().siggen, reference, silent)
    assert acq.gain_db == -math.inf
