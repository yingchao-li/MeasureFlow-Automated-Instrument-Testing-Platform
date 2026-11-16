"""SCPI protocol tests against the *real* simulator over raw TCP (docs/INTERFACE.md section 3).

Only the simulator is started (no backend needed). Every test talks to the instrument sockets
directly: command semantics, error queue, framing, fault injection observability, concurrency.
Where the contract is ambiguous the accepted set is stated in the test and kept as small as the
contract allows.
"""
from __future__ import annotations

import math
import re
import socket
import statistics
import threading
import time
from typing import Any

import pytest

from stack import ScpiClient, ScpiClosed, ScpiTimeout, Stack

INSTR = ["siggen", "analyzer", "dut"]
MODEL = {"siggen": ("VSG-1000", "SN-SIM-0001"), "analyzer": ("VAA-2000", "SN-SIM-0002"), "dut": ("VDUT-HA1", "SN-SIM-0003")}
NO_ERR = '0,"No error"'
ERR_RX = re.compile(r'^(-?\d+),"(.*)"$')


def err_code(line: str) -> int:
    m = ERR_RX.match(line)
    assert m, f"malformed SYST:ERR? response: {line!r}"
    return int(m.group(1))


def drain(c: ScpiClient, limit: int = 400) -> list[int]:
    """Read SYST:ERR? until 0; returns the codes (oldest first)."""
    out = []
    for _ in range(limit):
        code = err_code(c.query("SYST:ERR?"))
        if code == 0:
            return out
        out.append(code)
    raise AssertionError("error queue never emptied")


def c_(sim: Stack, inst: str) -> ScpiClient:
    return sim.scpi_client(inst, timeout=5.0)


def setup_tone(c_sig: ScpiClient, freq: float = 1000, amp: float = 0.05, out: bool = True) -> None:
    c_sig.write(f"SOUR:FUNC SIN")
    c_sig.write(f"SOUR:FREQ {freq}")
    c_sig.write(f"SOUR:VOLT {amp}")
    c_sig.write(f"OUTP {'ON' if out else 'OFF'}")
    c_sig.query("MF:FAULT?")  # barrier


# ============================================================================ identity / common
@pytest.mark.parametrize("inst", INSTR)
def test_idn_format_per_instrument(sim: Stack, inst: str) -> None:
    with c_(sim, inst) as c:
        idn = c.query("*IDN?")
    parts = idn.split(",")
    assert len(parts) == 4, idn
    assert parts[0] == "MeasureFlow"
    assert parts[1] == MODEL[inst][0]
    assert parts[2] == MODEL[inst][1]
    assert parts[3] == "1.0.0"  # DUT default firmware is also 1.0.0


@pytest.mark.parametrize("inst", INSTR)
def test_common_commands(sim: Stack, inst: str) -> None:
    with c_(sim, inst) as c:
        assert c.query("*OPC?") == "1"
        assert c.query("*TST?") == "0"
        assert c.query("SYST:VERS?") == "1999.0"
        assert re.fullmatch(r"\d+\.\d+\.\d+.*", c.query("MF:SIM:VERS?"))
        assert c.query("SYST:ERR?") == NO_ERR


def test_commands_are_case_insensitive_and_long_short_forms_equivalent(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("sour:freq 440")
        assert c.query("SOURce:FREQuency?") == "440"
        c.write("SOURCE:FREQUENCY 880")
        assert c.query("sour:freq?") == "880"
        c.write("outp on")
        assert c.query("OUTPut?") == "1"
        c.write("Outp Off")
        assert c.query("OUTP?") == "0"
        assert c.query("*idn?").startswith("MeasureFlow,VSG-1000")


@pytest.mark.parametrize("cmd,value", [
    ("SOUR:FREQ", 1234.5), ("SOUR:FREQ", 20000), ("SOUR:FREQ", 10), ("SOUR:FREQ", 99.999999),
    ("SOUR:FREQ", 12345.6789), ("SOUR:VOLT", 0.1), ("SOUR:VOLT", 0.001), ("SOUR:VOLT", 4.123456789123),
])
def test_numeric_responses_use_percent_9g(sim: Stack, cmd: str, value: float) -> None:
    with c_(sim, "siggen") as c:
        c.write(f"{cmd} {value!r}")
        assert c.query(f"{cmd}?") == f"{value:.9g}"


def test_setters_produce_no_response_and_queries_exactly_one(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("SOUR:FREQ 2000")
        c.write("SOUR:VOLT 0.1")
        c.write("OUTP ON")
        assert c.expect_no_data(0.2), "setters must not answer"
        c.write("*OPC?")
        c.write("*OPC?")
        assert c.read_line() == "1"
        assert c.read_line() == "1"
        assert c.expect_no_data(0.2), "each query must produce exactly one line"


@pytest.mark.parametrize("inst", INSTR)
def test_rst_restores_defaults_and_clears_state(sim: Stack, inst: str) -> None:
    with c_(sim, inst) as c:
        if inst == "siggen":
            c.write("SOUR:FUNC SQU"); c.write("SOUR:FREQ 5000"); c.write("SOUR:VOLT 1"); c.write("OUTP ON")
            c.write("MF:SOUR:SRAT 96000")
            c.write("*RST")
            assert c.query("MF:SOUR:CONF?") == "SIN,1000,0.05,48000,0"
        elif inst == "analyzer":
            c.write("MF:ACQ:POIN 4096"); c.write("MF:ACQ:SEED 99"); c.write("MF:ACQ:INIT")
            c.write("*RST")
            assert c.query("MF:ACQ:POIN?") == "16384"
            assert c.query("MF:ACQ:SEED?") == "12345"
            conf = c.query("MF:ACQ:CONF?").split(",")
            assert conf[0] == "16384" and conf[2] == "0", f"acquisition must be invalidated: {conf}"
        else:
            c.write("MF:DUT:PROF HIGHTHD"); c.write("MF:DUT:FW 1.2.0")
            c.write("*RST")
            assert c.query("MF:DUT:PROF?") == "NORMAL"
            assert c.query("MF:DUT:FW?") == "1.0.0"
        # RST clears fault injections too
        c.write("MF:FAULT:GARBAGE 3")
        c.write("*RST")
        assert c.query("MF:FAULT?") == "TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0"


# ============================================================================ error queue
def test_unknown_header_queues_minus_113_and_gives_no_response(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("FOO:BAR 1")
        c.write("FOO:BAR?")  # a *query* with an error must not answer either
        c.write("*OPC?")
        assert c.read_line() == "1", "an erroneous query must not produce a response line"
        assert drain(c) == [-113, -113]


def test_error_queue_is_fifo_and_ends_with_no_error(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("NOPE:CMD")             # -113
        c.write("SOUR:FREQ abc")        # -104
        c.write("SOUR:FREQ 5")          # -222
        assert err_code(c.query("SYST:ERR?")) == -113
        assert err_code(c.query("SYST:ERR?")) == -104
        assert err_code(c.query("SYST:ERR?")) == -222
        assert c.query("SYST:ERR?") == NO_ERR
        assert c.query("SYST:ERR?") == NO_ERR


def test_error_messages_are_quoted_text(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("SOUR:FREQ 5")
        line = c.query("SYST:ERR?")
        m = ERR_RX.match(line)
        assert m and m.group(1) == "-222" and len(m.group(2)) > 3, line


def test_cls_clears_error_queue(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("BAD:HEADER"); c.write("BAD:HEADER2")
        c.write("*CLS")
        assert c.query("SYST:ERR?") == NO_ERR


def test_error_queue_is_per_instrument(sim: Stack) -> None:
    with c_(sim, "siggen") as a, c_(sim, "dut") as b:
        a.write("BAD:CMD")
        assert b.query("SYST:ERR?") == NO_ERR
        assert err_code(a.query("SYST:ERR?")) == -113


def test_error_queue_is_shared_between_connections_of_one_instrument(sim: Stack) -> None:
    with c_(sim, "siggen") as a:
        a.write("BAD:CMD"); a.query("MF:FAULT?")
    with c_(sim, "siggen") as b:
        assert err_code(b.query("SYST:ERR?")) == -113


def test_error_queue_overflow_is_bounded_and_flagged(sim: Stack) -> None:
    n = 300
    with c_(sim, "siggen") as c:
        c.send_raw(b"BAD:CMD\n" * n)
        c.query("MF:FAULT?")
        codes = drain(c, limit=n + 10)
    assert 1 <= len(codes) <= n
    if len(codes) < n:
        assert -350 in codes, "queue dropped entries without a -350 overflow marker"


@pytest.mark.parametrize("cmd,allowed", [
    ("SOUR:FREQ abc", {-104}),
    ("SOUR:FREQ 9.99", {-222}),
    ("SOUR:FREQ 20000.1", {-222}),
    ("SOUR:VOLT 5.01", {-222}),
    ("SOUR:VOLT -0.1", {-222}),
    ("MF:SOUR:SRAT 7999", {-222}),
    ("MF:SOUR:SRAT 192001", {-222}),
    ("SOUR:FUNC TRIANGLE", {-104, -222, -224}),
    ("OUTP MAYBE", {-104, -222, -224}),
    ("SOUR:FREQ NAN", {-104, -222}),
    ("SOUR:FREQ 1e999", {-104, -222}),
])
def test_siggen_rejects_bad_arguments_without_changing_state(sim: Stack, cmd: str, allowed: set[int]) -> None:
    with c_(sim, "siggen") as c:
        before = c.query("MF:SOUR:CONF?")
        c.write(cmd)
        codes = drain(c)
        assert codes and set(codes) <= allowed, f"{cmd!r}: got {codes}, allowed {allowed}"
        assert c.query("MF:SOUR:CONF?") == before, "rejected command must not change state"


# ============================================================================ signal generator
@pytest.mark.parametrize("cmd,query,values", [
    ("SOUR:FREQ", "SOUR:FREQ?", [10, 20000, 1000, 12345.5]),
    ("SOUR:VOLT", "SOUR:VOLT?", [0, 5, 0.05, 1e-3]),
    ("MF:SOUR:SRAT", "MF:SOUR:SRAT?", [8000, 192000, 48000]),
])
def test_siggen_range_boundaries_are_accepted(sim: Stack, cmd: str, query: str, values: list[float]) -> None:
    with c_(sim, "siggen") as c:
        for v in values:
            c.write(f"{cmd} {v}")
            assert float(c.query(query)) == pytest.approx(v, rel=1e-9), f"{cmd} {v}"
        assert drain(c) == []


@pytest.mark.parametrize("func", ["SIN", "SQU", "CHIR", "NOIS"])
def test_siggen_waveforms(sim: Stack, func: str) -> None:
    with c_(sim, "siggen") as c:
        c.write(f"SOUR:FUNC {func}")
        assert c.query("SOUR:FUNC?") == func
        assert c.query("MF:SOUR:CONF?").startswith(func + ",")
        assert drain(c) == []


@pytest.mark.parametrize("on,off", [("ON", "OFF"), ("1", "0"), ("on", "off")])
def test_siggen_output_forms(sim: Stack, on: str, off: str) -> None:
    with c_(sim, "siggen") as c:
        c.write(f"OUTP {on}"); assert c.query("OUTP?") == "1"
        c.write(f"OUTP {off}"); assert c.query("OUTP?") == "0"


def test_siggen_conf_query_matches_individual_queries(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("SOUR:FUNC SQU"); c.write("SOUR:FREQ 2500"); c.write("SOUR:VOLT 0.2"); c.write("MF:SOUR:SRAT 96000"); c.write("OUTP ON")
        f, fr, a, sr, o = c.query("MF:SOUR:CONF?").split(",")
        assert (f, float(fr), float(a), float(sr), o) == ("SQU", 2500.0, 0.2, 96000.0, "1")


def test_chirp_start_roundtrip(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        assert float(c.query("MF:SOUR:CHIR:START?")) == 20.0  # documented default
        c.write("MF:SOUR:CHIR:START 100")
        assert float(c.query("MF:SOUR:CHIR:START?")) == 100.0


# ============================================================================ analyzer
@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384, 32768, 65536])
def test_acquisition_points_valid_powers_of_two(sim: Stack, n: int) -> None:
    with c_(sim, "analyzer") as c:
        c.write(f"MF:ACQ:POIN {n}")
        assert c.query("MF:ACQ:POIN?") == str(n)
        assert drain(c) == []


@pytest.mark.parametrize("n", [0, 512, 1000, 1023, 1025, 3000, 65535, 131072, -1024])
def test_acquisition_points_invalid_rejected(sim: Stack, n: int) -> None:
    with c_(sim, "analyzer") as c:
        c.write(f"MF:ACQ:POIN {n}")
        codes = drain(c)
        assert codes and set(codes) <= {-222, -221, -224, -104}, codes
        assert c.query("MF:ACQ:POIN?") == "16384"


def test_waveform_and_fft_shapes(sim: Stack) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        setup_tone(s)
        a.write("MF:ACQ:POIN 4096")
        a.write("MF:ACQ:INIT")
        assert a.query("*OPC?") == "1"
        assert a.query("MF:ACQ:CONF?") .split(",")[0] == "4096"
        wav = a.query("MF:ACQ:WAV?").split(",")
        assert len(wav) == 512, "default WAV? length is 512"
        assert len(a.query("MF:ACQ:WAV? 100").split(",")) == 100
        assert len(a.query("MF:ACQ:WAV? 4096").split(",")) == 4096
        for tok in wav[:50]:
            assert tok == f"{float(tok):.6g}", f"WAV sample {tok!r} not formatted with 6 significant digits"
        fft = a.query("MF:ACQ:FFT?").split(",")
        srate, nfft = float(fft[0]), int(float(fft[1]))
        assert srate == 48000
        assert len(fft) - 2 == nfft // 2 + 1
        capped = a.query("MF:ACQ:FFT? 50").split(",")
        assert len(capped) - 2 == 50 and capped[0] == fft[0] and capped[1] == fft[1]
        assert capped[2:] == fft[2:52], "capped spectrum must be a prefix of the full spectrum"


def test_wav_request_longer_than_buffer_is_clamped_or_rejected(sim: Stack) -> None:
    with c_(sim, "analyzer") as a:
        a.write("MF:ACQ:POIN 1024"); a.write("MF:ACQ:INIT")
        a.write("MF:ACQ:WAV? 100000")
        a.write("*OPC?")
        first = a.read_line()
        if first == "1":                       # rejected: no response + error
            codes = drain(a)
            assert codes and set(codes) <= {-222}, codes
        else:
            assert len(first.split(",")) == 1024


def test_fft_peak_is_at_stimulus_frequency_and_amplitude(sim: Stack) -> None:
    f0, amp = 1000.0, 0.05
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        setup_tone(s, f0, amp)
        a.write("MF:ACQ:INIT")
        fft = a.query("MF:ACQ:FFT?").split(",")
        srate, nfft = float(fft[0]), int(float(fft[1]))
        mags = [float(x) for x in fft[2:]]
        k = max(range(len(mags)), key=lambda i: mags[i])
        df = srate / nfft
        assert abs(k * df - f0) <= 1.5 * df, f"peak at {k * df} Hz"
        # NORMAL DUT: 20 dB gain => 0.5 V peak => -6.02 dBV (+0.016 dB from hd3), flat-top compensated
        assert mags[k] == pytest.approx(20 * math.log10(amp * 10), abs=0.3)


def test_measurement_values_are_stable_without_new_acquisition_and_change_with_it(sim: Stack) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        setup_tone(s)
        a.write("MF:ACQ:INIT")
        n1 = a.query("MEAS:NOIS?")
        assert a.query("MEAS:NOIS?") == n1 and a.query("MEAS:NOIS?") == n1
        r1 = a.query("MEAS:RMS?")
        assert a.query("MEAS:RMS?") == r1
        counter1 = int(a.query("MF:ACQ:CONF?").split(",")[3])
        a.write("MF:ACQ:INIT")
        assert int(a.query("MF:ACQ:CONF?").split(",")[3]) == counter1 + 1
        n2 = a.query("MEAS:NOIS?")
        assert n2 != n1, "a new acquisition must draw a new noise realisation"
        assert abs(float(n2) - float(n1)) < 1.5, "noise level estimate should be statistically stable (dB)"


def test_auto_acquire_and_invalidation_on_configuration_change(sim: Stack) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a, c_(sim, "dut") as d:
        setup_tone(s)
        stored = lambda: a.query("MF:ACQ:CONF?").split(",")[2]  # noqa: E731
        assert stored() == "0"
        float(a.query("MEAS:RMS?"))
        assert stored() == "1", "first MEAS after *RST must auto-acquire"
        s.write("SOUR:FREQ 2000"); s.query("MF:FAULT?")
        assert stored() == "0", "generator change must invalidate the stored acquisition"
        float(a.query("MEAS:RMS?")); assert stored() == "1"
        d.write("MF:DUT:GAIN 15"); d.query("MF:FAULT?")
        assert stored() == "0", "DUT change must invalidate the stored acquisition"
        float(a.query("MEAS:RMS?")); assert stored() == "1"
        a.write("MF:ACQ:POIN 2048"); a.query("MF:FAULT?")
        assert stored() == "0", "analyzer change must invalidate the stored acquisition"


def test_seed_makes_acquisitions_reproducible(sim: Stack) -> None:
    def run(seed: int) -> list[str]:
        with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
            setup_tone(s)
            a.write(f"MF:ACQ:SEED {seed}")
            out = []
            for _ in range(3):
                a.write("MF:ACQ:INIT")
                out.append(a.query("MEAS:NOIS?")); out.append(a.query("MEAS:THD?"))
            return out

    r1, r2, r3 = run(777), run(777), run(778)
    assert r1 == r2, "same seed + counter reset must reproduce every value bit-for-bit"
    assert r1 != r3, "different seed must change the noise realisation"
    assert len(set(r1[0::2])) == 3, "successive acquisitions must differ (counter advances)"


def test_seed_roundtrip_and_resets_counter(sim: Stack) -> None:
    with c_(sim, "analyzer") as a:
        a.write("MF:ACQ:INIT"); a.write("MF:ACQ:INIT")
        assert int(a.query("MF:ACQ:CONF?").split(",")[3]) == 2
        a.write("MF:ACQ:SEED 4242")
        assert a.query("MF:ACQ:SEED?") == "4242"
        assert int(a.query("MF:ACQ:CONF?").split(",")[3]) == 0


def test_simulator_restart_with_same_seed_reproduces_values(sim: Stack) -> None:
    def measure() -> tuple[str, ...]:
        with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
            setup_tone(s)
            return tuple(a.query(q) for q in ("MEAS:RMS?", "MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?", "MEAS:NOIS?"))

    sim.restart_simulator(seed=2024)
    first = measure()
    sim.restart_simulator(seed=2024)
    assert measure() == first
    sim.restart_simulator(seed=2025)
    assert measure() != first
    sim.restart_simulator(seed=12345)


@pytest.mark.parametrize("q", ["MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?"])
def test_sine_only_measurements_need_output_on(sim: Stack, q: str) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        s.write("OUTP OFF"); s.query("MF:FAULT?")
        assert a.query(q) == "NAN"
        assert -221 in drain(a)


@pytest.mark.parametrize("q", ["MEAS:GAIN?", "MEAS:THD?", "MEAS:SNR?"])
def test_sine_only_measurements_need_sine_function(sim: Stack, q: str) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        s.write("SOUR:FUNC SQU"); s.write("OUTP ON"); s.query("MF:FAULT?")
        assert a.query(q) == "NAN"
        assert -221 in drain(a)


def test_rms_noise_and_freq_work_without_tone(sim: Stack) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a:
        s.write("OUTP OFF"); s.query("MF:FAULT?")
        rms = float(a.query("MEAS:RMS?"))
        assert 5e-5 < rms < 2e-4, f"silence RMS should be the DUT noise (~1e-4 V), got {rms}"
        noise = float(a.query("MEAS:NOIS?"))
        assert -86 < noise < -78, noise      # -80 dBV full band, in-band ~ -80.8
        assert math.isfinite(float(a.query("MEAS:FREQ?")))
        assert drain(a) == []


@pytest.mark.parametrize("profile,checks", [
    ("NORMAL", dict(gain=(19.8, 20.2), thd=(0.05, 0.3), snr=(65, 76), noise=(-84, -78))),
    ("LOWGAIN", dict(gain=(13.8, 14.2), thd=(0.02, 0.3), snr=(58, 70), noise=(-84, -78))),
    ("HIGHTHD", dict(gain=(19.0, 21.5), thd=(2.0, 5.0), snr=(65, 76), noise=(-84, -78))),
    ("NOISY", dict(gain=(19.8, 20.2), thd=(0.02, 0.5), snr=(38, 44), noise=(-54, -48))),
])
def test_dut_profiles_produce_documented_symptoms(sim: Stack, profile: str, checks: dict[str, tuple[float, float]]) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a, c_(sim, "dut") as d:
        setup_tone(s)
        d.write(f"MF:DUT:PROF {profile}"); d.query("MF:FAULT?")
        got = {"gain": float(a.query("MEAS:GAIN?")), "thd": float(a.query("MEAS:THD?")),
               "snr": float(a.query("MEAS:SNR?")), "noise": float(a.query("MEAS:NOIS?"))}
        for k, (lo, hi) in checks.items():
            assert lo <= got[k] <= hi, f"{profile}: {k}={got[k]} not in [{lo},{hi}]"
        assert drain(a) == []


def test_clipping_profile_has_large_thd_and_low_rms(sim: Stack) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a, c_(sim, "dut") as d:
        setup_tone(s)
        normal_rms = float(a.query("MEAS:RMS?"))
        d.write("MF:DUT:PROF CLIPPING"); d.query("MF:FAULT?")
        rms, thd = float(a.query("MEAS:RMS?")), float(a.query("MEAS:THD?"))
        assert rms < 0.3 / 1.0 and rms < normal_rms * 0.8       # clipped at 0.3 Vpk
        assert thd > 5.0, f"hard clipping must give large THD, got {thd}"


def test_firmware_effects_on_normal_profile(sim: Stack) -> None:
    def mean_meas(c_a: ScpiClient, q: str, n: int = 6) -> float:
        vals = []
        for _ in range(n):
            c_a.write("MF:ACQ:INIT")
            vals.append(float(c_a.query(q)))
        return statistics.fmean(vals)

    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a, c_(sim, "dut") as d:
        setup_tone(s)
        res: dict[str, dict[str, float]] = {}
        for fw in ("1.0.0", "1.1.0", "1.2.0"):
            d.write(f"MF:DUT:FW {fw}"); d.query("MF:FAULT?")
            assert d.query("MF:DUT:FW?") == fw
            res[fw] = {"thd": mean_meas(a, "MEAS:THD?"), "noise": mean_meas(a, "MEAS:NOIS?"),
                       "gain": mean_meas(a, "MEAS:GAIN?")}
    assert res["1.1.0"]["thd"] < res["1.0.0"]["thd"], "1.1.0 has hd2 x 0.8 -> lower THD"
    assert res["1.1.0"]["noise"] <= res["1.0.0"]["noise"] + 0.05, "1.1.0 has slightly lower noise"
    assert 1.5 <= res["1.2.0"]["thd"] <= 3.0, f"1.2.0 regression build THD {res['1.2.0']['thd']}"
    assert 3.5 <= res["1.2.0"]["noise"] - res["1.0.0"]["noise"] <= 6.5, "1.2.0 noise should be +4..6 dB"
    for fw in res:
        assert 19.0 <= res[fw]["gain"] <= 21.0, f"gain must still pass for {fw}"


# ============================================================================ DUT
PROFILES = {
    "NORMAL": (20, 100, 8000, -80, 0.004, 0.01, 1.5),
    "LOWGAIN": (14, 100, 8000, -80, 0.004, 0.01, 1.5),
    "HIGHTHD": (20, 100, 8000, -80, 0.10, 0.30, 1.5),
    "NOISY": (20, 100, 8000, -50, 0.004, 0.01, 1.5),
    "CLIPPING": (20, 100, 8000, -80, 0.004, 0.01, 0.3),
}


@pytest.mark.parametrize("profile", list(PROFILES))
def test_dut_profile_table_via_conf_query(sim: Stack, profile: str) -> None:
    with c_(sim, "dut") as d:
        d.write(f"MF:DUT:PROF {profile.lower()}")
        assert d.query("MF:DUT:PROF?") == profile
        f = d.query("MF:DUT:CONF?").split(",")
        assert f[0] == profile and f[8] == "1.0.0"
        assert [float(x) for x in f[1:8]] == pytest.approx(list(PROFILES[profile]), rel=1e-9)


def test_dut_individual_change_makes_profile_custom_and_firmware_survives_profile_load(sim: Stack) -> None:
    with c_(sim, "dut") as d:
        d.write("MF:DUT:FW 1.2.0")
        d.write("MF:DUT:PROF LOWGAIN")
        assert d.query("MF:DUT:FW?") == "1.2.0", "profile load keeps firmware"
        d.write("MF:DUT:GAIN 12")
        assert d.query("MF:DUT:PROF?") == "CUSTOM"
        assert float(d.query("MF:DUT:GAIN?")) == 12.0
        conf = d.query("MF:DUT:CONF?").split(",")
        assert conf[0] == "CUSTOM" and float(conf[1]) == 12.0 and conf[8] == "1.2.0"


def test_dut_firmware_changes_idn_and_keeps_configured_values(sim: Stack) -> None:
    with c_(sim, "dut") as d, c_(sim, "siggen") as s:
        before = d.query("MF:DUT:CONF?").split(",")[1:8]
        d.write("MF:DUT:FW 1.2.0")
        assert d.query("*IDN?").endswith(",1.2.0")
        assert d.query("MF:DUT:CONF?").split(",")[1:8] == before, "configured values stay those of the profile"
        assert s.query("*IDN?").endswith(",1.0.0"), "siggen firmware is independent"


@pytest.mark.parametrize("cmd,query,ok,bad", [
    ("MF:DUT:GAIN", "MF:DUT:GAIN?", [-20, 60, 0], [-20.01, 60.01]),
    ("MF:DUT:HPF", "MF:DUT:HPF?", [20, 1000], [19.9, 1000.1]),
    ("MF:DUT:LPF", "MF:DUT:LPF?", [1000, 20000], [999, 20001]),
    ("MF:DUT:NOISE", "MF:DUT:NOISE?", [-140, 0], [-140.1, 0.1]),
    ("MF:DUT:HD2", "MF:DUT:HD2?", [0, 1, 0.5], [-0.001, 1.001]),
    ("MF:DUT:HD3", "MF:DUT:HD3?", [0, 1], [-0.001, 1.001]),
    ("MF:DUT:CLIP", "MF:DUT:CLIP?", [0.01, 10], [0.0099, 10.1]),
])
def test_dut_parameter_ranges(sim: Stack, cmd: str, query: str, ok: list[float], bad: list[float]) -> None:
    with c_(sim, "dut") as d:
        for v in ok:
            d.write(f"{cmd} {v}")
            assert float(d.query(query)) == pytest.approx(v), f"{cmd} {v}"
        assert drain(d) == []
        for v in bad:
            keep = d.query(query)
            d.write(f"{cmd} {v}")
            codes = drain(d)
            assert codes and set(codes) <= {-222}, f"{cmd} {v}: {codes}"
            assert d.query(query) == keep


@pytest.mark.parametrize("bad", ["2.0.0", "1.0", "abc", "1.3.0", ""])
def test_dut_rejects_unknown_firmware(sim: Stack, bad: str) -> None:
    with c_(sim, "dut") as d:
        d.write(f"MF:DUT:FW {bad}")
        codes = drain(d)
        allowed = {-224, -222, -104} | ({-102} if bad == "" else set())   # missing parameter = syntax error
        assert codes and set(codes) <= allowed, codes
        assert d.query("MF:DUT:FW?") == "1.0.0"


def test_dut_rejects_unknown_profile(sim: Stack) -> None:
    with c_(sim, "dut") as d:
        d.write("MF:DUT:PROF SUPERB")
        codes = drain(d)
        assert codes and set(codes) <= {-224, -222, -104}
        assert d.query("MF:DUT:PROF?") == "NORMAL"


@pytest.mark.parametrize("fault", ["NAN", "INF"])
def test_dut_fault_makes_analyzer_answer_nan_and_queue_minus_230(sim: Stack, fault: str) -> None:
    with c_(sim, "siggen") as s, c_(sim, "analyzer") as a, c_(sim, "dut") as d:
        setup_tone(s)
        d.write(f"MF:DUT:FAULT {fault}")
        assert d.query("MF:DUT:FAULT?") == fault
        assert a.query("MEAS:RMS?") == "NAN"
        assert -230 in drain(a)
        d.write("MF:DUT:FAULT NONE")
        assert d.query("MF:DUT:FAULT?") == "NONE"
        assert math.isfinite(float(a.query("MEAS:RMS?")))


# ============================================================================ fault injection (socket level)
FAULT_ZERO = "TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0"


def test_fault_query_format_and_counters_and_clear(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        assert c.query("MF:FAULT?") == FAULT_ZERO
        c.write("MF:FAULT:TIMEOUT 3,10"); c.write("MF:FAULT:GARBAGE 2"); c.write("MF:FAULT:NAN 4")
        c.write("MF:FAULT:INF 5"); c.write("MF:FAULT:FRAGMENT 6"); c.write("MF:FAULT:OVERSIZE 7"); c.write("MF:FAULT:DISCONNECT 8")
        assert c.query("MF:FAULT?") == "TIMEOUT=3,DISCONNECT=8,GARBAGE=2,FRAGMENT=6,NAN=4,INF=5,OVERSIZE=7"
        c.write("MF:FAULT:CLEAR")
        assert c.query("MF:FAULT?") == FAULT_ZERO


def test_fault_commands_are_never_faulted(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:TIMEOUT 5,3000")
        t0 = time.monotonic()
        assert c.query("MF:FAULT?").startswith("TIMEOUT=5,")
        c.write("MF:FAULT:CLEAR")
        assert c.query("MF:FAULT?") == FAULT_ZERO
        assert time.monotonic() - t0 < 1.0, "MF:FAULT commands must not be delayed by TIMEOUT injection"


def test_fault_counters_are_per_instrument(sim: Stack) -> None:
    with c_(sim, "analyzer") as a, c_(sim, "siggen") as s:
        a.write("MF:FAULT:GARBAGE 2")
        assert s.query("*IDN?").startswith("MeasureFlow,VSG-1000"), "siggen must be unaffected"
        assert s.query("MF:FAULT?") == FAULT_ZERO
        assert a.query("*IDN?") == "#!GARBAGE~~"


def test_timeout_fault_delays_next_n_commands_only(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:TIMEOUT 2,300")
        for _ in range(2):
            t0 = time.monotonic()
            assert c.query("*IDN?", timeout=5).startswith("MeasureFlow")
            assert time.monotonic() - t0 >= 0.27, "faulted command must be answered after delay_ms"
        t0 = time.monotonic()
        assert c.query("*IDN?").startswith("MeasureFlow")
        assert time.monotonic() - t0 < 0.25, "the (n+1)-th command must be prompt"
        assert c.query("MF:FAULT?") == FAULT_ZERO


@pytest.mark.slow
def test_timeout_fault_default_delay_is_five_seconds(sim: Stack) -> None:
    with c_(sim, "dut") as c:
        c.write("MF:FAULT:TIMEOUT 1")
        t0 = time.monotonic()
        c.write("*IDN?")
        with pytest.raises(ScpiTimeout):
            c.read_line(timeout=4.0)           # nothing for the first 4 s
        line = c.read_line(timeout=3.0)
        assert 4.8 <= time.monotonic() - t0 <= 6.5, "default delay should be ~5000 ms"
        assert line.startswith("MeasureFlow")


def test_disconnect_fault_closes_connection_without_response(sim: Stack) -> None:
    with c_(sim, "analyzer") as a:
        a.write("MF:FAULT:DISCONNECT 2")
        a.write("*IDN?")
        assert a.is_closed_by_peer(2.0), "connection must be closed"
        assert a.buf == b"", "no response bytes may precede the close"
    with c_(sim, "analyzer") as b:                     # counter is server wide: second victim
        b.write("*IDN?")
        assert b.is_closed_by_peer(2.0) and b.buf == b""
    with c_(sim, "analyzer") as c:                     # exhausted -> normal
        assert c.query("*IDN?").startswith("MeasureFlow")
        assert c.query("MF:FAULT?") == FAULT_ZERO


def test_garbage_fault_replaces_next_n_query_responses(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:GARBAGE 2")
        assert c.query("*IDN?") == "#!GARBAGE~~"
        assert c.query("*OPC?") == "#!GARBAGE~~"
        assert c.query("*OPC?") == "1"
        assert c.expect_no_data(0.1), "garbage must be a single line"


def test_nan_and_inf_faults_replace_numeric_responses(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.write("SOUR:FREQ 1500")
        c.write("MF:FAULT:NAN 1")
        assert c.query("*IDN?").startswith("MeasureFlow"), "non-numeric responses are never replaced"
        assert c.query("SOUR:FREQ?") == "NAN"
        assert c.query("SOUR:FREQ?") == "1500"
        c.write("MF:FAULT:INF 1")
        assert c.query("SOUR:FREQ?") == "INF"
        assert c.query("SOUR:FREQ?") == "1500"


def test_fragment_fault_sends_valid_response_in_chunks(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:FRAGMENT 1,2,30")
        t0 = time.monotonic()
        c.write("*IDN?")
        chunks = c.read_chunks(timeout=8)
        elapsed = time.monotonic() - t0
        data = b"".join(b for _, b in chunks)
        assert data.endswith(b"\n") and data.decode().strip().startswith("MeasureFlow,VAA-2000,SN-SIM-0002,")
        assert len(chunks) >= 6, f"expected many small TCP reads, got {len(chunks)}"
        assert max(len(b) for _, b in chunks) <= 8, "chunks must be small"
        assert elapsed >= 0.2, "chunks are spaced by delay_ms"
        assert c.query("*OPC?") == "1", "next response is back to normal"


def test_fragment_fault_default_parameters(sim: Stack) -> None:
    with c_(sim, "dut") as c:
        c.write("MF:FAULT:FRAGMENT 1")
        c.write("*IDN?")
        chunks = c.read_chunks(timeout=8)
        assert len(chunks) >= 8 and max(len(b) for _, b in chunks) <= 3, "default chunk size is 3 bytes"


def test_oversize_fault_pads_response_beyond_two_mebibytes(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:OVERSIZE 1")
        line = c.query("*IDN?", timeout=15)
        assert len(line) > 2 * 1024 * 1024, f"only {len(line)} bytes"
        assert c.query("*OPC?") == "1"


def test_clear_cancels_pending_injections(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.write("MF:FAULT:GARBAGE 5"); c.write("MF:FAULT:DISCONNECT 5"); c.write("MF:FAULT:CLEAR")
        assert c.query("*IDN?").startswith("MeasureFlow")


# ============================================================================ framing
def test_partial_writes_are_reassembled(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.send_raw(b"*ID"); time.sleep(0.15)
        c.send_raw(b"N"); time.sleep(0.15)
        assert c.expect_no_data(0.1)
        c.send_raw(b"?\n")
        assert c.read_line().startswith("MeasureFlow,VSG-1000")


def test_byte_by_byte_command(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        for b in b"SOUR:FREQ 777\nSOUR:FREQ?\n":
            c.send_raw(bytes([b]))
        assert c.read_line() == "777"


def test_crlf_terminator_accepted_and_response_has_lf_only(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.send_raw(b"*IDN?\r\n")
        c.sock.settimeout(3)
        data = b""
        while not data.endswith(b"\n"):
            data += c.sock.recv(4096)
        assert data.endswith(b"\n") and not data.endswith(b"\r\n"), data
        assert b"\r" not in data
        c.send_raw(b"SOUR:FREQ 321\r\nSOUR:FREQ?\r\n")
        assert c.read_line() == "321"


def test_whitespace_and_empty_lines_are_tolerated(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        c.send_raw(b"\n\n   \n  *OPC?  \n\t*OPC?\t\n")
        assert c.read_line() == "1"
        assert c.read_line() == "1"
        assert c.expect_no_data(0.15)


def test_pipelined_commands_answer_in_order(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        payload = b"".join(b"SOUR:FREQ %d\nSOUR:FREQ?\n" % (100 + i) for i in range(200))
        c.send_raw(payload)
        got = [c.read_line() for _ in range(200)]
        assert got == [str(100 + i) for i in range(200)]
        assert c.expect_no_data(0.1)


def test_pipelined_commands_across_packet_boundary(sim: Stack) -> None:
    with c_(sim, "analyzer") as c:
        c.send_raw(b"*OPC?\n*ID"); assert c.read_line() == "1"
        c.send_raw(b"N?\n*OPC?\n")
        assert c.read_line().startswith("MeasureFlow,VAA-2000")
        assert c.read_line() == "1"


def test_overlong_line_does_not_kill_or_hang_the_server(sim: Stack) -> None:
    junk = b"A" * (3 * 1024 * 1024)
    with c_(sim, "analyzer") as c:
        try:
            c.send_raw(junk)
            c.send_raw(b"\n*OPC?\n")
        except OSError:
            pass                                         # server may drop us: acceptable
    # whatever happened to that connection, the instrument must still serve new clients quickly
    t0 = time.monotonic()
    with c_(sim, "analyzer") as c2:
        assert c2.query("*IDN?", timeout=3).startswith("MeasureFlow")
    assert time.monotonic() - t0 < 2.0
    with c_(sim, "analyzer") as c3:
        codes = drain(c3)
        assert all(code in (-102, -113, -200, -350, -104) for code in codes), codes


def test_overlong_line_unterminated_then_client_closes(sim: Stack) -> None:
    s = socket.create_connection(("127.0.0.1", sim.sim_ports["siggen"]), timeout=5)
    try:
        s.sendall(b"B" * (2 * 1024 * 1024))
    except OSError:
        pass
    s.close()
    with c_(sim, "siggen") as c:
        assert c.query("*OPC?", timeout=3) == "1"


def test_binary_garbage_input_is_survivable(sim: Stack) -> None:
    with c_(sim, "dut") as c:
        c.send_raw(b"\xff\xfe\x00\x01\x02\n\x80\x81 \x7f\n*OPC?\n")
        try:
            assert c.read_line() == "1"
        except (ScpiClosed, ScpiTimeout):
            pass                                          # dropping the connection is acceptable
    with c_(sim, "dut") as c2:
        assert c2.query("*OPC?") == "1"


def test_abrupt_client_disconnects_do_not_affect_server(sim: Stack) -> None:
    for _ in range(20):
        s = socket.create_connection(("127.0.0.1", sim.sim_ports["analyzer"]), timeout=3)
        s.sendall(b"MEAS:RM")                             # half a command
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST on close
        s.close()
    with c_(sim, "analyzer") as c:
        assert c.query("*IDN?").startswith("MeasureFlow")
        assert drain(c) == [], "an unterminated command must not be executed on connection loss"


def test_client_closing_before_reading_response(sim: Stack) -> None:
    for _ in range(10):
        s = socket.create_connection(("127.0.0.1", sim.sim_ports["analyzer"]), timeout=3)
        s.sendall(b"MF:ACQ:WAV? 8192\nMF:ACQ:FFT?\n")
        s.close()
    with c_(sim, "analyzer") as c:
        assert c.query("*OPC?", timeout=5) == "1"


def test_idle_connection_stays_usable(sim: Stack) -> None:
    with c_(sim, "siggen") as c:
        assert c.query("*OPC?") == "1"
        time.sleep(1.5)
        assert c.query("*OPC?") == "1"


# ============================================================================ concurrency
def test_many_simultaneous_connections(sim: Stack) -> None:
    clients = [c_(sim, INSTR[i % 3]) for i in range(60)]
    try:
        for i, c in enumerate(clients):
            assert c.query("*IDN?").split(",")[1] == MODEL[INSTR[i % 3]][0]
    finally:
        for c in clients:
            c.close()


def test_concurrent_clients_get_correct_ordered_responses(sim: Stack) -> None:
    errors: list[str] = []
    n_threads, n_iter = 8, 80

    def worker(tid: int) -> None:
        inst = INSTR[tid % 3]
        try:
            with c_(sim, inst) as c:
                for i in range(n_iter):
                    if c.query("*IDN?").split(",")[1] != MODEL[inst][0]:
                        errors.append(f"t{tid} wrong idn")
                    if c.query("*OPC?") != "1":
                        errors.append(f"t{tid} wrong opc")
                    tag = f"{tid}:{i}"
                    c.write("*OPC?"); c.write("*TST?")
                    if (c.read_line(), c.read_line()) != ("1", "0"):
                        errors.append(f"t{tid} pipelined mismatch {tag}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"t{tid}: {exc!r}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    t0 = time.monotonic()
    for t in threads: t.start()
    for t in threads: t.join(60)
    assert not any(t.is_alive() for t in threads), "client threads hung"
    assert not errors, errors[:5]
    assert time.monotonic() - t0 < 30


def test_concurrent_writers_never_corrupt_shared_state(sim: Stack) -> None:
    freqs = [1000.0 + 111 * k for k in range(6)]
    seen: list[str] = []

    def worker(f: float) -> None:
        with c_(sim, "siggen") as c:
            for _ in range(60):
                c.write(f"SOUR:FREQ {f}")
                seen.append(c.query("SOUR:FREQ?"))

    ts = [threading.Thread(target=worker, args=(f,)) for f in freqs]
    for t in ts: t.start()
    for t in ts: t.join(30)
    valid = {f"{f:.9g}" for f in freqs}
    assert set(seen) <= valid, f"corrupt values: {set(seen) - valid}"
    with c_(sim, "siggen") as c:
        assert drain(c) == []


def test_concurrent_acquisitions_on_analyzer_do_not_deadlock(sim: Stack) -> None:
    with c_(sim, "siggen") as s:
        setup_tone(s)
    results: list[float] = []

    def worker() -> None:
        with c_(sim, "analyzer") as a:
            for _ in range(10):
                a.write("MF:ACQ:INIT")
                results.append(float(a.query("MEAS:RMS?")))

    ts = [threading.Thread(target=worker) for _ in range(5)]
    for t in ts: t.start()
    for t in ts: t.join(60)
    assert not any(t.is_alive() for t in ts)
    assert len(results) == 50 and all(0.3 < r < 0.45 for r in results), (min(results), max(results))


def test_fault_injection_on_one_connection_is_visible_to_other_connections(sim: Stack) -> None:
    """Counters are per instrument *server*, not per connection (contract section 3.1)."""
    with c_(sim, "dut") as a, c_(sim, "dut") as b:
        a.write("MF:FAULT:GARBAGE 1"); a.query("MF:FAULT?")
        assert b.query("*IDN?") == "#!GARBAGE~~"
        assert a.query("*IDN?").startswith("MeasureFlow")


# ============================================================================ PyVISA cross-check
def test_pyvisa_socket_resource_cross_check(sim: Stack) -> None:
    pyvisa = pytest.importorskip("pyvisa")
    pytest.importorskip("pyvisa_py")
    rm = pyvisa.ResourceManager("@py")
    try:
        for inst in INSTR:
            dev = rm.open_resource(f"TCPIP0::127.0.0.1::{sim.sim_ports[inst]}::SOCKET")
            try:
                dev.read_termination = "\n"
                dev.write_termination = "\n"
                dev.timeout = 3000
                idn = dev.query("*IDN?").strip()
                assert idn.startswith(f"MeasureFlow,{MODEL[inst][0]},{MODEL[inst][1]}")
                assert dev.query("*OPC?").strip() == "1"
                assert dev.query("SYST:ERR?").strip() == NO_ERR
                if inst == "siggen":
                    dev.write("SOUR:FREQ 1234")
                    assert float(dev.query("SOUR:FREQ?")) == 1234.0
                    assert dev.query_ascii_values("MF:SOUR:CONF?", converter="s")[0] == "SIN"
                if inst == "analyzer":
                    vals = dev.query_ascii_values("MF:ACQ:WAV? 64")
                    assert len(vals) == 64
            finally:
                dev.close()
    finally:
        rm.close()


def test_simulator_ships_pyvisa_verification_script(repo_root: Any, sim: Stack) -> None:
    script = repo_root / "simulator" / "verify_pyvisa.py"
    if not script.is_file():
        pytest.skip("simulator/verify_pyvisa.py not present")
    import subprocess
    import sys

    help_txt = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=30)
    argv = [sys.executable, str(script)]
    if "--base-port" in help_txt.stdout:
        argv += ["--base-port", str(sim.sim_base_port)]
    if "--host" in help_txt.stdout:
        argv += ["--host", "127.0.0.1"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=str(repo_root / "simulator"))
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
