"""E09 - Cancellation & resource cleanup.

Runs of full_pipeline / frequency_sweep are stretched by a fixed per-command latency on the analyzer (proxy) so that
they last ~1-2 s, then cancelled after a seeded random delay. After every cancellation we verify, independently
of the backend's own report: terminal status, generator output OFF (queried directly on the simulator), all
instrument leases released, the next run starts and passes, the run file was persisted as CANCELLED, and at the end that
the backend's thread/fd counts returned to the baseline.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

from common import Ctx, rate, summarize

LATENCY_MS = 12.0
TRIALS = 30


def run(ctx: Ctx) -> dict[str, Any]:
    trials = 8 if ctx.quick else TRIALS
    rng = random.Random(ctx.seed)
    rows: list[dict[str, Any]] = []
    with ctx.stack(with_proxy=True) as st:
        ctx.write_config({"trials": trials, "analyzer_latency_ms": LATENCY_MS, "cancel_delay_s": [0.05, 1.2], "sequences": ["full_pipeline", "frequency_sweep"],
                          "checks": ["terminal status", "OUTP? == 0 (direct)", "leased_by is null for all instruments", "next run PASS", "run.json persisted CANCELLED"],
                          "versions": st.versions()})
        st.connect_all()
        st.run_sequence("gain_verification")                       # warm-up
        base = st.proc_stats()
        for i in range(trials):
            seq = ["full_pipeline", "frequency_sweep"][i % 2]
            delay = rng.uniform(0.05, 1.2)
            st.proxy.set_latency("analyzer", LATENCY_MS)
            run0 = st.start_run(seq, retries=0)
            rid = run0["run_id"]
            time.sleep(delay)
            t0 = time.perf_counter()
            c = st.api("POST", "/api/tests/cancel", {"run_id": rid})
            final = st.wait_run(rid, timeout=30, poll=0.01)
            lat = (time.perf_counter() - t0) * 1000
            st.proxy.set_latency("analyzer", 0)
            out = st.scpi("siggen", "OUTP?")
            leases = {k: v["leased_by"] for k, v in st.instruments().items()}
            persisted = None
            try:
                persisted = json.loads((st.run_dir(rid) / "run.json").read_text())["status"]
            except Exception as exc:  # noqa: BLE001
                persisted = f"unreadable: {exc}"
            nxt = st.run_sequence("gain_verification", timeout=30)
            counts = final["counts"]
            rows.append({"trial": i, "sequence": seq, "cancel_delay_s": delay, "cancel_http": c.status_code, "final_status": final["status"],
                         "finished_before_cancel": c.status_code == 409, "cancel_latency_ms": lat, "output_after": out,
                         "leases_released": all(v is None for v in leases.values()), "next_run": nxt["status"], "persisted_status": persisted,
                         "tasks_done": len(final["tasks"]), "pending_left": counts.get("PENDING", 0) + counts.get("RUNNING", 0)})
            ctx.log(f"trial {i}: {seq} cancel@{delay:.2f}s -> {final['status']} in {lat:.0f} ms")
        time.sleep(0.5)
        end = st.proc_stats()
    ctx.write_raw_csv(rows)
    eff = [r for r in rows if not r["finished_before_cancel"]]
    ok = [r for r in eff if r["final_status"] == "CANCELLED" and r["output_after"] == "0" and r["leases_released"] and r["next_run"] == "PASS" and r["persisted_status"] == "CANCELLED"]
    m = {"trials": len(rows), "effective_cancellations": len(eff), "finished_before_cancel": len(rows) - len(eff),
         "cancelled_status_rate": rate(sum(r["final_status"] == "CANCELLED" for r in eff), len(eff)),
         "cleanup_success_rate": rate(len(ok), len(eff)), "output_off_rate": rate(sum(r["output_after"] == "0" for r in eff), len(eff)),
         "lease_released_rate": rate(sum(r["leases_released"] for r in eff), len(eff)), "next_run_pass_rate": rate(sum(r["next_run"] == "PASS" for r in eff), len(eff)),
         "persisted_cancelled_rate": rate(sum(r["persisted_status"] == "CANCELLED" for r in eff), len(eff)),
         "cancel_latency_ms": summarize(r["cancel_latency_ms"] for r in eff),
         "backend_resources": {"baseline": base, "after": end,
                               "threads_delta": (end.get("threads") or 0) - (base.get("threads") or 0), "fds_delta": (end.get("fds") or 0) - (base.get("fds") or 0)},
         "failures": [r for r in eff if r not in ok][:10]}
    if m["cleanup_success_rate"] != 1.0:
        ctx.defect("high", "cancellation left resources behind", f"cleanup success {m['cleanup_success_rate']}")
    ctx.write_metrics(m)
    return {"cleanup_success": m["cleanup_success_rate"], "latency_p95_ms": m["cancel_latency_ms"]["p95"]}
