"""SCPI grammar, argument validation, error queue and ``*RST`` semantics (in-process, no sockets)."""

from __future__ import annotations

import pytest

import mfsim
from mfsim import scpi
from mfsim.scpi import ErrorQueue, ScpiError, parse_line


def errors(inst_ask) -> list[str]:
    out = []
    while (entry := inst_ask("SYST:ERR?")) != '0,"No error"':
        out.append(entry)
    return out


# ---------------------------------------------------------------- header forms
@pytest.mark.parametrize("line", [
    "SOUR:FREQ 1500", "sour:freq 1500", "SOURce:FREQuency 1500", "SOURCE:FREQUENCY 1500",
    "Source:Freq 1500", "SOUR:FREQUENCY 1500", "SOURCE:FREQ 1500", ":SOUR:FREQ 1500", "SOUR:FREQ\t1500",
    "SOUR:FREQ    1500", "  SOUR:FREQ 1500  ", "SOUR:FREQ 1500\r",
])
def test_long_short_and_case_forms_are_accepted(rig, line):
    assert rig.sg(line) is None
    assert rig.sg("SOUR:FREQ?") == "1500"
    assert errors(rig.sg) == []


@pytest.mark.parametrize("line", ["SOUR:FREQU?", "SOURC:FREQ?", "SOUR:FRE?", "SOU:FREQ?", "FREQ?", "SOUR:FREQ:X?",
                                  "SOUR:FREQ1?", "SOURCES:FREQ?"])
def test_intermediate_and_unknown_mnemonics_are_undefined_headers(rig, line):
    assert rig.sg(line) is None
    assert errors(rig.sg) == ['-113,"Undefined header"']


def test_query_and_setter_forms_must_exist(rig):
    for line in ("*RST?", "*CLS?", "SYST:ERR 1", "*IDN 1", "SOUR:FREQ?5"):
        rig.sg(line)
    assert errors(rig.sg) == ['-113,"Undefined header"'] * 4 + ['-102,"Syntax error"']
    rig.an("MEAS:RMS 1")
    rig.an("MF:ACQ:INIT?")
    assert errors(rig.an) == ['-113,"Undefined header"'] * 2


def test_instruments_only_know_their_own_commands(rig):
    rig.sg("MEAS:RMS?")
    rig.sg("MF:DUT:GAIN?")
    rig.an("SOUR:FREQ?")
    rig.an("OUTP?")
    rig.du("MF:ACQ:CONF?")
    rig.du("SOUR:VOLT 1")
    assert errors(rig.sg) == ['-113,"Undefined header"'] * 2
    assert errors(rig.an) == ['-113,"Undefined header"'] * 2
    assert errors(rig.du) == ['-113,"Undefined header"'] * 2


@pytest.mark.parametrize("line", ["@#$%", "SOUR:FREQ 1000;SOUR:VOLT 1", "SOUR::FREQ 1", "1000", ":", "SOUR:FREQ, 1",
                                  "SOUR:FREQ 1,", "SOUR:FREQ ,1", "SOUR:FREQ\x01 1", "SOUR:FREQ 1\x00",
                                  "SOUR:FREQ 1000é", "é", "?", "SOUR:?", "*", "*1"])
def test_garbage_lines_push_one_error_and_no_response(rig, line):
    assert rig.sg(line) is None
    entries = errors(rig.sg)
    assert len(entries) == 1 and entries[0].split(",")[0] in {"-102", "-113", "-104"}


def test_semicolon_separated_commands_are_not_supported(rig):
    rig.sg("SOUR:FREQ 1000;SOUR:VOLT 1")
    assert errors(rig.sg) == ['-104,"Data type error"']
    assert rig.sg("SOUR:VOLT?") == "0.05"


@pytest.mark.parametrize("line", ["", "   ", "\t", "\r"])
def test_blank_lines_are_ignored_silently(rig, line):
    reply = rig.siggen.handle(line)
    assert reply.payload is None and not reply.disconnect
    assert errors(rig.sg) == []


# ---------------------------------------------------------------- arguments
@pytest.mark.parametrize("text,value", [("1000", 1000.0), ("+1000", 1000.0), ("1e3", 1000.0), ("1E3", 1000.0),
                                        ("1000.", 1000.0), (".5e4", 5000.0), ("2.5e+3", 2500.0), ("0010", 10.0)])
def test_number_syntax_accepted(rig, text, value):
    rig.sg(f"SOUR:FREQ {text}")
    assert float(rig.sg("SOUR:FREQ?")) == value and errors(rig.sg) == []


@pytest.mark.parametrize("text", ["abc", "NAN", "nan", "INF", "-inf", "1_000", "0x10", "1,5.5", "1 2", "--1", "1e",
                                  "e3",
                                  "1.2.3", "'1000'", "\"1000\"", "1000Hz"])
def test_malformed_numbers_are_data_type_errors(rig, text):
    rig.sg(f"SOUR:FREQ {text}")
    entries = errors(rig.sg)
    assert entries and entries[0] in ('-104,"Data type error"', '-102,"Syntax error"')
    assert rig.sg("SOUR:FREQ?") == "1000"                      # unchanged


@pytest.mark.parametrize("command,ok_values,bad_values", [
    ("SOUR:FREQ", ["10", "20000", "10.0", "19999.999"], ["9.999", "20000.001", "0", "-5", "1e9", "1e999"]),
    ("SOUR:VOLT", ["0", "5", "0.0001", "4.999"], ["-0.001", "5.001", "100"]),
    ("MF:SOUR:SRAT", ["8000", "192000", "44100"], ["7999", "192001", "0"]),
    ("MF:SOUR:CHIR:START", ["10", "20000"], ["9", "20001"]),
])
def test_siggen_range_boundaries(rig, command, ok_values, bad_values):
    for value in ok_values:
        rig.sg(f"{command} {value}")
        assert errors(rig.sg) == [], value
        assert float(rig.sg(f"{command}?")) == pytest.approx(float(value))
    before = rig.sg(f"{command}?")
    for value in bad_values:
        rig.sg(f"{command} {value}")
        assert errors(rig.sg) == ['-222,"Data out of range"'], value
    assert rig.sg(f"{command}?") == before                     # rejected values never change state


@pytest.mark.parametrize("command,low,high", [
    ("MF:DUT:GAIN", -20, 60), ("MF:DUT:HPF", 20, 1000), ("MF:DUT:LPF", 1000, 20000), ("MF:DUT:NOISE", -140, 0),
    ("MF:DUT:HD2", 0, 1), ("MF:DUT:HD3", 0, 1), ("MF:DUT:CLIP", 0.01, 10),
])
def test_dut_range_boundaries(rig, command, low, high):
    for value in (low, high):
        rig.du(f"{command} {value}")
        assert float(rig.du(f"{command}?")) == value
    span = high - low
    for value in (low - span * 0.001 - 1e-6, high + span * 0.001 + 1e-6):
        rig.du(f"{command} {value!r}")
    assert errors(rig.du) == ['-222,"Data out of range"'] * 2
    assert rig.du("MF:DUT:PROF?") == "CUSTOM"


def test_keyword_arguments(rig):
    for word, expected in (("SIN", "SIN"), ("sine", "SIN"), ("Square", "SQU"), ("squ", "SQU"), ("CHIRP", "CHIR"),
                           ("chir", "CHIR"), ("NOISE", "NOIS"), ("nois", "NOIS")):
        rig.sg(f"SOUR:FUNC {word}")
        assert rig.sg("SOUR:FUNC?") == expected
    for line, code in (("SOUR:FUNC TRIANGLE", -224), ("SOUR:FUNC 5", -222), ("SOUR:FUNC @@", -104),
                       ("OUTP MAYBE", -224), ("OUTP 2", -222), ("OUTP 0.5", -222)):
        rig.sg(line)
        assert errors(rig.sg) == [f'{code},"{scpi.ERROR_TEXT[code]}"'], line
    assert rig.sg("SOUR:FUNC?") == "NOIS"


@pytest.mark.parametrize("word,state", [("ON", "1"), ("on", "1"), ("1", "1"), ("OFF", "0"), ("off", "0"), ("0", "0")])
def test_output_boolean_forms(rig, word, state):
    rig.sg("OUTP ON" if state == "0" else "OUTP OFF")
    rig.sg(f"OUTP {word}")
    assert rig.sg("OUTP?") == state


@pytest.mark.parametrize("line", ["SOUR:FREQ", "SOUR:FREQ 1,2", "OUTP", "*RST 1", "*CLS 1", "MF:ACQ:INIT 1",
                                  "SOUR:FREQ? 1",
                                  "*IDN? 1", "SYST:ERR? 1"])
def test_wrong_argument_count_is_a_syntax_error(rig, line):
    rig.sg(line)
    rig.an(line)
    assert errors(rig.sg)[0].startswith("-1") and errors(rig.an)[0].startswith("-1")


def test_number_response_format_is_percent_g_nine(rig):
    rig.sg("SOUR:FREQ 1234.567890123")
    assert rig.sg("SOUR:FREQ?") == "1234.56789"
    rig.sg("SOUR:VOLT 0.1234567891")
    assert rig.sg("SOUR:VOLT?") == "0.123456789"
    rig.sg("MF:SOUR:SRAT 12345.5")
    assert rig.sg("MF:SOUR:SRAT?") == "12345.5"
    assert rig.du("MF:DUT:NOISE?") == "-80"
    assert scpi.format_number(float("nan")) == "NAN" and scpi.format_number(float("inf")) == "INF"
    assert scpi.format_number(float("-inf")) == "-INF" and scpi.format_number(1e-5) == "1e-05"


# ---------------------------------------------------------------- error queue
def test_error_queue_order_and_empty_marker(rig):
    assert rig.sg("SYST:ERR?") == '0,"No error"'
    rig.sg("BOGUS")
    rig.sg("SOUR:FREQ 1e9")
    rig.sg("SOUR:FREQ abc")
    rig.sg("@@")
    assert [rig.sg("SYST:ERR?") for _ in range(5)] == [
        '-113,"Undefined header"', '-222,"Data out of range"', '-104,"Data type error"', '-102,"Syntax error"',
        '0,"No error"']
    assert rig.sg("SYST:ERR?") == '0,"No error"'


def test_cls_clears_the_queue_only(rig):
    rig.sg("SOUR:FREQ 2000")
    rig.sg("BOGUS")
    rig.sg("*CLS")
    assert errors(rig.sg) == []
    assert rig.sg("SOUR:FREQ?") == "2000"


def test_error_queue_overflow_keeps_first_19_then_minus_350(rig):
    for _ in range(30):
        rig.sg("BOGUS")
    entries = errors(rig.sg)
    assert len(entries) == 20
    assert entries[:19] == ['-113,"Undefined header"'] * 19
    assert entries[19] == '-350,"Queue overflow"'


def test_error_queue_unit_behaviour():
    queue = ErrorQueue()
    assert len(queue) == 0 and queue.pop() == '0,"No error"'
    queue.push(-222)
    assert len(queue) == 1
    queue.clear()
    assert len(queue) == 0
    with pytest.raises(ScpiError) as info:
        parse_line("@")
    assert info.value.code == -102 and str(info.value) == "Syntax error"


def test_each_instrument_has_its_own_error_queue(rig):
    rig.sg("BOGUS")
    assert errors(rig.an) == [] and errors(rig.du) == []
    assert len(errors(rig.sg)) == 1


# ---------------------------------------------------------------- common commands
def test_common_commands(rig):
    assert rig.sg("*IDN?") == "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0"
    assert rig.an("*IDN?") == "MeasureFlow,VAA-2000,SN-SIM-0002,1.0.0"
    assert rig.du("*IDN?") == "MeasureFlow,VDUT-HA1,SN-SIM-0003,1.0.0"
    rig.du("MF:DUT:FW 1.2.0")
    assert rig.du("*IDN?") == "MeasureFlow,VDUT-HA1,SN-SIM-0003,1.2.0"
    assert rig.an("*IDN?").endswith(",1.0.0")
    for ask in (rig.sg, rig.an, rig.du):
        assert ask("*OPC?") == "1" and ask("*TST?") == "0" and ask("SYST:VERS?") == "1999.0"
        assert ask("MF:SIM:VERS?") == mfsim.__version__ == "0.1.0"
        assert ask("*OPC") is None and ask("*idn?").startswith("MeasureFlow,")
        assert ask("SYSTem:VERSion?") == "1999.0" and ask("syst:err?") == '0,"No error"'
    assert errors(rig.sg) == []


def test_setters_never_respond_and_queries_respond_exactly_once(rig):
    for ask, setter, query in ((rig.sg, "SOUR:FREQ 500", "SOUR:FREQ?"), (rig.du, "MF:DUT:GAIN 10", "MF:DUT:GAIN?"),
                               (rig.an, "MF:ACQ:POIN 2048", "MF:ACQ:POIN?")):
        assert ask(setter) is None
        response = ask(query)
        assert response is not None and "\n" not in response
    payload = rig.siggen.handle("SOUR:FREQ?").payload
    assert payload is not None and payload.endswith(b"\n") and not payload.endswith(b"\r\n")
    assert payload.count(b"\n") == 1


# ---------------------------------------------------------------- *RST
def test_rst_restores_siggen_defaults(rig):
    rig.sg("SOUR:FUNC CHIR")
    rig.sg("SOUR:FREQ 5000")
    rig.sg("SOUR:VOLT 1.5")
    rig.sg("OUTP ON")
    rig.sg("MF:SOUR:SRAT 96000")
    rig.sg("MF:SOUR:CHIR:START 300")
    assert rig.sg("MF:SOUR:CONF?") == "CHIR,5000,1.5,96000,1"
    rig.sg("*RST")
    assert rig.sg("MF:SOUR:CONF?") == "SIN,1000,0.05,48000,0"
    assert rig.sg("MF:SOUR:CHIR:START?") == "20" and rig.sg("OUTP?") == "0"


def test_rst_restores_dut_defaults(rig):
    rig.du("MF:DUT:PROF NOISY")
    rig.du("MF:DUT:FW 1.2.0")
    rig.du("MF:DUT:FAULT NAN")
    rig.du("MF:DUT:GAIN 3")
    rig.du("*RST")
    assert rig.du("MF:DUT:CONF?") == "NORMAL,20,100,8000,-80,0.004,0.01,1.5,1.0.0"
    assert rig.du("MF:DUT:FAULT?") == "NONE" and rig.du("MF:DUT:FW?") == "1.0.0" and rig.du("MF:DUT:PROF?") == "NORMAL"


def test_rst_restores_analyzer_defaults_and_acquisition_state(rig):
    rig.tone()
    rig.an("MF:ACQ:POIN 2048")
    rig.an("MF:ACQ:SEED 777")
    rig.an("MF:ACQ:INIT")
    rig.an("MF:ACQ:INIT")
    assert rig.an("MF:ACQ:CONF?") == "2048,48000,1,2"
    rig.an("*RST")
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,0,0"
    assert rig.an("MF:ACQ:SEED?") == "12345"


def test_rst_on_any_instrument_resets_counter_and_drops_the_stored_buffer(rig):
    rig.tone()
    rig.an("MF:ACQ:SEED 5")
    rig.an("MF:ACQ:INIT")
    assert rig.an("MF:ACQ:CONF?").endswith(",1,1")
    rig.du("*RST")
    assert rig.an("MF:ACQ:CONF?") == "16384,48000,0,0" and rig.an("MF:ACQ:SEED?") == "12345"


def test_rst_clears_faults_but_not_the_error_queue(rig):
    rig.sg("MF:FAULT:GARBAGE 3")
    rig.sg("MF:FAULT:TIMEOUT 2,50")
    rig.sg("BOGUS")
    rig.sg("*RST")
    assert rig.sg("MF:FAULT?") == "TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0"
    assert errors(rig.sg) == ['-113,"Undefined header"']


def test_rst_uses_the_simulator_seed_as_default():
    from conftest import Rig
    rig = Rig(seed=4242)
    assert rig.an("MF:ACQ:SEED?") == "4242"
    rig.an("MF:ACQ:SEED 1")
    rig.an("*RST")
    assert rig.an("MF:ACQ:SEED?") == "4242"


# ---------------------------------------------------------------- DUT command semantics
def test_dut_profile_semantics(rig):
    for name in ("NORMAL", "LOWGAIN", "HIGHTHD", "NOISY", "CLIPPING", "lowgain"):
        rig.du(f"MF:DUT:PROF {name}")
        assert rig.du("MF:DUT:PROF?") == name.upper()
    rig.du("MF:DUT:PROF CLIPPING")
    assert rig.du("MF:DUT:CONF?") == "CLIPPING,20,100,8000,-80,0.004,0.01,0.3,1.0.0"
    rig.du("MF:DUT:HPF 150")
    assert rig.du("MF:DUT:PROF?") == "CUSTOM"
    assert rig.du("MF:DUT:CONF?") == "CUSTOM,20,150,8000,-80,0.004,0.01,0.3,1.0.0"
    rig.du("MF:DUT:FW 1.1.0")
    rig.du("MF:DUT:PROF NORMAL")
    assert rig.du("MF:DUT:CONF?") == "NORMAL,20,100,8000,-80,0.004,0.01,1.5,1.1.0"      # preset keeps the firmware
    rig.du("MF:DUT:PROF FANCY")
    rig.du("MF:DUT:PROF CUSTOM")
    assert errors(rig.du) == ['-224,"Illegal parameter value"'] * 2


def test_dut_firmware_and_fault_validation(rig):
    for version in ("1.0.0", "1.1.0", "1.2.0"):
        rig.du(f"MF:DUT:FW {version}")
        assert rig.du("MF:DUT:FW?") == version
    for bad, code in (("1.3.0", -224), ("2.0.0", -224), ("1.2", -222), ("v1.0.0", -224), ("1.0.0.0", -224),
                      ("@", -104)):
        rig.du(f"MF:DUT:FW {bad}")
        assert errors(rig.du) == [f'{code},"{scpi.ERROR_TEXT[code]}"'], bad
    assert rig.du("MF:DUT:FW?") == "1.2.0"
    for mode in ("NAN", "inf", "NONE"):
        rig.du(f"MF:DUT:FAULT {mode}")
        assert rig.du("MF:DUT:FAULT?") == mode.upper()
    rig.du("MF:DUT:FAULT SOME")
    assert errors(rig.du) == ['-224,"Illegal parameter value"']


def test_configured_values_stay_those_of_the_profile_under_firmware(rig):
    rig.du("MF:DUT:FW 1.2.0")
    assert rig.du("MF:DUT:CONF?") == "NORMAL,20,100,8000,-80,0.004,0.01,1.5,1.2.0"
    assert rig.du("MF:DUT:HD2?") == "0.004" and rig.du("MF:DUT:NOISE?") == "-80"


def test_siggen_conf_query_and_chirp_start(rig):
    assert rig.sg("MF:SOUR:CONF?") == "SIN,1000,0.05,48000,0"
    rig.sg("SOUR:FUNC SQU")
    rig.sg("SOUR:FREQ 440")
    rig.sg("OUTP 1")
    assert rig.sg("MF:SOUR:CONF?") == "SQU,440,0.05,48000,1"
    assert rig.sg("MF:SOUR:CHIR:START?") == "20"


def test_handler_failure_becomes_execution_error(rig):
    def boom(_args):
        raise RuntimeError("synthetic failure")

    object.__setattr__(rig.siggen.table.lookup(("SOUR", "FREQ")), "getter", boom)   # frozen dataclass
    assert rig.sg("SOUR:FREQ?") is None
    assert errors(rig.sg) == ['-200,"Execution error"']
    assert rig.sg("*OPC?") == "1"                                                # instrument keeps working
