#!/usr/bin/env python3
"""Run experiments E01-E10 against private simulator + backend stacks (free ports, temporary roots).

    python3 experiments/run_experiments.py --root . --backend backend/build/measureflow_backend [--only E03,E08] [--seed N] [--out DIR] [--quick]

Each experiment writes ``<out>/E0x_<slug>/{config.json,log.txt,raw.*,metrics.json}``; ``<out>/summary.json`` lists
outcomes and every defect observed. With the default ``--out`` the report ``docs/EXPERIMENT_REPORT.md`` is regenerated from
those files (``make_report.py``) - numbers are never typed by hand.
"""
from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Ctx, safe_run  # noqa: E402

EXPERIMENTS = {
    "E01": ("e01_comm", "communication"), "E02": ("e02_accuracy", "accuracy"), "E03": ("e03_oot", "out_of_tolerance"),
    "E04": ("e04_timeout_retry", "timeout_retry"), "E05": ("e05_disconnect", "disconnect_recovery"), "E06": ("e06_invalid", "invalid_response"),
    "E07": ("e07_firmware", "firmware_regression"), "E08": ("e08_batch", "batch_500"), "E09": ("e09_cancel", "cancellation"),
    "E10": ("e10_pipeline", "end_to_end"),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--backend", default=None)
    ap.add_argument("--only", default="", help="comma separated ids, e.g. E03,E08")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", default=None)
    ap.add_argument("--quick", action="store_true", help="reduced sample sizes (smoke test of the experiment code, not for the report)")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    backend = Path(a.backend).resolve() if a.backend else root / "backend" / "build" / "measureflow_backend"
    if not backend.exists():
        print(f"backend binary not found: {backend}", file=sys.stderr)
        return 2
    default_out = root / "results" / "experiments"
    out = Path(a.out).resolve() if a.out else default_out
    out.mkdir(parents=True, exist_ok=True)
    wanted = [e.strip().upper() for e in a.only.split(",") if e.strip()] or list(EXPERIMENTS)
    unknown = [e for e in wanted if e not in EXPERIMENTS]
    if unknown:
        print(f"unknown experiment(s): {unknown}", file=sys.stderr)
        return 2

    summary: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seed": a.seed, "quick": a.quick,
                     "backend": str(backend), "host": {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine()},
                     "experiments": {}, "defects": []}
    t_all = time.time()
    for eid in wanted:
        mod_name, slug = EXPERIMENTS[eid]
        ctx = Ctx(eid=eid, slug=slug, root=root, backend=backend, seed=a.seed, out_root=out, quick=a.quick)
        print(f"=== {eid} {slug} ===", flush=True)
        t0 = time.time()
        res = safe_run(importlib.import_module(mod_name).run, ctx)
        summary["experiments"][eid] = {"slug": slug, "duration_s": round(time.time() - t0, 1), "headline": res, "crashed": bool(res.get("crashed"))}
        summary["defects"].extend(ctx.defects)
        (out / "summary.json").write_text(json.dumps({**summary, "total_duration_s": round(time.time() - t_all, 1)}, indent=2, default=str) + "\n")
    summary["total_duration_s"] = round(time.time() - t_all, 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    crashed = [e for e, v in summary["experiments"].items() if v["crashed"]]
    print(f"done in {summary['total_duration_s']} s; crashed: {crashed or 'none'}; defects observed: {len(summary['defects'])}")
    if not a.no_report and out == default_out and not a.quick and not a.only:
        import make_report
        make_report.build(out, root / "docs" / "EXPERIMENT_REPORT.md", root / "docs" / "figures")
        print("wrote docs/EXPERIMENT_REPORT.md")
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
