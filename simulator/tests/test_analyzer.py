"""Analyzer: acquisition model, measurement commands, preconditions, determinism."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from conftest import Rig
from mfsim import truth
from mfsim.scpi import ERROR_TEXT


def errors(ask) -> list[str]:
    out = []
    while (entry := ask("SYST:ERR?")) != '0,"No error"':
        out.append(entry)
    return out


def number(text: str | None) -> float:
    assert text is not None
    return float(text.replace("NAN", "nan").replace("-INF", "-inf").replace("INF", "inf"))


# ---------------------------------------------------------------- measurement commands vs truth
def test_all_measurements_match_truth_for_the_normal_profile(rig):
    rig.tone()
    p = rig.bench.dut.effective()
    assert number(rig.an("MEAS:GAIN?")) == pytest.approx(truth.expected_gain_db(p, 1000, 0.05), abs=0.005)
    assert number(rig.an("MEAS:THD?")) == pytest.approx(truth.expected_thd_percent(p, 1000, 0.05), rel=0.03)
    assert number(rig.an("MEAS:SNR?")) == pytest.approx(truth.expected_snr_db(p, 1000, 0.05), abs=0.4)
    assert number(rig.an("MEAS:NOIS?")) == pytest.approx(truth.expected_noise_floor_dbv(p), abs=0.4)
    assert number(rig.an("MEAS:RMS?")) == pytest.approx(truth.expected_rms_v(p, 1000, 0.05), rel=2e-3)
    assert number(rig.an("MEAS:FREQ?")) == pytest.approx(1000.0, abs=0.01)
    assert rig.an("MF:ANAL:WIN?") == "FLATTOP"
    assert errors(rig.an) == []


@pytest.mark.parametrize("form", ["MEAS:GAIN?", "MEASURE:GAIN?", "meas:gain?", "MEASure:GAIN?"])
def test_measurement_header_forms(rig, form):
    rig.tone()
    assert 19.9 < number(rig.an(form)) < 20.2


def test_noise_with_output_off_excludes_nothing_and_equals_the_dut_noise(rig):
    p = rig.bench.dut.effective()
    value = number(rig.an("MEAS:NOIS?"))
    assert value == pytest.approx(truth.expected_noise_floor_dbv(p), abs=0.4)
    assert number(rig.an("MEAS:RMS?")) == pytest.approx(10 ** (-80 / 20), rel=0.02)    # only DUT noise
    assert errors(rig.an) == []


def test_noise_with_tone_excludes_tone_and_harmonics(rig):
    rig.tone(2000.0, 0.4)
    assert number(rig.an("MEAS:NOIS?")) == pytest.approx(-80.8, abs=0.4)
    rig.sg("SOUR:FUNC SQU")                                          # not a tone: nothing is excluded
    assert number(rig.an("MEAS:NOIS?")) > -50.0


@pytest.mark.parametrize("function", ["SQU", "CHIR", "NOIS"])
def test_rms_noise_and_freq_work_for_any_stimulus(rig, function):
    rig.tone(3000.0, 0.1)
    rig.sg(f"SOUR:FUNC {function}")
    for query in ("MEAS:RMS?", "MEAS:NOIS?", "MEAS:FREQ?"):
        assert math.isfinite(number(rig.an(query)))
    assert number(rig.an("MEAS:RMS?")) > 0.1
    assert errors(rig.an) == []


def test_square_wave_stimulus_rms_and_frequency(rig):
    rig.tone(1000.0, 0.01)
    rig.sg("SOUR:FUNC SQU")
    assert number(rig.an("MEAS:FREQ?")) == pytest.approx(1000.0, abs=0.05)
    assert number(rig.an("MEAS:RMS?")) == pytest.approx(0.01 * 10 * 0.9, rel=0.15)


# ---------------------------------------------------------------- preconditions
@pytest.mark.parametrize("query", ["MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?"])
def test_tone_measurements_need_sine_and_output_on(rig, query):
    assert rig.an(query) == "NAN"                                    # output off
    assert errors(rig.an) == ['-221,"Settings conflict"']
    rig.tone()
    assert math.isfinite(number(rig.an(query)))
    for setup in ("SOUR:FUNC SQU", "SOUR:FUNC CHIR", "SOUR:FUNC NOIS"):
        rig.sg(setup)
        assert rig.an(query) == "NAN"
        assert errors(rig.an) == ['-221,"Settings conflict"']
    rig.sg("SOUR:FUNC SIN")
    rig.sg("SOUR:VOLT 0")
    assert rig.an(query) == "NAN" and errors(rig.an) == ['-221,"Settings conflict"']
    rig.sg("SOUR:VOLT 0.05")
    rig.sg("OUTP OFF")
    assert rig.an(query) == "NAN" and errors(rig.an) == ['-221,"Settings conflict"']


def test_dut_nan_and_inf_faults_answer_nan_and_queue_230(rig):
    rig.tone()
    for mode in ("NAN", "INF"):
        rig.du(f"MF:DUT:FAULT {mode}")
        for query in ("MEAS:RMS?", "MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?", "MEAS:NOIS?", "MEAS:FREQ?"):
            assert rig.an(query) == "NAN", query
            assert errors(rig.an) == ['-230,"Data corrupt or stale"'], query
    rig.du("MF:DUT:FAULT NONE")
    assert math.isfinite(number(rig.an("MEAS:GAIN?"))) and errors(rig.an) == []


def test_fault_with_failed_precondition_reports_the_conflict_first(rig):
    rig.du("MF:DUT:FAULT NAN")
    assert rig.an("MEAS:GAIN?") == "NAN"
    assert errors(rig.an) == ['-221,"Settings conflict"']


def test_waveform_and_spectrum_with_nonfinite_output(rig):
    rig.tone()
    rig.du("MF:DUT:FAULT NAN")
    rig.an("MF:ACQ:POIN 1024")
    wav = rig.an("MF:ACQ:WAV? 1024")
    assert wav.count("NAN") == 3 and len(wav.split(",")) == 1024
    assert errors(rig.an) == ['-230,"Data corrupt or stale"']
    assert rig.an("MF:ACQ:WAV? 8") is not None and errors(rig.an) == []           # the NaNs are beyond the 8th sample
    fft = rig.an("MF:ACQ:FFT? 4").split(",")
    assert fft[:2] == ["48000", "1024"] and fft[2:] == ["NAN"] * 4
    assert errors(rig.an) == ['-230,"Data corrupt or stale"']


# ---------------------------------------------------------------- acquisition model
def test_auto_acquire_then_values_are_stable_until_a_configuration_change(rig):
    rig.tone()
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,0,0"
    first = rig.an("MEAS:SNR?")
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,1,1"               # auto-acquired exactly once
    assert [rig.an("MEAS:SNR?") for _ in range(3)] == [first] * 3
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,1,1"
    rig.an("MF:ACQ:INIT")
    assert rig.an("MF:ACQ:CONF?").endswith(",1,2")
    second = rig.an("MEAS:SNR?")
    assert second != first                                           # new noise realisation
    assert abs(number(second) - number(first)) < 1.0


@pytest.mark.parametrize("setter", [
    ("sg", "SOUR:FREQ 2000"), ("sg", "SOUR:VOLT 0.1"), ("sg", "SOUR:FUNC SQU"), ("sg", "OUTP OFF"),
    ("sg", "MF:SOUR:SRAT 44100"), ("sg", "MF:SOUR:CHIR:START 100"), ("du", "MF:DUT:PROF NOISY"),
    ("du", "MF:DUT:FW 1.1.0"),
    ("du", "MF:DUT:GAIN 10"), ("du", "MF:DUT:HPF 200"), ("du", "MF:DUT:LPF 5000"), ("du", "MF:DUT:NOISE -60"),
    ("du", "MF:DUT:HD2 0.01"), ("du", "MF:DUT:HD3 0.02"), ("du", "MF:DUT:CLIP 1"), ("du", "MF:DUT:FAULT NAN"),
    ("an", "MF:ACQ:POIN 4096"), ("an", "MF:ACQ:SEED 3"), ("an", "*RST"), ("sg", "*RST"), ("du", "*RST"),
])
def test_any_configuration_change_invalidates_the_stored_acquisition(rig, setter):
    rig.tone()
    rig.an("MF:ACQ:INIT")
    assert rig.an("MF:ACQ:CONF?").split(",")[2] == "1"
    getattr(rig, setter[0])(setter[1])
    assert rig.an("MF:ACQ:CONF?").split(",")[2] == "0"


def test_queries_and_rejected_setters_do_not_invalidate(rig):
    rig.tone()
    rig.an("MF:ACQ:INIT")
    for ask, line in ((rig.sg, "SOUR:FREQ?"), (rig.du, "MF:DUT:CONF?"), (rig.sg, "SOUR:FREQ 1e9"),
                      (rig.an, "SYST:ERR?"),
                      (rig.an, "MF:FAULT:GARBAGE 0"), (rig.sg, "BOGUS"), (rig.du, "MF:DUT:PROF NOPE")):
        ask(line)
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,1,1"


def test_acquisition_commands_all_use_the_same_stored_buffer(rig):
    rig.tone()
    rig.an("MF:ACQ:INIT")
    wav = [float(v) for v in rig.an("MF:ACQ:WAV? 16384").split(",")]
    rms = number(rig.an("MEAS:RMS?"))
    assert math.sqrt(np.mean(np.square(wav))) == pytest.approx(rms, rel=1e-4)       # 6 significant digits
    assert rig.an("MF:ACQ:CONF?").endswith(",1,1")


def test_points_setting(rig):
    rig.tone()
    for points in (1024, 2048, 4096, 8192, 16384, 32768, 65536):
        rig.an(f"MF:ACQ:POIN {points}")
        assert rig.an("MF:ACQ:POIN?") == str(points)
        assert len(rig.an("MF:ACQ:WAV? 1024").split(",")) == 1024
        assert rig.an("MF:ACQ:FFT?").split(",")[1] == str(points)
        assert 19.9 < number(rig.an("MEAS:GAIN?")) < 20.2
    for bad in ("512", "1000", "3000", "131072", "0", "-1024", "16384.5", "abc"):
        rig.an(f"MF:ACQ:POIN {bad}")
    assert errors(rig.an) == ['-222,"Data out of range"'] * 7 + ['-104,"Data type error"']
    assert rig.an("MF:ACQ:POIN?") == "65536"
    rig.an("MF:ACQ:POIN 1.6384e4")
    assert rig.an("MF:ACQ:POIN?") == "16384"


def test_seed_resets_counter_and_makes_runs_reproducible(rig):
    rig.tone()
    rig.an("MF:ACQ:SEED 99")
    rig.an("MF:ACQ:INIT")
    rig.an("MF:ACQ:INIT")
    assert rig.an("MF:ACQ:CONF?").endswith(",1,2")
    reference = [rig.an("MEAS:NOIS?")]
    rig.an("MF:ACQ:SEED 99")
    assert rig.an("MF:ACQ:CONF?").endswith(",0,0") and rig.an("MF:ACQ:SEED?") == "99"
    rig.an("MF:ACQ:INIT")
    rig.an("MF:ACQ:INIT")
    assert [rig.an("MEAS:NOIS?")] == reference
    rig.an("MF:ACQ:SEED 100")
    rig.an("MF:ACQ:INIT")
    rig.an("MF:ACQ:INIT")
    assert rig.an("MEAS:NOIS?") != reference[0]
    for bad, code in (("-1", -222), ("1.5", -222), ("x", -104), ("9223372036854775808", -222)):
        rig.an(f"MF:ACQ:SEED {bad}")
        assert errors(rig.an) == [f'{code},"{ERROR_TEXT[code]}"'], bad


def run_sequence(seed: int) -> list[str | None]:
    """A fixed command script; returns every response it produces."""
    rig = Rig(seed)
    script = [(rig.an, "*RST"), (rig.sg, "SOUR:FREQ 1500"), (rig.sg, "SOUR:VOLT 0.08"), (rig.sg, "OUTP ON"),
              (rig.du, "MF:DUT:FW 1.2.0"), (rig.an, "MF:ACQ:INIT")]
    for ask, line in script:
        ask(line)
    out: list[str | None] = []
    for _ in range(3):
        rig.an("MF:ACQ:INIT")
        out += [rig.an(q) for q in ("MEAS:RMS?", "MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?", "MEAS:NOIS?", "MEAS:FREQ?")]
        out.append(rig.an("MF:ACQ:WAV? 64"))
    return out


def test_identical_command_sequences_give_identical_numbers():
    assert run_sequence(12345) == run_sequence(12345)
    assert run_sequence(12345) != run_sequence(54321)


def test_waveform_query(rig):
    rig.tone()
    default = rig.an("MF:ACQ:WAV?").split(",")
    assert len(default) == 512
    digits = [re.sub(r"[-+.]|e[-+]?\d+$", "", v).lstrip("0") for v in default]
    assert all(len(d) <= 6 for d in digits)                                  # six significant digits
    assert rig.an("MF:ACQ:WAV? 1") == default[0]
    assert len(rig.an("MF:ACQ:WAV? 16384").split(",")) == 16384
    for bad in ("0", "16385", "-3", "x", "1,2"):
        assert rig.an(f"MF:ACQ:WAV? {bad}") is None
    assert [e.split(",")[0] for e in errors(rig.an)] == ["-222", "-222", "-222", "-104", "-102"]
    samples = np.array(default, dtype=float)
    assert np.max(np.abs(samples)) < 0.55 and np.max(np.abs(samples)) > 0.4       # 0.5 V tone


def test_spectrum_query(rig):
    rig.tone(1000.0, 0.05)
    fields = rig.an("MF:ACQ:FFT?").split(",")
    assert fields[0] == "48000" and fields[1] == "16384"
    bins = np.array(fields[2:], dtype=float)
    assert bins.size == 8193
    peak = int(np.argmax(bins))
    assert peak * 48000 / 16384 == pytest.approx(1000.0, abs=3.0)
    assert bins[peak] == pytest.approx(20 * math.log10(0.5 * 1.001875), abs=0.02)   # peak amplitude 0.5 V -> -6 dBV
    assert bins[0] < -100.0                                                        # HPF removed DC
    capped = rig.an("MF:ACQ:FFT? 10").split(",")
    assert len(capped) == 12 and capped[2:] == fields[2:12]
    assert len(rig.an("MF:ACQ:FFT? 8193").split(",")) == 8195
    for bad in ("0", "8194", "x"):
        assert rig.an(f"MF:ACQ:FFT? {bad}") is None
    assert [e.split(",")[0] for e in errors(rig.an)] == ["-222", "-222", "-104"]


def test_spectrum_shows_the_dut_harmonics_at_their_expected_levels(rig):
    rig.tone(1000.0, 0.05)
    bins = np.array(rig.an("MF:ACQ:FFT?").split(",")[2:], dtype=float)
    p = rig.bench.dut.effective()
    harmonics = truth.expected_harmonic_v(p, 1000.0, 0.05)
    for h, amp in harmonics.items():
        k = round(h * 1000.0 * 16384 / 48000)
        assert bins[k - 2:k + 3].max() == pytest.approx(20 * math.log10(amp), abs=0.5)


def test_dut_profile_switch_changes_what_the_analyzer_sees(rig):
    rig.tone()
    assert number(rig.an("MEAS:GAIN?")) == pytest.approx(20.0, abs=0.05)
    rig.du("MF:DUT:PROF LOWGAIN")
    assert number(rig.an("MEAS:GAIN?")) == pytest.approx(14.0, abs=0.05)
    rig.du("MF:DUT:PROF HIGHTHD")
    assert number(rig.an("MEAS:THD?")) == pytest.approx(2.96, abs=0.1)
    rig.du("MF:DUT:PROF NOISY")
    assert number(rig.an("MEAS:SNR?")) == pytest.approx(41.8, abs=0.5)
    rig.du("MF:DUT:PROF CLIPPING")
    assert number(rig.an("MEAS:THD?")) > 10 and number(rig.an("MEAS:RMS?")) < 0.3


def test_chirp_stimulus_reaches_the_analyzer(rig):
    rig.sg("OUTP ON")
    rig.sg("SOUR:FUNC CHIR")
    rig.sg("SOUR:FREQ 6000")
    rig.sg("SOUR:VOLT 0.1")
    fields = rig.an("MF:ACQ:FFT?").split(",")
    peak_hz = np.argmax(np.array(fields[2:], dtype=float)) * 48000 / 16384
    assert 2000 < peak_hz < 5000                                   # centre of the sweep (flat-top weights time)
