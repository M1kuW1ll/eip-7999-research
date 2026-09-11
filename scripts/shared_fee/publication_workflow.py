"""Execution and display helpers for the four one-dimensional report notebooks.

Model equations and simulation kernels remain in the existing shared_fee modules.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/shared_fee"
REPORT = ROOT / "markdowns/eip8279_floor_calibration_report.md"
LABELS = {
    "proposal_faithful": "Baseline",
    "fully_optimized": "Floor-adjusted + EIP-8368",
    "normalized_state": "Floor-adjusted + EIP-8372",
    "balanced": "EIP-7999: historically anchored",
    "maximum": "EIP-7999: maximum-throughput",
}


def require_files(paths):
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing inputs or outputs:\n  " + "\n  ".join(missing)
            + "\nSee notebooks/one_dimensional_simulation/README.md for the "
            "upstream sequence and Xatu/RPC pull commands."
        )


def run_stage(script, *args, outputs=(), reuse=False):
    """Run a repository script, or explicitly verify its cached outputs."""
    paths = [DATA / name for name in outputs]
    if reuse:
        require_files(paths)
        print(f"Using existing outputs: {script}")
        return
    command = [sys.executable, str(ROOT / "scripts/shared_fee" / script), *map(str, args)]
    print("Running", script, *map(str, args), flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "scripts")])
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    require_files(paths)


def read_table(name):
    path = DATA / name
    require_files([path])
    return pd.read_csv(path)


def source_snapshot():
    """Record the existing upstream calibration and EIP-7999 result bytes."""
    paths = [p for folder in (ROOT / "data/7999", ROOT / "data/glamsterdam")
             for p in folder.glob("*.csv")]
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify_sources(snapshot):
    changed = [str(p.relative_to(ROOT)) for p, digest in snapshot.items()
               if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest]
    if changed:
        raise AssertionError(f"Upstream files changed during notebook execution: {changed}")
    print(f"Verified {len(snapshot)} upstream calibration and EIP-7999 tables.")


def baseline_anchor():
    """Select F=64 even after the sweep replaces the generic anchor with F=96."""
    base = read_table("equilibrium_anchor_8279.csv").iloc[0]
    if int(base.get("floor_rate", 64)) != 64:
        per_rate = read_table("equilibrium_anchor_by_floor_rate.csv")
        rows = per_rate[per_rate.floor_rate.eq(64)]
        if len(rows) != 1:
            raise ValueError("Expected exactly one 64-gas baseline calibration")
        base = rows.iloc[0]
    return base


def shared_display(frame):
    """Use the report's units while retaining source precision in the CSVs."""
    result = pd.DataFrame({
        "Propagation (s)": frame.propagation_time_s,
        "Target (M)": frame.shared_target / 1e6,
        "Limit (M)": frame.shared_limit / 1e6,
        "Equilibrium fee (wei)": frame.equilibrium_fee_wei,
        "Execution (M)": frame.included_execution_metered / 1e6,
        "Data/floor (M)": frame.included_data_metered / 1e6,
        "State (M)": frame.included_state_metered / 1e6,
        "State growth (GiB/year)": frame.annualized_state_growth_gib,
        "At limit (%)": 100 * frame.shared_limit_hit_fraction,
        "Fee variation": frame.shared_fee_log_return_sd,
        "State as bottleneck (%)": 100 * (1 - frame.regular_binding_fraction),
    })
    return result.reset_index(drop=True)
