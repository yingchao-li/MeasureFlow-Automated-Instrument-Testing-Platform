"""E10 - End-to-end pipeline: health -> connect -> full_pipeline -> reports -> summary -> backend restart -> history retained."""
from __future__ import annotations

import csv
import io
import time
from typing import Any

from common import Ctx, timed


def run(ctx: Ctx) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None, ms: float | None = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "duration_ms": ms})
        ctx.log(f"{'PASS' if ok else 'FAIL'} {name} {detail if detail is not None else ''}")

    with ctx.stack() as st:
        ctx.write_config({"flow": ["health", "environment", "connect all", "sequences", "full_pipeline NORMAL/1.0.0", "run detail", "csv/html/pdf reports",
                                   "summary consistency", "restart backend", "history + reports retained"], "versions": st.versions()})
        h, ms = timed(st.api_json, "GET", "/api/health")
        check("health reachable", h["status"] in ("ok", "degraded"), h["status"], ms)
        env, ms = timed(st.api_json, "GET", "/api/environment")
        check("environment report", bool(env["calibration"]) and "software" in env, {"calibration": [c["status"] for c in env["calibration"]]}, ms)
        ins, ms = timed(st.connect_all)
        check("connect all instruments", all(i["state"] == "connected" for i in ins), [i["id"] for i in ins], ms)
        seqs = st.api_json("GET", "/api/sequences")["sequences"]
        check("7 sequences listed", len(seqs) == 7, [s["id"] for s in seqs])
        run, ms = timed(st.run_sequence, "full_pipeline", label="e10")
        check("full_pipeline PASS", run["status"] == "PASS", {"status": run["status"], "counts": run["counts"]}, ms)
        check("13 tasks, sequential unique ids", len(run["tasks"]) == 13 and len({t["task_id"] for t in run["tasks"]}) == 13)
        rid = run["run_id"]
        csv_r = st.get(f"/api/reports/{rid}.csv")
        rows = list(csv.DictReader(io.StringIO(csv_r.text)))
        check("CSV report rows == tasks", csv_r.status_code == 200 and len(rows) == len(run["tasks"]), {"rows": len(rows)})
        html_r = st.get(f"/api/reports/{rid}.html")
        check("HTML report contains run id", html_r.status_code == 200 and rid in html_r.text, {"bytes": len(html_r.content)})
        pdf_r = st.get(f"/api/reports/{rid}.pdf")
        pdf_ok, pages, has_id = False, 0, False
        try:
            import pypdf
            rd = pypdf.PdfReader(io.BytesIO(pdf_r.content))
            pages = len(rd.pages)
            has_id = rid in "".join(p.extract_text() or "" for p in rd.pages)
            pdf_ok = pdf_r.content.startswith(b"%PDF") and pages >= 1
        except Exception as exc:  # noqa: BLE001
            ctx.log(f"pdf parse failed: {exc}")
        check("PDF report parses and contains run id", pdf_ok and has_id, {"pages": pages, "bytes": len(pdf_r.content)})
        summ = st.api_json("GET", "/api/reports/summary")
        res = st.all_results()
        check("summary consistent with results", summ["tasks"]["total"] == len(res) == 13, {"summary_tasks": summ["tasks"]["total"], "results": len(res)})
        t0 = time.perf_counter()
        st.restart_backend()
        st.connect_all()
        ms = (time.perf_counter() - t0) * 1000
        runs_after = st.all_runs()
        check("history retained after backend restart", any(r["run_id"] == rid for r in runs_after), {"runs": len(runs_after)}, ms)
        check("report still downloadable after restart", st.get(f"/api/reports/{rid}.csv").status_code == 200)
        run2 = st.run_sequence("full_pipeline", dut={"profile": "LOWGAIN", "firmware": "1.0.0"})
        check("post-restart run on faulty DUT is FAIL (not ERROR)", run2["status"] == "FAIL", {"status": run2["status"], "counts": run2["counts"]})
    ctx.write_raw_json(checks)
    ok = sum(c["ok"] for c in checks)
    m = {"checks": len(checks), "passed": ok, "failed": [c["check"] for c in checks if not c["ok"]], "all_passed": ok == len(checks),
         "pipeline_run_duration_ms": next((c["duration_ms"] for c in checks if c["check"] == "full_pipeline PASS"), None), "checklist": checks}
    for c in checks:
        if not c["ok"]:
            ctx.defect("high", f"E10 check failed: {c['check']}", str(c["detail"]))
    ctx.write_metrics(m)
    return {"passed": ok, "total": len(checks)}
