"""TCP transport: framing, many clients, abrupt disconnects, lifecycle."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from conftest import Client, wait_until
from mfsim.scpi import MAX_LINE_BYTES
from mfsim.server import LineFramer
from mfsim.simulator import Simulator


def test_ready_line_and_ports(sim):
    ports = sim.ports
    assert sim.ready_line() == f"READY siggen={ports['siggen']} analyzer={ports['analyzer']} dut={ports['dut']}"
    assert len(set(ports.values())) == 3 and all(p > 0 for p in ports.values())


def test_each_port_serves_its_own_instrument(siggen, analyzer, dut):
    assert siggen.query("*IDN?") == "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0"
    assert analyzer.query("*IDN?") == "MeasureFlow,VAA-2000,SN-SIM-0002,1.0.0"
    assert dut.query("*IDN?") == "MeasureFlow,VDUT-HA1,SN-SIM-0003,1.0.0"


def test_signal_path_across_the_three_servers(siggen, analyzer, dut):
    siggen.send("SOUR:FREQ 2000", "SOUR:VOLT 0.1", "OUTP ON")
    siggen.sync()
    dut.send("MF:DUT:PROF LOWGAIN")
    dut.sync()
    assert float(analyzer.query("MEAS:GAIN?")) == pytest.approx(14.0, abs=0.05)
    assert analyzer.query("MF:ACQ:CONF?") == "16384,48000,1,1"


def test_default_port_layout_is_base_plus_offsets():
    from conftest import free_port_block
    base = free_port_block()
    with Simulator(base_port=base) as simulator:
        assert simulator.ports == {"siggen": base, "analyzer": base + 1, "dut": base + 2}
        assert Client(base + 2).query("*IDN?").startswith("MeasureFlow,VDUT-HA1")


def test_binds_only_the_requested_host(sim):
    assert all(server._server.server_address[0] == "127.0.0.1" for server in sim._servers.values())


def test_port_in_use_raises_and_releases_everything():
    from conftest import free_port_block
    base = free_port_block()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", base + 1))
    blocker.listen()
    try:
        with pytest.raises(OSError):
            Simulator(base_port=base)
        # the first port must have been released again
        probe = socket.socket()
        probe.bind(("127.0.0.1", base))
        probe.close()
    finally:
        blocker.close()


def test_ipv6_loopback_if_available():
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    try:
        probe = socket.socket(socket.AF_INET6)
        probe.bind(("::1", 0))
        probe.close()
    except OSError:
        pytest.skip("::1 not bindable")
    with Simulator(host="::1", base_port=0) as simulator, \
            socket.create_connection(("::1", simulator.ports["siggen"]), timeout=3) as conn:
        conn.sendall(b"*OPC?\n")
        assert conn.recv(16) == b"1\n"


# ---------------------------------------------------------------- framing
def test_crlf_and_lf_terminators_and_pipelining(siggen):
    siggen.sock.sendall(b"SOUR:FREQ 1234\r\nSOUR:FREQ?\r\n*IDN?\n  *OPC?  \r\nSOUR:FREQ?\n")
    assert [siggen.read_line() for _ in range(4)] == ["1234", "MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0", "1", "1234"]
    assert "\r" not in siggen.buffer.decode()


def test_responses_end_with_lf_only(siggen):
    siggen.sock.sendall(b"*OPC?\r\n")
    time.sleep(0.1)
    assert siggen.sock.recv(16) == b"1\n"


def test_partial_lines_are_buffered_until_the_terminator(siggen):
    for chunk in (b"SOUR", b":FRE", b"Q 4321", b"\n", b"SO", b"UR:FREQ?", b"\r", b"\n"):
        siggen.sock.sendall(chunk)
        time.sleep(0.02)
    assert siggen.read_line() == "4321"


def test_byte_by_byte_delivery(siggen):
    for byte in b"*IDN?\n":
        siggen.sock.sendall(bytes([byte]))
    assert siggen.read_line().startswith("MeasureFlow,VSG-1000")


def test_unterminated_command_is_not_executed_until_the_terminator_arrives(sim, siggen, make_client):
    siggen.sock.sendall(b"SOUR:FREQ 777")
    time.sleep(0.1)
    other = make_client("siggen")
    assert other.query("SOUR:FREQ?") == "1000"
    siggen.sock.sendall(b"\n")
    siggen.sync()
    assert other.query("SOUR:FREQ?") == "777"


def test_line_of_exactly_4096_bytes_is_accepted_and_4097_is_rejected(siggen):
    ok = b"*OPC?" + b" " * (MAX_LINE_BYTES - 5) + b"\n"
    assert len(ok) == MAX_LINE_BYTES + 1
    siggen.sock.sendall(ok)
    assert siggen.read_line() == "1"
    siggen.sock.sendall(b"*OPC?" + b" " * (MAX_LINE_BYTES - 4) + b"\n")           # 4097 bytes
    assert siggen.query("*OPC?") == "1"                                           # stream stays in sync
    assert siggen.drain_errors() == ['-102,"Syntax error"']


def test_overlong_line_is_dropped_whole_even_when_it_arrives_in_pieces(siggen):
    siggen.sock.sendall(b"SOUR:FREQ " + b"9" * 3000)
    time.sleep(0.05)
    siggen.sock.sendall(b"9" * 3000)                                              # passes 4096 here
    time.sleep(0.05)
    siggen.sock.sendall(b"9" * 3000 + b"\nSOUR:FREQ 1500\n")
    assert siggen.query("SOUR:FREQ?") == "1500"
    assert siggen.drain_errors() == ['-102,"Syntax error"']                       # reported once


def test_megabyte_without_newline_does_not_grow_memory_or_kill_the_server(siggen):
    siggen.sock.sendall(b"A" * (1 << 20))
    siggen.sock.sendall(b"\n*OPC?\n")
    assert siggen.read_line() == "1"
    assert siggen.drain_errors() == ['-102,"Syntax error"']


def test_binary_garbage_never_crashes_a_connection(siggen):
    siggen.sock.sendall(bytes(range(256)) * 4 + b"\n")
    siggen.sock.sendall(b"\xff\xfe\x00\x01\n\n\n\r\n")
    assert siggen.query("*OPC?") == "1"
    assert siggen.drain_errors()                                                   # complaints were queued


def test_line_framer_unit():
    framer = LineFramer(max_line=8)
    assert framer.feed(b"abc") == [] and framer.feed(b"d\r\nxy\n") == ["abcd", "xy"]
    assert framer.feed(b"123456789") == []                                        # 9 = max + 1: could still be "...\r"
    assert framer.feed(b"0") == [None]                                            # 10 pending bytes without terminator
    assert framer.feed(b"zzzz") == []                                             # dropping
    assert framer.feed(b"\nok\n") == ["ok"]
    assert framer.feed(b"123456789\nnext\n") == [None, "next"]
    assert framer.feed(b"12345678\r\n") == ["12345678"]                           # exactly max_line is fine
    assert framer.feed(b"\xe9\n") == ["\xe9"]                                     # latin-1 decoding never fails


# ---------------------------------------------------------------- robustness
def test_clients_that_vanish_never_hurt_the_server(sim):
    port = sim.ports["analyzer"]
    for i in range(40):
        s = socket.create_connection(("127.0.0.1", port))
        if i % 4 == 0:
            s.sendall(b"MEAS:RMS?\n")                                       # then vanish before reading the answer
        elif i % 4 == 1:
            s.sendall(b"MF:ACQ:WAV? 16384\n")
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")   # RST on close
        elif i % 4 == 2:
            s.sendall(b"MEAS:GA")                                           # vanish in the middle of a line
        s.close()
    time.sleep(0.1)
    client = Client(port)
    assert client.query("*OPC?") == "1"
    client.close()


def test_client_that_never_reads_a_big_answer_does_not_block_others(sim):
    slow = socket.create_connection(("127.0.0.1", sim.ports["analyzer"]))
    slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    for _ in range(20):
        slow.sendall(b"MF:ACQ:FFT?\n")
    other = Client(sim.ports["analyzer"])
    assert other.query("*OPC?") == "1"
    slow.close()
    other.close()


def test_many_concurrent_clients_get_consistent_answers(sim):
    clients_per_instrument, rounds = 4, 40                                     # 12 clients in total
    failures: list[str] = []

    def worker(name: str, index: int) -> None:
        try:
            client = Client(sim.ports[name])
            for round_no in range(rounds):
                if name == "siggen":
                    client.send(f"SOUR:VOLT {0.01 + 0.001 * ((index + round_no) % 5)}")
                    assert 0.01 <= float(client.query("SOUR:VOLT?")) <= 0.015
                elif name == "analyzer":
                    assert client.query("MEAS:RMS?") != ""
                    assert client.query("MF:ACQ:CONF?").count(",") == 3
                else:
                    assert client.query("MF:DUT:CONF?").count(",") == 8
                assert client.query("*IDN?").startswith("MeasureFlow,")
            assert client.query("SYST:ERR?") in ('0,"No error"',)
            client.close()
        except Exception as error:  # noqa: BLE001 - collect failures from worker threads
            failures.append(f"{name}#{index}: {error!r}")

    threads = [threading.Thread(target=worker, args=(name, i))
               for name in ("siggen", "analyzer", "dut") for i in range(clients_per_instrument)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not failures, failures
    assert not any(t.is_alive() for t in threads)
    assert time.perf_counter() - started < 15


def test_concurrent_measurements_and_reconfiguration_are_race_free(sim):
    """Config changes interleave with acquisitions; every answer must still be a valid number or NAN."""
    stop = threading.Event()
    bad: list[str] = []

    def reconfigure() -> None:
        client = Client(sim.ports["siggen"])
        dut = Client(sim.ports["dut"])
        profiles = ("NORMAL", "LOWGAIN", "HIGHTHD", "NOISY")
        i = 0
        while not stop.is_set():
            client.send(f"SOUR:FREQ {200 + 100 * (i % 20)}", f"OUTP {i % 2}")
            dut.send(f"MF:DUT:PROF {profiles[i % 4]}")
            i += 1
            client.sync()

    def measure(query: str) -> None:
        client = Client(sim.ports["analyzer"])
        for _ in range(60):
            value = client.query(query)
            try:
                float(value.replace("NAN", "nan"))
            except ValueError:
                bad.append(f"{query} -> {value!r}")
        client.close()

    writer = threading.Thread(target=reconfigure)
    queries = ("MEAS:GAIN?", "MEAS:THD?", "MEAS:NOIS?", "MEAS:RMS?")
    readers = [threading.Thread(target=measure, args=(q,)) for q in queries]
    writer.start()
    for r in readers:
        r.start()
    for r in readers:
        r.join(30)
    stop.set()
    writer.join(10)
    assert not bad, bad


def test_fifty_simultaneous_connections(sim):
    clients = [Client(sim.ports["dut"]) for _ in range(50)]
    assert all(c.query("*OPC?") == "1" for c in clients)
    for c in clients:
        c.close()


def test_sustained_command_rate(siggen, analyzer):
    siggen.send("SOUR:VOLT 0.05", "OUTP ON")
    siggen.sync()
    start = time.perf_counter()
    for _ in range(300):
        analyzer.send("MF:ACQ:INIT")
        analyzer.query("MEAS:GAIN?")
    per_pair = (time.perf_counter() - start) / 300
    assert per_pair < 0.030                                                  # INIT + one measurement < 30 ms
    start = time.perf_counter()
    for _ in range(2000):
        siggen.query("SOUR:FREQ?")
    assert 2000 / (time.perf_counter() - start) > 1000                       # >> thousands of commands/minute


def test_stop_closes_clients_and_releases_ports():
    simulator = Simulator(base_port=0)
    simulator.start()
    client = Client(simulator.ports["siggen"])
    assert client.query("*OPC?") == "1"
    port = simulator.ports["siggen"]
    simulator.stop()
    with pytest.raises((ConnectionError, OSError)):
        client.read_line(timeout=2)
    assert wait_until(lambda: _refuses(port))
    simulator.stop()                                                          # idempotent


def _refuses(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except OSError:
        return True
    return False
