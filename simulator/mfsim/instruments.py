"""The three virtual instruments: signal generator, audio analyzer and device under test."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

from .bench import DEFAULT_POINTS, POINTS_RANGE, Acquisition
from .dsp import WINDOW_NAME
from .dut import FAULT_MODES, DutState
from .firmware import FIRMWARE
from .generator import AMPLITUDE_RANGE_V, FREQ_RANGE_HZ, SAMPLE_RATE_RANGE_HZ, SigGenState
from .instrument import Instrument
from .profiles import PROFILES
from .scpi import (DATA_CORRUPT, OUT_OF_RANGE, SETTINGS_CONFLICT, Command, ScpiError,
                   format_number, format_vector, parse_integer, parse_keyword)

_FUNCTION_WORDS = {"SIN": "SIN", "SINE": "SIN", "SQU": "SQU", "SQUARE": "SQU",
                   "CHIR": "CHIR", "CHIRP": "CHIR", "NOIS": "NOIS", "NOISE": "NOIS"}
_BOOLEAN_WORDS = {"ON": True, "OFF": False, "1": True, "0": False}
DEFAULT_WAVEFORM_POINTS = 512
MAX_SEED = 2 ** 63 - 1


def _flag(value: bool) -> str:
    return "1" if value else "0"


class SigGen(Instrument):
    """Virtual signal generator ``VSG-1000``.

    It only holds settings; samples are rendered by the bench during an acquisition, so the
    analyzer measures what the generator would have produced (phase 0 at the window start).
    """

    MODEL = "VSG-1000"
    SERIAL = "SN-SIM-0001"

    def reset_state(self) -> None:
        self.bench.siggen = SigGenState()

    def register(self) -> None:
        add = self.table.add
        state: Callable[[], SigGenState] = lambda: self.bench.siggen  # noqa: E731
        add(Command("SOURce:FUNCtion", self._set_function, lambda _a: state().function))
        add(self.number_command("SOURce:FREQuency", lambda: state().frequency_hz,
                                lambda v: setattr(state(), "frequency_hz", v), *FREQ_RANGE_HZ))
        add(self.number_command("SOURce:VOLTage", lambda: state().amplitude_vpk,
                                lambda v: setattr(state(), "amplitude_vpk", v), *AMPLITUDE_RANGE_V))
        add(Command("OUTPut", self._set_output, lambda _a: _flag(state().output_on)))
        add(self.number_command("MF:SOURce:SRATe", lambda: state().sample_rate_hz,
                                lambda v: setattr(state(), "sample_rate_hz", v), *SAMPLE_RATE_RANGE_HZ))
        add(self.number_command("MF:SOURce:CHIRp:STARt", lambda: state().chirp_start_hz,
                                lambda v: setattr(state(), "chirp_start_hz", v), *FREQ_RANGE_HZ))
        add(Command("MF:SOURce:CONFig", getter=self._get_config))

    def _set_function(self, args: tuple[str, ...]) -> None:
        self.bench.siggen.function = str(parse_keyword(args[0], _FUNCTION_WORDS))
        self.bench.invalidate()

    def _set_output(self, args: tuple[str, ...]) -> None:
        self.bench.siggen.output_on = bool(parse_keyword(args[0], _BOOLEAN_WORDS))
        self.bench.invalidate()

    def _get_config(self, _args: tuple[str, ...]) -> str:
        s = self.bench.siggen
        return ",".join((s.function, format_number(s.frequency_hz), format_number(s.amplitude_vpk),
                         format_number(s.sample_rate_hz), _flag(s.output_on)))


class Dut(Instrument):
    """Virtual hearing-aid device under test ``VDUT-HA1`` (chain described in :mod:`mfsim.dut`)."""

    MODEL = "VDUT-HA1"
    SERIAL = "SN-SIM-0003"

    def firmware(self) -> str:
        return self.bench.dut.firmware

    def reset_state(self) -> None:
        self.bench.dut = DutState()

    def register(self) -> None:
        add = self.table.add
        add(Command("MF:DUT:PROFile", self._set_profile, lambda _a: self.bench.dut.profile))
        for header, name, low, high in (
                ("GAIN", "gain_db", -20.0, 60.0), ("HPF", "hpf_hz", 20.0, 1000.0),
                ("LPF", "lpf_hz", 1000.0, 20000.0), ("NOISe", "noise_dbv", -140.0, 0.0),
                ("HD2", "hd2", 0.0, 1.0), ("HD3", "hd3", 0.0, 1.0), ("CLIP", "clip_vpk", 0.01, 10.0)):
            add(self.number_command(f"MF:DUT:{header}", self._reader(name), self._writer(name), low, high))
        add(Command("MF:DUT:FW", self._set_firmware, lambda _a: self.bench.dut.firmware))
        add(Command("MF:DUT:FAULT", self._set_fault, lambda _a: self.bench.dut.fault))
        add(Command("MF:DUT:CONFig", getter=self._get_config))

    def _reader(self, name: str) -> Callable[[], float]:
        return lambda: getattr(self.bench.dut.params, name)

    def _writer(self, name: str) -> Callable[[float], None]:
        def write(value: float) -> None:
            dut = self.bench.dut
            dut.params = replace(dut.params, **{name: value})
            dut.profile = "CUSTOM"
        return write

    def _set_profile(self, args: tuple[str, ...]) -> None:
        name = str(parse_keyword(args[0], {key: key for key in PROFILES}))
        self.bench.dut.profile = name
        self.bench.dut.params = PROFILES[name]
        self.bench.invalidate()

    def _set_firmware(self, args: tuple[str, ...]) -> None:
        self.bench.dut.firmware = str(parse_keyword(args[0], {key: key for key in FIRMWARE}))
        self.bench.invalidate()

    def _set_fault(self, args: tuple[str, ...]) -> None:
        self.bench.dut.fault = str(parse_keyword(args[0], {mode: mode for mode in FAULT_MODES}))
        self.bench.invalidate()

    def _get_config(self, _args: tuple[str, ...]) -> str:
        dut = self.bench.dut
        p = dut.params
        values = (p.gain_db, p.hpf_hz, p.lpf_hz, p.noise_dbv, p.hd2, p.hd3, p.clip_vpk)
        return ",".join((dut.profile, *map(format_number, values), dut.firmware))


class Analyzer(Instrument):
    """Virtual audio analyzer ``VAA-2000`` measuring the DUT output.

    Measurement queries work on the stored acquisition (see :class:`mfsim.bench.Bench`).
    Non-finite DUT output yields ``NAN`` and error -230; ``GAIN``/``THD``/``SNR`` need a sine
    with non-zero amplitude and the generator output on, otherwise ``NAN`` and error -221.
    """

    MODEL = "VAA-2000"
    SERIAL = "SN-SIM-0002"

    def reset_state(self) -> None:
        self.bench.points = DEFAULT_POINTS

    def register(self) -> None:
        add = self.table.add
        add(Command("MF:ACQ:POINts", self._set_points, lambda _a: str(self.bench.points)))
        add(Command("MF:ACQ:SEED", self._set_seed, lambda _a: str(self.bench.seed)))
        add(Command("MF:ACQ:INIT", self._init, set_args=(0, 0)))
        add(Command("MF:ACQ:CONFig", getter=self._get_config))
        add(Command("MF:ACQ:WAVeform", getter=self._get_waveform, get_args=(0, 1)))
        add(Command("MF:ACQ:FFT", getter=self._get_spectrum, get_args=(0, 1)))
        add(Command("MF:ANALyzer:WINdow", getter=lambda _a: WINDOW_NAME))
        for name, fn, needs_tone in (
                ("RMS", lambda a: a.rms_v, False),
                ("GAIN", lambda a: a.gain_db, True),
                ("THD", lambda a: a.output_analysis.thd_percent(), True),
                ("SNR", lambda a: a.output_analysis.snr_db(), True),
                ("NOISe", self._noise, False),
                ("FREQuency", lambda a: a.output_analysis.frequency_hz, False)):
            add(Command(f"MEASure:{name}", getter=self._measurement(fn, needs_tone)))

    def _init(self, _args: tuple[str, ...]) -> None:
        self.bench.acquire()

    def _set_points(self, args: tuple[str, ...]) -> None:
        points = parse_integer(args[0], *POINTS_RANGE)
        if points & (points - 1):
            raise ScpiError(OUT_OF_RANGE)
        self.bench.points = points
        self.bench.invalidate()

    def _set_seed(self, args: tuple[str, ...]) -> None:
        self.bench.seed = parse_integer(args[0], 0, MAX_SEED)
        self.bench.counter = 0
        self.bench.invalidate()

    def _get_config(self, _args: tuple[str, ...]) -> str:
        b = self.bench
        stored = _flag(b.stored is not None)
        return f"{b.points},{format_number(b.siggen.sample_rate_hz)},{stored},{b.counter}"

    @staticmethod
    def _noise(acq: Acquisition) -> float:
        """In-band noise; the tone and its harmonics are excluded only if a sine is applied."""
        return acq.output_analysis.noise_dbv(exclude_tone=acq.tone_present)

    def _measurement(self, compute: Callable[[Acquisition], float], needs_tone: bool
                     ) -> Callable[[tuple[str, ...]], str]:
        def query(_args: tuple[str, ...]) -> str:
            acq = self.bench.current()
            if needs_tone and not acq.tone_present:
                self.errors.push(SETTINGS_CONFLICT)
                return "NAN"
            if not acq.finite:
                self.errors.push(DATA_CORRUPT)
                return "NAN"
            return format_number(compute(acq))
        return query

    def _get_waveform(self, args: tuple[str, ...]) -> str:
        count = parse_integer(args[0], 1, self.bench.points) if args else DEFAULT_WAVEFORM_POINTS
        samples = self.bench.current().output[:count]
        if not math.isfinite(float(samples.sum())):
            self.errors.push(DATA_CORRUPT)
        return format_vector(samples)

    def _get_spectrum(self, args: tuple[str, ...]) -> str:
        n = self.bench.points
        count = parse_integer(args[0], 1, n // 2 + 1) if args else n // 2 + 1
        acq = self.bench.current()
        if acq.finite:
            body = format_vector(acq.output_analysis.amplitude_dbv()[:count])
        else:
            self.errors.push(DATA_CORRUPT)
            body = ",".join(["NAN"] * count)
        return f"{format_number(acq.sample_rate_hz)},{n},{body}"
