#!/usr/bin/env bash
# Run experiments E01-E10 against a freshly started simulator + backend on private ports.
# Results (config, raw data, logs, metrics) are written to results/experiments/ and the report
# docs/EXPERIMENT_REPORT.md is regenerated from them.
#   scripts/run_experiments.sh                 # all experiments
#   scripts/run_experiments.sh --only E03,E08  # selection
#   scripts/run_experiments.sh --seed 7        # different (fixed) seed
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$MF_ROOT"
[ -x "$MF_BUILD_DIR/measureflow_backend" ] || die "backend not built — run scripts/build.sh first"
[ -f experiments/run_experiments.py ] || die "experiments/run_experiments.py missing"
py experiments/run_experiments.py --root "$MF_ROOT" --backend "$MF_BUILD_DIR/measureflow_backend" "$@"
