"""Shared infrastructure for experiments E01-E10.

Every experiment writes into ``<out>/E0x_<slug>/``:

* ``config.json``  - all parameters, seeds, thresholds, assumptions, component versions
* ``log.txt``      - timestamped log of what was done
* ``raw.json`` / ``raw.csv`` - every individual observation
* ``metrics.json`` - computed *from the raw observations by code* (never hand-entered)

Statistics helpers live here so every experiment computes mean/std/percentiles identically.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import Stack  # noqa: E402

ALL = ("siggen", "analyzer", "dut")


# ----------------------------------------------------------------------------------------------- statistics
def pct(values: list[float], q: float) -> Optional[float]:
    """Percentile with linear interpolation (q in [0, 100]); ``None`` for an empty sample."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(values: Iterable[float]) -> dict[str, Any]:
    """n / mean / sample-std / min / p50 / p95 / p99 / max of a sample."""
    v = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not v:
        return {"n": 0, "mean": None, "std": None, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    return {"n": len(v), "mean": statistics.fmean(v), "std": statistics.stdev(v) if len(v) > 1 else 0.0,
            "min": min(v), "p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99), "max": max(v)}


def rate(num: int, den: int) -> Optional[float]:
    return None if den == 0 else num / den


def error_stats(errors: list[float]) -> dict[str, Any]:
    """Bias (mean signed error), MAE, max |error|, RMS error."""
    e = [x for x in errors if x is not None and math.isfinite(x)]
    if not e:
        return {"n": 0, "bias": None, "mae": None, "max_abs": None, "rmse": None, "std": None}
    return {"n": len(e), "bias": statistics.fmean(e), "mae": statistics.fmean(abs(x) for x in e),
            "max_abs": max(abs(x) for x in e), "rmse": math.sqrt(statistics.fmean(x * x for x in e)),
            "std": statistics.stdev(e) if len(e) > 1 else 0.0}


# ----------------------------------------------------------------------------------------------- context
@dataclass
class Ctx:
    """Everything an experiment needs; also owns its output files."""

    eid: str
    slug: str
    root: Path
    backend: Path
    seed: int
    out_root: Path
    quick: bool = False
    t0: float = field(default_factory=time.time)
    defects: list[dict[str, Any]] = field(default_factory=list)
    _logf: Any = None

    @property
    def dir(self) -> Path:
        d = self.out_root / f"{self.eid}_{self.slug}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(f"{self.eid} {line}", flush=True)
        if self._logf is None:
            self._logf = open(self.dir / "log.txt", "w", buffering=1)
        self._logf.write(line + "\n")

    def close(self) -> None:
        if self._logf:
            self._logf.close()
            self._logf = None

    def stack(self, **kw: Any) -> Stack:
        """A private stack (use as a context manager). Seed defaults to the experiment seed."""
        kw.setdefault("seed", self.seed)
        kw.setdefault("name", f"{self.eid.lower()}")
        return Stack(self.root, self.backend, **kw)

    def versions(self, st: Stack) -> dict[str, Any]:
        return st.versions()

    def defect(self, severity: str, title: str, detail: str) -> None:
        self.defects.append({"experiment": self.eid, "severity": severity, "title": title, "detail": detail})
        self.log(f"DEFECT [{severity}] {title}: {detail}")

    # -- writers ------------------------------------------------------------------------------------
    def write_config(self, cfg: dict[str, Any]) -> None:
        cfg = {"experiment": self.eid, "slug": self.slug, "base_seed": self.seed, "quick_mode": self.quick, **cfg}
        (self.dir / "config.json").write_text(json.dumps(cfg, indent=2, default=str) + "\n")

    def write_raw_json(self, raw: Any) -> None:
        (self.dir / "raw.json").write_text(json.dumps(raw, indent=1, default=str) + "\n")

    def write_raw_csv(self, rows: list[dict[str, Any]]) -> None:
        keys: list[str] = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(self.dir / "raw.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        metrics = {**metrics, "defects_observed": self.defects, "duration_s": round(time.time() - self.t0, 2)}
        (self.dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")


# ----------------------------------------------------------------------------------------------- helpers
def timed(fn: Callable[..., Any], *a: Any, **kw: Any) -> tuple[Any, float]:
    t0 = time.perf_counter()
    r = fn(*a, **kw)
    return r, (time.perf_counter() - t0) * 1000.0


def run_and_time(st: Stack, seq: str, **kw: Any) -> tuple[dict[str, Any], float]:
    """Start a run and wait for it; returns (run detail, wall time in ms as seen by the client)."""
    t0 = time.perf_counter()
    run = st.run_sequence(seq, **kw)
    return run, (time.perf_counter() - t0) * 1000.0


def safe_run(fn: Callable[[Ctx], dict[str, Any]], ctx: Ctx) -> dict[str, Any]:
    """Run an experiment function, converting a crash into a recorded failure (never silently swallowed)."""
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        ctx.log("EXPERIMENT CRASHED:\n" + tb)
        ctx.defect("high", f"{ctx.eid} aborted", f"{type(exc).__name__}: {exc}")
        ctx.write_metrics({"crashed": True, "error": f"{type(exc).__name__}: {exc}", "traceback": tb})
        return {"crashed": True, "error": str(exc)}
    finally:
        ctx.close()


def outcome_class(expected: str, actual: str, injected: bool, border: bool = False) -> str:
    """Classify one task outcome.

    * ``pass``                      expected PASS, got PASS
    * ``expected_measurement_fail`` expected FAIL (DUT really out of spec, analytic), got FAIL
    * ``expected_injected_fault``   a fault was injected, expected ERROR, got ERROR
    * ``unexpected_software_error`` ERROR without an injected cause (must be 0)
    * ``false_pass`` / ``false_fail`` verdict disagrees with the analytic expectation
    * ``missed_fault``              fault injected and expected ERROR but the task did not ERROR
    * ``borderline``                expectation within the measurement uncertainty of a limit (not judged)
    * ``other_mismatch``            anything else (e.g. CANCELLED)
    """
    if border and not injected:
        return "borderline"
    if injected:
        if expected == "ERROR" and actual == "ERROR":
            return "expected_injected_fault"
        if expected == "ERROR":
            return "missed_fault"
        # fault injected but the plan expects recovery
        if actual == expected:
            return "pass" if expected == "PASS" else "expected_measurement_fail"
        return "other_mismatch"
    if actual == "ERROR":
        return "unexpected_software_error"
    if expected == actual:
        return "pass" if actual == "PASS" else "expected_measurement_fail"
    if expected == "FAIL" and actual == "PASS":
        return "false_pass"
    if expected == "PASS" and actual == "FAIL":
        return "false_fail"
    return "other_mismatch"
