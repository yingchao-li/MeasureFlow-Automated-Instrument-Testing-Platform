"""Fault injection over real TCP sockets: every injection must have its real-world effect."""

from __future__ import annotations

import socket
import time

import pytest

from mfsim.faults import GARBAGE_TEXT, OVERSIZE_BYTES, FaultInjector

CLEAN = "TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0"
INSTRUMENTS = ("siggen", "analyzer", "dut")


@pytest.mark.parametrize("name", INSTRUMENTS)
def test_every_server_supports_the_fault_commands(make_client, name):
    client = make_client(name)
    assert client.query("MF:FAULT?") == CLEAN
    for kind in ("TIMEOUT", "DISCONNECT", "GARBAGE", "FRAGMENT", "NAN", "INF", "OVERSIZE"):
        client.send(f"MF:FAULT:{kind} 2")
    assert client.query("MF:FAULT?") == "TIMEOUT=2,DISCONNECT=2,GARBAGE=2,FRAGMENT=2,NAN=2,INF=2,OVERSIZE=2"
    client.send("MF:FAULT:CLEAR")
    assert client.query("MF:FAULT?") == CLEAN
    assert client.drain_errors() == []


def test_timeout_really_delays_the_response(siggen):
    siggen.send("MF:FAULT:TIMEOUT 2,300")
    start = time.perf_counter()
    assert siggen.query("*OPC?") == "1"
    assert time.perf_counter() - start >= 0.29
    start = time.perf_counter()
    assert siggen.query("SOUR:FREQ?") == "1000"
    assert time.perf_counter() - start >= 0.29
    start = time.perf_counter()
    assert siggen.query("SOUR:FREQ?") == "1000"
    assert time.perf_counter() - start < 0.1                    # counter exhausted
    assert siggen.query("MF:FAULT?") == CLEAN


def test_timeout_default_delay_is_five_seconds(siggen):
    siggen.send("MF:FAULT:TIMEOUT 1")
    siggen.sock.sendall(b"*OPC?\n")
    with pytest.raises(socket.timeout):
        siggen.read_line(timeout=0.5)                           # nothing within 0.5 s
    injector = FaultInjector()
    injector.arm("TIMEOUT", 1)
    assert injector.on_command().delay_s == 5.0


def test_timeout_also_stalls_setters_and_the_following_commands(siggen):
    siggen.send("MF:FAULT:TIMEOUT 1,250")
    start = time.perf_counter()
    siggen.send("SOUR:FREQ 2000")                               # executes, then the connection stalls
    assert siggen.query("SOUR:FREQ?") == "2000"
    assert time.perf_counter() - start >= 0.24


def test_disconnect_closes_the_connection_without_a_response_and_drops_the_command(sim, make_client):
    victim = make_client("siggen")
    victim.send("MF:FAULT:DISCONNECT 1")
    victim.send("SOUR:FREQ 4000")
    victim.sock.settimeout(3)
    assert victim.sock.recv(100) == b""                         # orderly close, nothing answered
    survivor = make_client("siggen")
    assert survivor.query("SOUR:FREQ?") == "1000"               # the command was not executed
    assert survivor.query("MF:FAULT?") == CLEAN                 # and the counter was consumed


def test_disconnect_counts_commands_across_reconnects(make_client):
    admin = make_client("analyzer")
    admin.send("MF:FAULT:DISCONNECT 2")
    for _ in range(2):
        victim = make_client("analyzer")
        victim.send("*OPC?")
        victim.sock.settimeout(3)
        assert victim.sock.recv(100) == b""
    assert make_client("analyzer").query("*OPC?") == "1"


def test_garbage_replaces_query_responses_only(siggen):
    siggen.send("MF:FAULT:GARBAGE 2")
    siggen.send("SOUR:FREQ 1500")                               # setters do not consume
    assert siggen.query("MF:FAULT?") == CLEAN.replace("GARBAGE=0", "GARBAGE=2")
    assert siggen.query("SOUR:FREQ?") == GARBAGE_TEXT == "#!GARBAGE~~"
    assert siggen.query("*IDN?") == "#!GARBAGE~~"
    assert siggen.query("SOUR:FREQ?") == "1500"
    with pytest.raises(ValueError):
        float(GARBAGE_TEXT)


def test_fragment_arrives_in_chunks_with_pauses(siggen):
    siggen.send("MF:FAULT:FRAGMENT 1,4,60")
    siggen.sock.sendall(b"*IDN?\n")                             # 38 bytes -> 10 chunks, 9 pauses of 60 ms
    expected = b"MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0\n"
    siggen.sock.settimeout(3)
    received, arrivals = b"", []
    start = time.perf_counter()
    while not received.endswith(b"\n"):
        chunk = siggen.sock.recv(1024)
        arrivals.append(time.perf_counter() - start)
        received += chunk
    assert received == expected
    assert len(arrivals) >= 6                                   # delivered in pieces, not in one segment
    assert arrivals[-1] >= 0.4                                  # ~9 x 60 ms spent in total
    assert arrivals[0] < 0.2
    assert siggen.query("*OPC?") == "1"                         # next response is whole again


def test_fragment_defaults_are_three_bytes_every_15_ms(siggen):
    siggen.send("MF:FAULT:FRAGMENT 1")
    siggen.sock.sendall(b"*IDN?\n")
    siggen.sock.settimeout(3)
    sizes, start = [], time.perf_counter()
    received = b""
    while not received.endswith(b"\n"):
        chunk = siggen.sock.recv(1024)
        sizes.append(len(chunk))
        received += chunk
    assert max(sizes) <= 9 and len(sizes) >= 5                  # 3-byte chunks (a slow reader may merge a few)
    assert time.perf_counter() - start >= 0.15


def test_nan_and_inf_replace_numeric_responses(analyzer, siggen):
    siggen.send("MF:FAULT:NAN 1")
    assert siggen.query("*IDN?").startswith("MeasureFlow")      # not numeric: not consumed
    assert siggen.query("MF:FAULT?").startswith("TIMEOUT=0,DISCONNECT=0,GARBAGE=0,FRAGMENT=0,NAN=1")
    assert siggen.query("SOUR:FREQ?") == "NAN"
    assert siggen.query("SOUR:FREQ?") == "1000"
    analyzer.send("MF:FAULT:INF 2")
    assert analyzer.query("MEAS:RMS?") == "INF"
    assert analyzer.query("*OPC?") == "INF"
    assert analyzer.query("MEAS:RMS?") != "INF"
    analyzer.send("MF:FAULT:NAN 1", "MF:FAULT:INF 1")
    assert [analyzer.query("*OPC?"), analyzer.query("*OPC?")] == ["NAN", "INF"]


def test_oversize_response_exceeds_two_mebibytes(siggen):
    siggen.send("MF:FAULT:OVERSIZE 1")
    siggen.sock.sendall(b"SOUR:FREQ?\n")
    siggen.sock.settimeout(10)
    data = b""
    while not data.endswith(b"\n"):
        data += siggen.sock.recv(1 << 20)
    assert len(data) > 2 * 1024 * 1024
    assert len(data) == OVERSIZE_BYTES + 1
    assert data.startswith(b"1000 ") and data.strip() == b"1000"       # valid payload, just padded
    assert siggen.query("SOUR:FREQ?") == "1000"


def test_client_may_abandon_an_oversize_response(sim, make_client):
    c = make_client("siggen")
    c.send("MF:FAULT:OVERSIZE 1")
    c.sock.sendall(b"SOUR:FREQ?\n")
    c.sock.settimeout(5)
    c.sock.recv(1024)
    c.close()
    assert make_client("siggen").query("SOUR:FREQ?") == "1000"          # server unharmed


def test_response_faults_combine_in_priority_order(siggen):
    siggen.send("MF:FAULT:GARBAGE 1", "MF:FAULT:NAN 1", "MF:FAULT:FRAGMENT 1,8,1")
    assert siggen.query("SOUR:FREQ?") == GARBAGE_TEXT          # GARBAGE wins, FRAGMENT applies to it as well
    assert siggen.query("SOUR:FREQ?") == "NAN"
    assert siggen.query("MF:FAULT?") == CLEAN


def test_fault_commands_are_never_faulted_and_never_consume(siggen):
    siggen.send("MF:FAULT:DISCONNECT 3", "MF:FAULT:TIMEOUT 3,5000", "MF:FAULT:GARBAGE 3")
    assert siggen.query("MF:FAULT?") == "TIMEOUT=3,DISCONNECT=3,GARBAGE=3,FRAGMENT=0,NAN=0,INF=0,OVERSIZE=0"
    siggen.send("MF:FAULT:CLEAR")
    assert siggen.query("MF:FAULT?") == CLEAN


def test_faults_are_per_server_and_shared_between_connections(sim, make_client):
    a1, a2 = make_client("analyzer"), make_client("analyzer")
    a1.send("MF:FAULT:GARBAGE 1")
    assert a1.query("MF:FAULT?").startswith("TIMEOUT=0,DISCONNECT=0,GARBAGE=1")     # armed (also orders the commands)
    assert make_client("siggen").query("*IDN?").startswith("MeasureFlow")        # other server unaffected
    assert make_client("dut").query("MF:FAULT?") == CLEAN
    assert a2.query("*OPC?") == GARBAGE_TEXT                                     # other connection, same server
    assert a1.query("*OPC?") == "1"


def test_rst_clears_injections(siggen):
    siggen.send("MF:FAULT:GARBAGE 5", "MF:FAULT:NAN 2", "*RST")
    assert siggen.query("MF:FAULT?") == CLEAN
    assert siggen.query("SOUR:FREQ?") == "1000"


def test_unparsable_lines_do_not_consume_counters(siggen):
    siggen.send("MF:FAULT:GARBAGE 1", "@@@@", "SOUR:FREQ 1e9")
    assert siggen.query("MF:FAULT?") == CLEAN.replace("GARBAGE=0", "GARBAGE=1")
    assert siggen.query("SOUR:FREQ?") == GARBAGE_TEXT


def test_fault_argument_validation(siggen):
    for line in ("MF:FAULT:TIMEOUT abc", "MF:FAULT:TIMEOUT -1", "MF:FAULT:TIMEOUT 1,-5", "MF:FAULT:TIMEOUT 1,2,3",
                 "MF:FAULT:TIMEOUT", "MF:FAULT:FRAGMENT 1,0", "MF:FAULT:FRAGMENT 1,2,-1", "MF:FAULT:FRAGMENT 1,2,3,4",
                 "MF:FAULT:NAN 1.5", "MF:FAULT:INF 1000001", "MF:FAULT:CLEAR 1", "MF:FAULT:BOGUS 1", "MF:FAULT? 1"):
        siggen.send(line)
    codes = [entry.split(",")[0] for entry in siggen.drain_errors()]
    assert codes == ["-104", "-222", "-222", "-102", "-102", "-222", "-222", "-102", "-222", "-222", "-102", "-113",
                     "-102"]
    assert siggen.query("MF:FAULT?") == CLEAN


def test_zero_count_disarms(siggen):
    siggen.send("MF:FAULT:GARBAGE 4", "MF:FAULT:GARBAGE 0")
    assert siggen.query("SOUR:FREQ?") == "1000"


def test_fault_injector_unit():
    injector = FaultInjector()
    injector.arm("FRAGMENT", 2, chunk=5, chunk_delay_ms=7.0)
    first = injector.on_response("hello")
    assert (first.text, first.chunk_size, first.chunk_delay_s) == ("hello", 5, 0.007)
    injector.arm("FRAGMENT", 1)                                  # defaults when no timing is given
    assert (injector.on_response("x").chunk_size, injector.on_response("x").chunk_size) == (3, 0)
    injector.arm("TIMEOUT", 1, timeout_ms=1.0)
    assert injector.on_command().delay_s == 0.001
    injector.arm("OVERSIZE", 1)
    assert len(injector.on_response("a b").text) == OVERSIZE_BYTES
    injector.arm("NAN", 1)
    assert injector.on_response("not numeric").text == "not numeric"
    assert injector.on_response("-1.5e-3").text == "NAN"
    injector.arm("DISCONNECT", 1)
    assert injector.on_command().disconnect and not injector.on_command().disconnect
