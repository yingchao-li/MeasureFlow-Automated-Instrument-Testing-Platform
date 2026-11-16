"""E05 - Disconnection & recovery.

A) transient disconnect: ``MF:FAULT:DISCONNECT 1`` (the simulator closes the socket without executing the command)
   is injected before the n-th occurrence of a command, on each instrument, during ``full_pipeline``.
   Expectation (independent of the outcome): the client reconnects and retries the idempotent command -> run PASS.
B) persistent disconnect: ``MF:FAULT:DISCONNECT 50`` -> reconnects keep failing -> run ERROR (never FAIL).
C) hard kill of the simulator process in the middle of a run, then restart: the backend must report ERROR, stay
   healthy and reconnect through the API; the next run must PASS.
"""
from __future__ import annotations

import time
from typing import Any

from common import Ctx, rate, summarize

POINTS = [("siggen", r"^SOUR:FREQ"), ("siggen", r"^OUTP ON"), ("analyzer", r"^MF:ACQ:INIT"),
          ("analyzer", r"^MEAS:"), ("dut", r"^MF:DUT:PROF")]
NTH = [1, 2, 3]


def run(ctx: Ctx) -> dict[str, Any]:
    nths = [1] if ctx.quick else NTH
    rows: list[dict[str, Any]] = []
    kill: dict[str, Any] = {}
    with ctx.stack(with_proxy=True) as st:
        ctx.write_config({"sequence": "full_pipeline (NORMAL, 1.0.0)", "task_retries": 2, "points": [[i, p] for i, p in POINTS],
                          "nth_occurrence": nths, "persistent_fault": "MF:FAULT:DISCONNECT 50",
                          "expectation": {"transient": "PASS", "persistent": "ERROR (never FAIL)", "kill_restart": "ERROR, then PASS after restart"},
                          "versions": st.versions()})
        for mode, inject in (("transient", "MF:FAULT:DISCONNECT 1"), ("persistent", "MF:FAULT:DISCONNECT 50")):
            for inst, rx in POINTS:
                for n in (nths if mode == "transient" else [1]):
                    st.proxy.reset()
                    st.proxy.arm(inst, inject, match=rx, nth=n, times=1)
                    t0 = time.perf_counter()
                    r = st.run_sequence("full_pipeline", retries=2, timeout=90)
                    wall = (time.perf_counter() - t0) * 1000
                    codes = sorted({t["error_code"] for t in r["tasks"] if t["status"] == "ERROR"} - {None})
                    rows.append({"mode": mode, "instrument": inst, "match": rx, "nth": n, "expected": "PASS" if mode == "transient" else "ERROR",
                                 "status": r["status"], "fail_tasks": sum(1 for t in r["tasks"] if t["status"] == "FAIL"),
                                 "error_codes": codes, "tasks": len(r["tasks"]), "wall_ms": wall,
                                 "max_attempts": max((t["attempts"] for t in r["tasks"]), default=0),
                                 "injected": r["status"] is not None and any(e.injected for e in st.proxy.trace(inst))})
                    ctx.log(f"{mode} {inst} {rx} nth={n}: {r['status']} {codes}")
                    st.ensure_idle()
                    st.reset_simulator_state()
                    st.disconnect_all(); st.connect_all()
        # ---- C) hard kill mid-run
        st.proxy.reset()
        st.proxy.arm("analyzer", [], match=r"^MEAS:THD\?", nth=1, times=1, action=st.kill_simulator)
        r = st.run_sequence("full_pipeline", retries=1, timeout=90)
        kill["run_status"] = r["status"]
        kill["error_codes"] = sorted({t["error_code"] for t in r["tasks"] if t["status"] == "ERROR"} - {None})
        h = st.get("/api/health")
        kill["health_http"] = h.status_code
        kill["health_status_after_kill"] = h.json().get("status")
        t0 = time.perf_counter()
        st.proxy.reset()
        st.restart_simulator()
        st.connect_all()
        r2 = st.run_sequence("full_pipeline", retries=1, timeout=90)
        kill["recovery_ms"] = (time.perf_counter() - t0) * 1000
        kill["next_run_status"] = r2["status"]
        kill["instruments_connected_after"] = sum(1 for i in st.instruments().values() if i["state"] == "connected")
    ctx.write_raw_json({"cases": rows, "kill_restart": kill})

    tr = [r for r in rows if r["mode"] == "transient"]
    pe = [r for r in rows if r["mode"] == "persistent"]
    m: dict[str, Any] = {
        "transient": {"n": len(tr), "recovered_pass_rate": rate(sum(1 for r in tr if r["status"] == "PASS"), len(tr)),
                      "wall_ms": summarize(r["wall_ms"] for r in tr)},
        "persistent": {"n": len(pe), "error_rate": rate(sum(1 for r in pe if r["status"] == "ERROR"), len(pe)),
                       "wall_ms": summarize(r["wall_ms"] for r in pe),
                       "error_codes_seen": sorted({c for r in pe for c in r["error_codes"]})},
        "unexpected_fail_tasks": sum(r["fail_tasks"] for r in rows),
        "kill_restart": kill,
        "overall_recovery_rate": rate(sum(1 for r in tr if r["status"] == "PASS") + int(kill.get("next_run_status") == "PASS"), len(tr) + 1),
    }
    if m["unexpected_fail_tasks"]:
        ctx.defect("high", "disconnect reported as FAIL", f"{m['unexpected_fail_tasks']} FAIL tasks")
    ctx.write_metrics(m)
    return {"transient_recovered": m["transient"]["recovered_pass_rate"], "persistent_error": m["persistent"]["error_rate"],
            "kill_next_run": kill.get("next_run_status")}
