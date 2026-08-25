"""Experiment A: substitute physical capacity between execution and data.

A slot divides a fixed time budget between propagating the payload and
executing it, so the two hard limits are not independent design choices.  More
propagation time buys a larger payload, hence a larger data limit, and costs
execution time, hence a smaller execution limit.

This sweep is parameterised by the limit pair ``(L_E, L_D)`` directly rather
than by propagation time.  The propagation model is uncertain -- the notebook's
own candidates span 29M to 90M data gas for a three-second window depending on
the fit and safety factor -- and it is cheap to evaluate.  Keeping it out of the
simulation means a change of fit redraws a frontier line over these results
instead of requiring a re-run, and it lets the question be asked in reverse:
what data limit would a given design need, and what propagation time is that?

Two conventions differ from ``run_design_surface.py``:

* ``L_E`` is one physical value per scenario, shared by every execution-target
  row.  The design surface used ``L_E = 2 T_E``, which is a target-ratio
  convention rather than a physical constraint and would confound this
  experiment.
* The absolute target grid is held fixed across scenarios, so the treatment is
  the limit pair alone.  Cells whose target exceeds its own limit are dropped.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dynamics.batched_replay import BatchConfig, run_batch  # noqa: E402
from run_multiscale_design_surface import build_canonical_workload  # noqa: E402
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}
REPORT_SHOCK_SEED = 20260814

# Physical capacity scenarios.  Execution limits span 4.5s-6.5s of execution
# time at 100M gas/s; data limits span the propagation candidates over roughly
# 2.5s-4.5s under the empirical fit, and cover the conservative fit's range at
# longer windows.
EXECUTION_LIMITS = np.array([450, 500, 550, 600, 650]) * 1e6
DATA_LIMITS = np.array([60, 75, 90, 105, 120, 135]) * 1e6

# Absolute targets, held fixed across every scenario.
EXECUTION_TARGETS = np.array([150, 175, 200, 225, 250, 275, 300]) * 1e6
DATA_TARGETS = np.array([22.5, 36, 45, 52.5, 60, 67.5, 77, 80, 90, 100, 110]) * 1e6


def add_interval(row: dict, name: str, values: np.ndarray) -> None:
    values = np.asarray(values, dtype=float)
    row[name] = float(values.mean())
    row[f"{name}_p05"] = float(np.quantile(values, 0.05))
    row[f"{name}_p95"] = float(np.quantile(values, 0.95))


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]

    shocks = build_canonical_workload().paths

    rows: list[dict] = []
    started = time.time()
    for execution_limit in EXECUTION_LIMITS:
        for data_limit in DATA_LIMITS:
            grid = [
                (te, td)
                for te in EXECUTION_TARGETS if te < execution_limit
                for td in DATA_TARGETS if td < data_limit
            ]
            if not grid:
                continue
            n = len(grid)
            repeat = lambda values: np.repeat(np.asarray(values, dtype=float), N_SEEDS)
            ones = np.ones(n * N_SEEDS)
            cfg = BatchConfig(
                execution_target=repeat([g[0] for g in grid]),
                execution_limit=ones * execution_limit,
                data_target=repeat([g[1] for g in grid]),
                data_limit=ones * data_limit,
                state_target=ones * STATE_TARGET,
                eps_execution=ones * EPS["execution"], eps_data=ones * EPS["data"],
                eps_state=ones * EPS["state"],
                w_execution=ones * float(demand.w_execution_reference),
                w_state=ones * float(demand.w_state_reference), rho_A=ones,
                m_execution=float(demand.m_execution), m_state=float(demand.m_state),
                m_data_static=float(anchor.static_data_metering_multiplier),
                q_execution_0=float(demand.q_execution_per_block),
                q_state_0=float(demand.q_state_per_block),
                g_static_0=float(anchor.static_data_gas_per_block),
                p0_gwei=float(demand.base_fee_ref_gwei),
            )
            out = run_batch(
                cfg, shocks, bundle_cost_equivalent_start(cfg), burn_in=BURN_IN,
                bundle_consistent=True,
            )
            for i, (execution_target, data_target) in enumerate(grid):
                sl = slice(i * N_SEEDS, (i + 1) * N_SEEDS)
                execution_used = out["mean_used"][sl, 0]
                execution_rationed = out["mean_rationed"][sl, 0]
                # Offered execution labels which arm of the fee-floor U a cell
                # sits on: below one, demand is inadequate and a larger data
                # limit will not help; at or above one, the shortfall is bundle
                # exclusion and more data headroom should relieve it.
                adequacy = (execution_used + execution_rationed) / execution_target
                row = {
                    "execution_limit": float(execution_limit),
                    "data_limit": float(data_limit),
                    "execution_target": float(execution_target),
                    "data_target": float(data_target),
                    "execution_target_ratio": execution_target / execution_limit,
                    "data_target_ratio": data_target / data_limit,
                }
                add_interval(row, "included_execution", execution_used)
                add_interval(row, "execution_fill", execution_used / execution_target)
                add_interval(row, "execution_adequacy", adequacy)
                add_interval(row, "rationed_execution", execution_rationed)
                add_interval(row, "rationed_data", out["mean_rationed"][sl, 1])
                add_interval(row, "data_limit_hit_fraction",
                             out["included_limit_fraction"][sl, 1])
                add_interval(row, "execution_limit_hit_fraction",
                             out["included_limit_fraction"][sl, 0])
                add_interval(row, "data_offered_limit_pressure_fraction",
                             out["offered_limit_pressure_fraction"][sl, 1])
                add_interval(row, "execution_offered_limit_pressure_fraction",
                             out["offered_limit_pressure_fraction"][sl, 0])
                add_interval(row, "data_scale_determining_fraction",
                             out["scale_determining_fraction"][sl, 1])
                add_interval(row, "execution_scale_determining_fraction",
                             out["scale_determining_fraction"][sl, 0])
                add_interval(row, "execution_floor_fraction", out["floor_fraction"][sl, 0])
                add_interval(row, "execution_floor_bounded_fraction",
                             out["floor_downward_pressure_fraction"][sl, 0])
                add_interval(row, "longest_data_limit_run",
                             out["longest_limit_run"][sl, 1])
                add_interval(row, "data_fee_sd", out["log_return_sd"][sl, 1])
                add_interval(row, "execution_price_sd",
                             out["effective_price_log_return_sd"][sl, 0])
                rows.append(row)
            print(f"  L_E {execution_limit/1e6:>5.0f}M  L_D {data_limit/1e6:>5.0f}M"
                  f"  -> {n:>3} cells   [{time.time()-started:6.1f}s]", flush=True)

    results = pd.DataFrame(rows)
    out_path = ROOT / "data/7999/physical_limit_substitution.csv"
    results.to_csv(out_path, index=False)
    print(f"\n{len(results)} rows -> {out_path.relative_to(ROOT)}"
          f"   ({time.time()-started:.0f}s total)")


if __name__ == "__main__":
    main()
