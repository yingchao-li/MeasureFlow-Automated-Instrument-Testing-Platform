"""E01 - Instrument communication: connect/disconnect, *IDN? x N per instrument (REST and raw TCP),
IDN validation, error-queue behaviour, reconnect cycles."""
from __future__ import annotations

import re
import time
from typing import Any

from common import ALL, Ctx, pct, rate, summarize
from stack import ScpiClient

EXPECTED_IDN = {"siggen": ("VSG-1000", "SN-SIM-0001", "1.0.0"), "analyzer": ("VAA-2000", "SN-SIM-0002", "1.0.0"),
                "dut": ("VDUT-HA1", "SN-SIM-0003", "1.0.0")}


def idn_valid(inst: str, text: str | None) -> bool:
    if not text:
        return False
    model, serial, fw = EXPECTED_IDN[inst]
    return re.fullmatch(rf"MeasureFlow,{re.escape(model)},{re.escape(serial)},{re.escape(fw)}", text) is not None


def run(ctx: Ctx) -> dict[str, Any]:
    n_idn = 20 if ctx.quick else 200
    n_cycles = 3 if ctx.quick else 20
    n_fresh = 10 if ctx.quick else 50
    raw: dict[str, list[dict[str, Any]]] = {"rest_connect": [], "rest_idn": [], "tcp_idn": [], "tcp_fresh": [],
                                              "error_queue": [], "reconnect": []}
    with ctx.stack() as st:
        cfg = {"idn_queries_per_instrument": n_idn, "fresh_connection_queries": n_fresh, "reconnect_cycles": n_cycles,
               "instrument_config_defaults": "configs/instruments.json (timeouts 1000/2000/1000 ms, max_retries 2)",
               "assumptions": ["latency is wall time seen by the Python client on loopback (includes HTTP for REST)",
                               "no fault injection active"], "stack": st.describe(), "versions": st.versions()}
        ctx.write_config(cfg)

        # 1. connect / disconnect individually via REST
        ctx.log("connect/disconnect each instrument via REST")
        for iid in ALL:
            t0 = time.perf_counter()
            out = st.api("POST", "/api/instruments/connect", {"id": iid})
            ms = (time.perf_counter() - t0) * 1000
            inst = out.json()["instruments"][0] if out.status_code == 200 else {}
            raw["rest_connect"].append({"id": iid, "op": "connect", "http": out.status_code, "ms": ms,
                                        "state": inst.get("state"), "idn_ok": idn_valid(iid, inst.get("idn")),
                                        "firmware": inst.get("firmware")})
        for iid in ALL:
            t0 = time.perf_counter()
            out = st.api("POST", "/api/instruments/disconnect", {"id": iid})
            ms = (time.perf_counter() - t0) * 1000
            inst = out.json()["instruments"][0] if out.status_code == 200 else {}
            raw["rest_connect"].append({"id": iid, "op": "disconnect", "http": out.status_code, "ms": ms,
                                        "state": inst.get("state"), "idn_ok": None, "firmware": None})
        st.connect_all()

        # 2. *IDN? x N through the backend
        ctx.log(f"{n_idn} x *IDN? per instrument through /api/instruments/command")
        for iid in ALL:
            for i in range(n_idn):
                t0 = time.perf_counter()
                r = st.api("POST", "/api/instruments/command", {"id": iid, "command": "*IDN?"})
                ms = (time.perf_counter() - t0) * 1000
                body = r.json() if r.status_code == 200 else {}
                raw["rest_idn"].append({"id": iid, "i": i, "http": r.status_code, "ms": ms,
                                        "server_ms": body.get("duration_ms"), "response": body.get("response"),
                                        "ok": r.status_code == 200 and idn_valid(iid, body.get("response")),
                                        "error": body.get("error")})
        # 3. raw TCP, persistent connection and fresh connections
        ctx.log("raw TCP *IDN? (persistent and fresh connections)")
        for iid in ALL:
            with st.scpi_client(iid) as c:
                for i in range(n_idn):
                    t0 = time.perf_counter()
                    try:
                        resp = c.query("*IDN?")
                    except Exception as exc:  # noqa: BLE001
                        resp = f"EXC {exc!r}"
                    raw["tcp_idn"].append({"id": iid, "i": i, "ms": (time.perf_counter() - t0) * 1000, "response": resp,
                                           "ok": idn_valid(iid, resp)})
            for i in range(n_fresh):
                t0 = time.perf_counter()
                try:
                    resp = st.scpi(iid, "*IDN?")
                except Exception as exc:  # noqa: BLE001
                    resp = f"EXC {exc!r}"
                raw["tcp_fresh"].append({"id": iid, "i": i, "ms": (time.perf_counter() - t0) * 1000, "ok": idn_valid(iid, resp)})

        # 4. error queue behaviour
        ctx.log("error-queue behaviour")
        for iid in ALL:
            r = st.command(iid, "BOGUS:CMD 1")
            raw["error_queue"].append({"id": iid, "check": "rest_setter_reports_-113", "ok": bool(r["error"]) and r["error"]["code"] == -113})
            r = st.command(iid, "SYST:ERR?")
            raw["error_queue"].append({"id": iid, "check": "backend_drained_queue", "ok": r["response"] == '0,"No error"', "got": r["response"]})
            with st.scpi_client(iid) as c:
                c.write("*CLS")
                c.write("BOGUS:A"); c.write("BOGUS:B")
                got = [c.query("SYST:ERR?") for _ in range(3)]
                raw["error_queue"].append({"id": iid, "check": "fifo_two_errors_then_empty",
                                           "ok": got[0].startswith("-113,") and got[1].startswith("-113,") and got[2] == '0,"No error"', "got": got})
                c.write("BOGUS:C"); c.write("*CLS")
                got = c.query("SYST:ERR?")
                raw["error_queue"].append({"id": iid, "check": "cls_clears", "ok": got == '0,"No error"', "got": got})
            r = st.command(iid, "*IDN?")
            raw["error_queue"].append({"id": iid, "check": "link_healthy_after_errors", "ok": idn_valid(iid, r["response"])})

        # 5. reconnect cycles
        ctx.log(f"{n_cycles} reconnect cycles")
        fds0 = st.proc_stats()
        for k in range(n_cycles):
            t0 = time.perf_counter()
            out = st.api("POST", "/api/instruments/connect", {"id": "all"})
            c_ms = (time.perf_counter() - t0) * 1000
            insts = out.json().get("instruments", []) if out.status_code == 200 else []
            ok_conn = len(insts) == 3 and all(i["state"] == "connected" and idn_valid(i["id"], i.get("idn")) for i in insts)
            t0 = time.perf_counter()
            out2 = st.api("POST", "/api/instruments/disconnect", {"id": "all"})
            d_ms = (time.perf_counter() - t0) * 1000
            insts2 = out2.json().get("instruments", []) if out2.status_code == 200 else []
            ok_disc = len(insts2) == 3 and all(i["state"] == "disconnected" for i in insts2)
            raw["reconnect"].append({"cycle": k, "connect_ms": c_ms, "disconnect_ms": d_ms, "ok_connect": ok_conn, "ok_disconnect": ok_disc,
                                     "output_off": st.scpi("siggen", "OUTP?") == "0"})
        fds1 = st.proc_stats()
        raw["backend_resources"] = [{"phase": "before_cycles", **fds0}, {"phase": "after_cycles", **fds1}]  # type: ignore[list-item]

    ctx.write_raw_json(raw)

    # ------------------------------------------------------------------ metrics (computed from raw)
    m: dict[str, Any] = {"per_instrument": {}}
    for iid in ALL:
        rest = [r for r in raw["rest_idn"] if r["id"] == iid]
        tcp = [r for r in raw["tcp_idn"] if r["id"] == iid]
        fresh = [r for r in raw["tcp_fresh"] if r["id"] == iid]
        m["per_instrument"][iid] = {
            "rest": {"n": len(rest), "success_rate": rate(sum(r["ok"] for r in rest), len(rest)),
                     "latency_ms": summarize(r["ms"] for r in rest), "server_duration_ms": summarize(r["server_ms"] for r in rest if r["server_ms"] is not None)},
            "tcp_persistent": {"n": len(tcp), "success_rate": rate(sum(r["ok"] for r in tcp), len(tcp)), "latency_ms": summarize(r["ms"] for r in tcp)},
            "tcp_fresh_connection": {"n": len(fresh), "success_rate": rate(sum(r["ok"] for r in fresh), len(fresh)), "latency_ms": summarize(r["ms"] for r in fresh)},
        }
    allrest = raw["rest_idn"]
    alltcp = raw["tcp_idn"]
    m["overall"] = {"rest_queries": len(allrest), "rest_success_rate": rate(sum(r["ok"] for r in allrest), len(allrest)),
                    "tcp_queries": len(alltcp), "tcp_success_rate": rate(sum(r["ok"] for r in alltcp), len(alltcp)),
                    "idn_field_validation_rate": rate(sum(r["ok"] for r in allrest + alltcp), len(allrest + alltcp)),
                    "rest_latency_ms": summarize(r["ms"] for r in allrest), "tcp_latency_ms": summarize(r["ms"] for r in alltcp)}
    rc = raw["rest_connect"]
    m["connect_disconnect"] = {"connect_ms": summarize(r["ms"] for r in rc if r["op"] == "connect"),
                               "disconnect_ms": summarize(r["ms"] for r in rc if r["op"] == "disconnect"),
                               "connect_ok": sum(1 for r in rc if r["op"] == "connect" and r["http"] == 200 and r["state"] == "connected" and r["idn_ok"]),
                               "disconnect_ok": sum(1 for r in rc if r["op"] == "disconnect" and r["http"] == 200 and r["state"] == "disconnected"),
                               "n_each": len(ALL)}
    eq = raw["error_queue"]
    m["error_queue"] = {"checks": len(eq), "passed": sum(r["ok"] for r in eq), "failed": [r for r in eq if not r["ok"]],
                        "pass_rate": rate(sum(r["ok"] for r in eq), len(eq))}
    cyc = raw["reconnect"]
    r0, r1 = raw["backend_resources"][0], raw["backend_resources"][1]  # type: ignore[index]
    m["reconnect_cycles"] = {"cycles": len(cyc), "success_rate": rate(sum(c["ok_connect"] and c["ok_disconnect"] and c["output_off"] for c in cyc), len(cyc)),
                             "connect_ms": summarize(c["connect_ms"] for c in cyc), "disconnect_ms": summarize(c["disconnect_ms"] for c in cyc),
                             "backend_fds_before": r0["fds"], "backend_fds_after": r1["fds"],
                             "backend_threads_before": r0["threads"], "backend_threads_after": r1["threads"],
                             "backend_rss_kb_before": r0["rss_kb"], "backend_rss_kb_after": r1["rss_kb"]}
    bad = [k for k, v in m["per_instrument"].items() if v["rest"]["success_rate"] != 1.0 or v["tcp_persistent"]["success_rate"] != 1.0]
    if bad:
        ctx.defect("medium", "IDN query failures", f"instruments with <100 % *IDN? success: {bad}")
    if m["error_queue"]["failed"]:
        ctx.defect("medium", "error-queue behaviour deviates from contract", str(m["error_queue"]["failed"][:3]))
    if m["reconnect_cycles"]["success_rate"] != 1.0:
        ctx.defect("medium", "reconnect cycle failures", f"success rate {m['reconnect_cycles']['success_rate']}")
    if r0["fds"] is not None and r1["fds"] > r0["fds"] + 3:
        ctx.defect("medium", "fd growth over reconnect cycles", f"{r0['fds']} -> {r1['fds']}")
    ctx.write_metrics(m)
    return {"rest_success": m["overall"]["rest_success_rate"], "tcp_success": m["overall"]["tcp_success_rate"],
            "rest_p95_ms": m["overall"]["rest_latency_ms"]["p95"]}
