"""Plot one matched central workload path without modifying either replay kernel.

The main figures display all 50,400 measured blocks in the simulated week.
Explicit full-week filename aliases are also saved. Replication zero is chosen
in advance, without screening paths for their appearance.
"""
from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "src", ROOT / "scripts", ROOT / "scripts/shared_fee"):
    sys.path.insert(0, str(directory))

from dynamics.batched_replay import bundle_cost_equivalent_start, run_batch
from run_multiscale_design_surface import (
    BURN_IN, MEASURE_BLOCKS, REPORT_SHOCK_SEED, DAILY_SHOCK_SEED,
    build_canonical_workload,
)
from run_slot_time_parameter_sensitivity import build_config, specification_table
from shared_fee.equilibrium import SharedFeeAnchor, solve_shared_fee_equilibrium
import shared_fee.replay as shared_replay

OUT = ROOT / "data/shared_fee/example_paths"
PLOTS = ROOT / "plots"
REPLICATION = 0
DISPLAY_BLOCKS = MEASURE_BLOCKS
RESOURCE_ORDER = ((2, "State", "#54a24b"), (1, "Data", "#f58518"),
                  (0, "Execution", "#4c78a8"))


def shared_trace(config, shocks, initial_fee, burn_in):
    """Observe the canonical streaming summary in a single-threaded replay.

    The scoped observer only retains arrays passed to OnlineSummary.update;
    every demand, inclusion, and fee-update operation stays in the existing
    kernel. Restore its summary class on exit, including exceptional exits.
    """
    if config.batch_size != 1 or shocks.shape[0] != 1:
        raise ValueError("the illustrative trace expects exactly one path")
    used, offered, current_fees, next_fees = [], [], [], []
    original = shared_replay.OnlineSummary

    class RecordingSummary(original):
        def update(self, fees, previous_fees, included, demand, *args, **kwargs):
            current_fees.append(previous_fees.copy())
            next_fees.append(fees.copy())
            used.append(included.copy())
            offered.append(demand.copy())
            return super().update(fees, previous_fees, included, demand, *args, **kwargs)

    with patch.object(shared_replay, "OnlineSummary", RecordingSummary):
        summary = shared_replay.run_shared_fee_batch(
            config, shocks, initial_fee, burn_in=burn_in,
        )
    included = np.asarray(used)[:, 0, :]
    demand = np.asarray(offered)[:, 0, :]
    fees = np.asarray(current_fees)[:, 0, 0]
    following_fees = np.asarray(next_fees)[:, 0, 0]
    # Summary channels are execution, max(regular, state), and state. Recover
    # regular from the included execution and its common inclusion fraction.
    scale = included[:, 0] / demand[:, 0]
    m_data = float(np.asarray(config.m_data).reshape(-1)[0])
    epsilon = float(config.eps_data[0])
    q_data = (config.q_data_0 * np.maximum(m_data * fees / (config.p0_gwei * 1e9), 1e-300)
              ** (-epsilon) * shocks[0, burn_in:, 1])
    data = m_data * q_data * scale
    regular = included[:, 0] + data
    np.testing.assert_allclose(regular.mean(), summary["mean_included_regular"][0], rtol=1e-12)
    np.testing.assert_allclose(data.mean(), summary["mean_included_data"][0], rtol=1e-12)
    np.testing.assert_allclose(np.maximum(regular, included[:, 2]), included[:, 1], rtol=1e-12)
    np.testing.assert_array_equal(fees[1:], following_fees[:-1])
    return dict(regular=regular, state=included[:, 2], execution=included[:, 0],
                data=data, shared=included[:, 1], fee=fees, next_fee=following_fees), summary


def settings():
    specs = specification_table()
    spec = specs[specs.is_central].iloc[0]
    demand = pd.read_csv(ROOT / "data/7999/bal_decomposition_demand_parameters.csv").iloc[0]
    data = pd.read_csv(ROOT / "data/7999/data_metering_runtime_bal_anchor.csv").iloc[0]
    batch = build_config([(int(spec.name), 225e6, 60e6, 450e6, 90e6)], specs, demand, data)
    # The existing builder repeats a design for all 32 paths; keep only path 0.
    eip = replace(batch, **{f.name: getattr(batch, f.name)[:1] for f in fields(batch)
                            if isinstance(getattr(batch, f.name), np.ndarray)})
    baseline = pd.read_csv(ROOT / "data/shared_fee/shared_fee_state_tail.csv")
    baseline = baseline[baseline.benchmark.eq("proposal_faithful")
                        & baseline.propagation_time_s.eq(3.)
                        & baseline.state_demand_cap_label.eq("unrestricted")].iloc[0]
    base = pd.read_csv(ROOT / "data/shared_fee/equilibrium_anchor_by_floor_rate.csv").iloc[0]
    arr = lambda x: np.array([float(x)])
    shared = shared_replay.SharedFeeConfig(
        gas_target=arr(baseline.shared_target), gas_limit=arr(baseline.shared_limit),
        eps_execution=arr(spec.eps_execution), eps_data=arr(spec.eps_data),
        eps_state=arr(spec.eps_state), m_execution=baseline.m_execution,
        m_data=baseline.m_data, m_state=baseline.m_state,
        q_execution_0=base.q_execution_per_block, q_data_0=base.q_data_per_block,
        q_state_0=base.q_state_per_block, p0_gwei=base.base_fee_ref_gwei,
        w_execution=demand.w_execution_reference, w_state=demand.w_state_reference,
    )
    anchor = SharedFeeAnchor(base.q_execution_per_block, base.q_data_per_block,
        base.q_state_per_block, baseline.m_execution, baseline.m_data, baseline.m_state,
        base.base_fee_ref_gwei, spec.eps_execution, spec.eps_data, spec.eps_state)
    equilibrium = solve_shared_fee_equilibrium(baseline.shared_target, anchor)
    np.testing.assert_allclose(baseline.equilibrium_fee_wei, equilibrium.base_fee_wei, rtol=1e-10)
    np.testing.assert_allclose(eip.m_execution, shared.m_execution, rtol=1e-12)
    return eip, shared, equilibrium, spec


def save(fig, name):
    PLOTS.mkdir(exist_ok=True)
    fig.savefig(PLOTS / f"{name}.png", dpi=140, bbox_inches="tight", pil_kwargs={"optimize": True})
    fig.savefig(PLOTS / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def format_axis(ax, count, fee=False):
    ax.set_xlim(1, count)
    ax.grid(alpha=.18)
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.spines[["right", "top"]].set_visible(False)
    if fee:
        ax.set_yscale("log")
        ax.set_ylabel("base fee (wei, log scale)")
    else:
        ax.set_ylim(bottom=0)
        ax.set_ylabel("gas usage (M)")


def eip_figure(used, fees, count, suffix=""):
    fig, axes = plt.subplots(2, 3, figsize=(17.2, 8.4), sharex=True)
    blocks = np.arange(1, count + 1)
    targets, limits = [225, 60, 75], [450, 90, None]
    for column, (index, name, color) in enumerate(RESOURCE_ORDER):
        top, bottom = axes[:, column]
        top.plot(blocks, used[:count, index] / 1e6, color=color, lw=.45, alpha=.72,
                 rasterized=True)
        top.axhline(targets[index], color="#333333", ls="--", lw=1.5,
                    label=f"target: {targets[index]:g}M")
        if limits[index] is not None:
            top.axhline(limits[index], color="#222222", lw=1.6,
                        label=f"limit: {limits[index]:g}M")
        top.set_title(f"{name} gas" + (" (static + BAL)" if index == 1 else ""))
        top.legend(loc="upper right", fontsize=10, framealpha=.92)
        bottom.plot(blocks, fees[:count, index], color=color, lw=.7, rasterized=True)
        if index == 0:
            bottom.axhline(1, color="#555555", ls=":", lw=1)
        bottom.set_title(f"{name} base fee")
        bottom.set_xlabel("block number")
        format_axis(top, count)
        format_axis(bottom, count, fee=True)
    fig.subplots_adjust(wspace=.29, hspace=.25, bottom=.12)
    fig.text(.5, .015, "EIP-7999 E225/D60 · execution limit 450M · data limit 90M · state target 75M, no state hard limit\n"
             "35-day elasticities · λ = 0 · ρA = 1 · replication 0 · burn-in excluded · raw block observations",
             ha="center", va="bottom", fontsize=10)
    save(fig, "dynamic_7999_E225_D60_example_path" + suffix)


def shared_figure(trace, config, count, suffix=""):
    fig, axes = plt.subplots(1, 3, figsize=(17.2, 5.4), sharex=True)
    blocks = np.arange(1, count + 1)
    for ax, key, color in zip(axes[:2], ("regular", "state"), ("#4c78a8", "#54a24b")):
        ax.plot(blocks, trace[key][:count] / 1e6, color=color, lw=.5,
                alpha=.72, rasterized=True)
        ax.axhline(config.gas_target[0] / 1e6, color="#333333", ls="--", lw=1.5,
                   label=f"target: {config.gas_target[0] / 1e6:.1f}M")
        ax.axhline(config.gas_limit[0] / 1e6, color="#222222", lw=1.6,
                   label=f"limit: {config.gas_limit[0] / 1e6:.1f}M")
        ax.set_title(f"Metered {key} gas")
        ax.legend(loc="upper right", fontsize=10, framealpha=.94)
    axes[2].plot(blocks, trace["fee"][:count], color="#6c6c6c", lw=.8, rasterized=True)
    axes[2].set_title("Shared base fee")
    for i, ax in enumerate(axes):
        format_axis(ax, count, fee=i == 2)
        ax.set_xlabel("block number")
    # Keep the two counter panels directly comparable on the same gas scale.
    for ax in axes[:2]:
        ax.set_ylim(0, config.gas_limit[0] / 1e6 * 1.05)
    fig.subplots_adjust(wspace=.29, bottom=.22)
    fig.text(.5, .015, "Baseline one-dimensional · 3s propagation · floor 64 gas/byte · CPSB 1,530\n"
             "35-day elasticities · same replication 0 · burn-in excluded · raw block observations",
             ha="center", va="bottom", fontsize=10)
    save(fig, "dynamic_baseline_3s_example_path" + suffix)


def main():
    plt.rcParams.update({"font.size": 12, "axes.titlesize": 15, "axes.labelsize": 12})
    eip, shared, equilibrium, spec = settings()
    workload = build_canonical_workload().paths
    workload_hash = hashlib.sha256(np.ascontiguousarray(workload).view(np.uint8)).hexdigest()
    expected = pd.read_csv(ROOT / "data/shared_fee/shared_fee_factorial_manifest.csv").iloc[0].workload_sha256
    assert workload_hash == expected
    shocks = workload[REPLICATION:REPLICATION + 1]
    initial = bundle_cost_equivalent_start(eip)
    result = run_batch(eip, shocks, initial, bundle_consistent=True,
                       burn_in=BURN_IN, return_paths=True)
    used = result["used_paths"][0, BURN_IN:]
    # The canonical fee_paths stores the update for the next block. Shift it
    # back so usage and monetary price on the figure refer to the same block.
    fees = result["fee_paths"][0, BURN_IN - 1:-1]
    next_fees = result["fee_paths"][0, BURN_IN:]
    np.testing.assert_allclose(used.mean(axis=0), result["mean_used"][0], rtol=1e-12)
    np.testing.assert_allclose(next_fees.mean(axis=0), result["mean_fee_wei"][0], rtol=1e-12)
    np.testing.assert_allclose((used * fees).mean(axis=0), result["mean_burn_wei"][0], rtol=1e-12)
    trace, summary = shared_trace(shared, shocks, np.array([equilibrium.base_fee_wei]), BURN_IN)
    assert len(fees) == len(trace["fee"]) == MEASURE_BLOCKS
    # Check the observed baseline path against its saved matched replication.
    cache = pd.read_csv(ROOT / "data/shared_fee/shared_fee_elasticity_comparison_paths.csv")
    row = cache[cache.benchmark.eq("proposal_faithful") & cache.window_days.eq(35)
                & cache.propagation_time_s.eq(3) & cache.replication.eq(REPLICATION)].iloc[0]
    np.testing.assert_allclose(trace["execution"].mean(), row.metered_execution_gas, rtol=1e-12)
    np.testing.assert_allclose(trace["state"].mean(), row.state_gas, rtol=1e-12)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "central_replication_00.npz", measured_block=np.arange(1, MEASURE_BLOCKS + 1),
        shocks=shocks[0, BURN_IN:], eip7999_included_gas=used, eip7999_base_fee_wei=fees,
        eip7999_next_base_fee_wei=next_fees, **{f"baseline_{k}": v for k, v in trace.items()})
    for count, suffix in ((DISPLAY_BLOCKS, ""), (MEASURE_BLOCKS, "_full_week")):
        eip_figure(used, fees, count, suffix)
        shared_figure(trace, shared, count, suffix)
    manifest = dict(replication=REPLICATION, choice="First saved path; no path screening",
        workload_sha256=workload_hash, fast_seed=REPORT_SHOCK_SEED, daily_seed=DAILY_SHOCK_SEED,
        burn_in_blocks=BURN_IN, measured_blocks=MEASURE_BLOCKS, main_plot_blocks=DISPLAY_BLOCKS,
        displayed_series="Every measured block, unsmoothed; fees are pre-update prices charged in that block",
        resource_order_in_arrays=["execution", "data", "state"],
        elasticity_window=35, eps_execution=spec.eps_execution, eps_data=spec.eps_data,
        eps_state=spec.eps_state, lambda_bal=0, rho_A=1,
        eip7999=dict(execution_target=225e6, execution_limit=450e6, data_target=60e6,
                     data_limit=90e6, state_target=75e6, state_limit=None,
                     initialization="Existing cost-equivalent launch; one-day burn-in"),
        baseline=dict(propagation_seconds=3, shared_target=float(shared.gas_target[0]),
                      shared_limit=float(shared.gas_limit[0]), floor=64, cpsb=1530,
                      equilibrium_fee_wei=equilibrium.base_fee_wei,
                      initialization="Existing unshocked equilibrium launch; one-day burn-in"),
        kernel_hashes={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                      ("src/shared_fee/replay.py", "src/dynamics/batched_replay.py")})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "main_plot_blocks": DISPLAY_BLOCKS,
          "baseline_target": float(shared.gas_target[0]), "baseline_limit": float(shared.gas_limit[0]),
          "mean_7999_gas": used.mean(axis=0).tolist(),
          "mean_baseline_regular": float(trace["regular"].mean()),
          "mean_baseline_state": float(trace["state"].mean())}, indent=2))


if __name__ == "__main__":
    main()
