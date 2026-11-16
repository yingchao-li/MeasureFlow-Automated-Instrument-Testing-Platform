"""Golden regression: fresh runs must reproduce ``baseline.json`` (generated from real runs) within the
documented per-kind tolerances (see ``regression_lib``). The comparison function itself is unit-tested
with synthetic drift so the suite cannot silently become vacuous."""
from __future__ import annotations

import copy
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from regression_lib import CASES, SEQUENCE, TOLERANCES, compare_case, summarise_run  # noqa: E402
from stack import Stack  # noqa: E402

BASELINE = HERE / "baseline.json"


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    if not BASELINE.is_file():
        pytest.skip("tests/regression/baseline.json missing - generate it with tests/regression/update_baseline.py")
    return json.loads(BASELINE.read_text())


@pytest.fixture(scope="module")
def seeded_stack(baseline: dict[str, Any], backend_bin: Path, sim_available: None, repo_root: Path):
    st = Stack(repo_root, backend_bin, seed=baseline["simulator_seed"], name="qa-regression")
    st.start()
    try:
        yield st
    finally:
        st.stop()


def fresh(st: Stack, case: dict[str, Any]) -> dict[str, Any]:
    run = st.run_sequence(SEQUENCE, dut={"profile": case["profile"], "firmware": case["firmware"]}, retries=0)
    return summarise_run(run)


def test_baseline_file_is_complete_and_records_versions(baseline: dict[str, Any]) -> None:
    assert set(baseline["cases"]) == {c["key"] for c in CASES}
    for key in ("backend", "simulator", "config_version", "python", "numpy", "scipy"):
        assert baseline["versions"].get(key), f"baseline lacks version of {key}"
    assert baseline["simulator_seed"] == 12345 and baseline["sequence"] == SEQUENCE
    assert baseline["tolerances"] == {k: {"relative": v[0], "absolute": v[1]} for k, v in TOLERANCES.items()}, \
        "tolerances in baseline.json differ from regression_lib.TOLERANCES - regenerate the baseline"
    for key, c in baseline["cases"].items():
        assert len(c["tasks"]) == 13
    assert baseline["cases"]["normal_1.0.0"]["status"] == "PASS"
    for k in ("lowgain_1.0.0", "highthd_1.0.0", "noisy_1.0.0", "clipping_1.0.0", "normal_1.2.0"):
        assert baseline["cases"][k]["status"] == "FAIL", f"{k} baseline must be a FAIL run"
        assert baseline["cases"][k]["counts"]["ERROR"] == 0


@pytest.mark.parametrize("case", CASES, ids=[c["key"] for c in CASES])
def test_fresh_run_matches_baseline_within_tolerance(seeded_stack: Stack, baseline: dict[str, Any], case: dict[str, Any]) -> None:
    diffs = compare_case(baseline["cases"][case["key"]], fresh(seeded_stack, case))
    assert not diffs, "regression vs baseline:\n  " + "\n  ".join(diffs)


def test_versions_match_baseline_or_warn(seeded_stack: Stack, baseline: dict[str, Any]) -> None:
    now = seeded_stack.versions()
    for k in ("backend", "simulator", "config_version"):
        if now.get(k) != baseline["versions"].get(k):
            warnings.warn(f"{k} version {now.get(k)!r} differs from baseline {baseline['versions'].get(k)!r}: regenerate the baseline if intentional")


@pytest.mark.parametrize("key", ["normal_1.0.0", "normal_1.2.0", "noisy_1.0.0"])
def test_different_noise_realisation_is_benign_noise_not_drift(backend_bin: Path, sim_available: None, baseline: dict[str, Any], key: str, repo_root: Path) -> None:
    """A different simulator seed changes every noise realisation; results must stay inside the tolerances."""
    case = next(c for c in CASES if c["key"] == key)
    with Stack(repo_root, backend_bin, seed=baseline["simulator_seed"] + 4242, name="qa-regression-seed") as st:
        diffs = compare_case(baseline["cases"][key], fresh(st, case))
    assert not diffs, "benign noise exceeded the tolerances (tolerance too tight):\n  " + "\n  ".join(diffs)


# ---- the comparison itself (synthetic drift) ------------------------------------------------------------------
def _base(baseline: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(baseline["cases"]["normal_1.0.0"])


def test_comparison_accepts_identical_and_sub_tolerance_changes(baseline: dict[str, Any]) -> None:
    b = _base(baseline)
    assert compare_case(b, copy.deepcopy(b)) == []
    f = copy.deepcopy(b)
    for t in f["tasks"]:
        rel, ab = TOLERANCES[t["kind"]]
        t["value"] += 0.9 * (rel * abs(t["value"]) + ab)
    assert compare_case(b, f) == [], "changes below 90 % of the tolerance must be accepted"


@pytest.mark.parametrize("idx", range(13))
def test_comparison_flags_drift_beyond_tolerance_for_every_task(baseline: dict[str, Any], idx: int) -> None:
    b = _base(baseline)
    f = copy.deepcopy(b)
    t = f["tasks"][idx]
    rel, ab = TOLERANCES[t["kind"]]
    t["value"] += 1.5 * (rel * abs(t["value"]) + ab)
    diffs = compare_case(b, f)
    assert len(diffs) == 1 and t["test_name"] in diffs[0]


def test_comparison_flags_status_code_structure_and_limit_changes(baseline: dict[str, Any]) -> None:
    b = _base(baseline)
    f = copy.deepcopy(b); f["tasks"][2]["status"] = "FAIL"; f["status"] = "FAIL"
    assert any("status" in d for d in compare_case(b, f))
    f = copy.deepcopy(b); f["tasks"][3]["error_code"] = "OUT_OF_TOLERANCE_LOW"
    assert any("error_code" in d for d in compare_case(b, f))
    f = copy.deepcopy(b); f["tasks"].pop()
    assert any("task count" in d for d in compare_case(b, f))
    f = copy.deepcopy(b); f["tasks"][1]["limits"]["max"] += 1
    assert any("limits" in d for d in compare_case(b, f))
    f = copy.deepcopy(b); f["tasks"][0]["test_name"] = "RMS @ 999 Hz"
    assert any("test_name" in d for d in compare_case(b, f))
    f = copy.deepcopy(b); f["tasks"][4]["value"] = None
    assert any("presence" in d for d in compare_case(b, f))
