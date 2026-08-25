"""Solve both hard limits from one slot-time split, then sweep both targets.

A slot divides a fixed budget between propagating the payload and executing it.
Fixing the propagation time therefore determines both limits at once:

    L_D = DATA_GAS_PER_BYTE * safe_payload_bytes(t_prop, fit, safety)
    L_E = execution_speed * (budget - t_prop)

so the design question becomes "how should the slot be divided" rather than
"which two limits should be chosen".  The absolute target grid is held fixed
across scenarios, so the treatment is the split alone.

Every slot split receives the same full multiscale workload used by the dynamic
report.  The output is descriptive: it retains the complete target surface and
does not impose guardrails or select a preferred design.
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

from bandwidth_limits import EMPIRICAL_P90, safe_payload_bytes  # noqa: E402
from dynamics.batched_replay import BatchConfig, run_batch  # noqa: E402
from run_execution_target_ratio_sensitivity import build_workload  # noqa: E402
from run_multiscale_design_surface import _collect_rows  # noqa: E402
from run_stage_a_screening import bundle_cost_equivalent_start  # noqa: E402

BLOCKS_PER_DAY = 7_200
BURN_IN = BLOCKS_PER_DAY
MEASURE_BLOCKS = 7 * BLOCKS_PER_DAY
N_SEEDS = 32
STATE_TARGET = 75_000_000.0
EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}
# Slot-budget assumptions.  All three are uncertain and all three are recorded
# on every output row.
SLOT_BUDGET_S = 9.0
EXECUTION_SPEED_GAS_PER_S = 100e6
DATA_GAS_PER_BYTE = 16
PROPAGATION_FIT = EMPIRICAL_P90
PROPAGATION_SAFETY = 1.0

PROPAGATION_TIMES_S = (2.5, 3.0, 3.5, 4.0, 4.5, 5.0)

EXECUTION_TARGETS = np.array([150, 175, 200, 225, 250, 275, 300]) * 1e6
DATA_TARGETS = np.array([
    22.5, 36, 45, 52.5, 60, 67.5, 77, 80, 90, 100, 110, 120, 130, 140,
]) * 1e6


def limits_for(t_prop_s: float) -> tuple[float, float]:
    """Solve the execution and data hard limits implied by one split."""

    payload = safe_payload_bytes(
        t_prop_s * 1000.0, PROPAGATION_FIT, PROPAGATION_SAFETY
    )
    data_limit = float(DATA_GAS_PER_BYTE * payload)
    execution_limit = EXECUTION_SPEED_GAS_PER_S * (SLOT_BUDGET_S - t_prop_s)
    return execution_limit, data_limit


def main() -> None:
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    anchor = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]

    print(f"slot budget {SLOT_BUDGET_S}s, execution {EXECUTION_SPEED_GAS_PER_S/1e6:.0f}M gas/s, "
          f"propagation fit {PROPAGATION_FIT.name} at safety {PROPAGATION_SAFETY}\n")
    print(f"{'t_prop':>8}{'t_exec':>9}{'payload':>11}{'L_data':>10}{'L_exec':>10}")
    for t_prop in PROPAGATION_TIMES_S:
        execution_limit, data_limit = limits_for(t_prop)
        print(f"{t_prop:>7.1f}s{SLOT_BUDGET_S-t_prop:>8.1f}s"
              f"{data_limit/DATA_GAS_PER_BYTE/2**20:>9.2f}MiB"
              f"{data_limit/1e6:>9.1f}M{execution_limit/1e6:>9.0f}M")
    print()

    shocks = build_workload()

    rows: list[dict] = []
    started = time.time()
    for t_prop in PROPAGATION_TIMES_S:
        execution_limit, data_limit = limits_for(t_prop)
        grid = [
            (te, td)
            for te in EXECUTION_TARGETS if te < execution_limit
            for td in DATA_TARGETS if td < data_limit
        ]
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
        split_rows = _collect_rows(
            workload="full_multiscale",
            data_limit=data_limit,
            grid=grid,
            config=cfg,
            result=out,
        )
        for row in split_rows:
            row.update({
                "propagation_time_s": float(t_prop),
                "execution_time_s": float(SLOT_BUDGET_S - t_prop),
                "slot_budget_s": SLOT_BUDGET_S,
                "execution_speed_gas_per_s": EXECUTION_SPEED_GAS_PER_S,
                "propagation_fit": PROPAGATION_FIT.name,
                "propagation_safety_factor": PROPAGATION_SAFETY,
                "execution_limit": execution_limit,
                "execution_target_ratio": (
                    float(row["execution_target"]) / execution_limit
                ),
                "data_target_ratio": float(row["data_target"]) / data_limit,
            })
        rows.extend(split_rows)
        print(f"  t_prop {t_prop:.1f}s -> {n:>3} cells   [{time.time()-started:6.1f}s]",
              flush=True)

    results = pd.DataFrame(rows)
    key = ["propagation_time_s", "execution_target", "data_target"]
    if results.duplicated(key).any():
        raise AssertionError("duplicate slot-time target configurations")
    if set(results["workload"]) != {"full_multiscale"}:
        raise AssertionError("slot-time output must use only the multiscale workload")
    out_path = ROOT / "data/7999/slot_time_scenarios.csv"
    results.to_csv(out_path, index=False)
    fixed_designs = {
        "E225/D36": (225e6, 36e6),
        "E225/D45": (225e6, 45e6),
        "E225/D52.5": (225e6, 52.5e6),
        "E250/D52.5": (250e6, 52.5e6),
        "E250/D60": (250e6, 60e6),
        "E275/D60": (275e6, 60e6),
        "E275/D67.5": (275e6, 67.5e6),
        "E300/D77": (300e6, 77e6),
        "E300/D80": (300e6, 80e6),
    }
    selected = []
    for design, (execution_target, data_target) in fixed_designs.items():
        match = results[
            np.isclose(results["execution_target"], execution_target)
            & np.isclose(results["data_target"], data_target)
        ].copy()
        match.insert(0, "design", design)
        selected.append(match)
    fixed = pd.concat(selected, ignore_index=True).sort_values(
        ["design", "propagation_time_s"]
    )
    fixed_path = ROOT / "data/7999/slot_time_fixed_designs.csv"
    fixed.to_csv(fixed_path, index=False)

    envelope = results.loc[
        results.groupby("propagation_time_s")["included_execution"].idxmax()
    ].sort_values("propagation_time_s")
    envelope_path = ROOT / "data/7999/slot_time_throughput_envelope.csv"
    envelope.to_csv(envelope_path, index=False)
    print(f"\n{len(results)} rows -> {out_path.relative_to(ROOT)}"
          f"   ({time.time()-started:.0f}s total)")
    print(f"{len(fixed)} rows -> {fixed_path.relative_to(ROOT)}")
    print(f"{len(envelope)} rows -> {envelope_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
