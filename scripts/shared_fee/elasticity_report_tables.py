"""Render report tables from the matched-path elasticity outputs (no simulation)."""
from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/shared_fee"
LABELS = {
    "proposal_faithful": "Baseline",
    "fully_optimized": "Floor-adjusted + EIP-8368",
    "balanced": "EIP-7999 historically anchored",
    "maximum": "EIP-7999 maximum throughput",
}


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(str, row)) + " |" for row in rows),
    ])


def report_tables():
    selected = pd.read_csv(OUT / "shared_fee_elasticity_reselected.csv")
    best = pd.read_csv(OUT / "shared_fee_elasticity_best_designs.csv")
    fixed = pd.read_csv(OUT / "shared_fee_elasticity_fixed_central.csv")
    gains = pd.read_csv(OUT / "shared_fee_elasticity_gains.csv")
    rows = []
    for window in (21, 35, 60, 75):
        cells = [f"{window}-day"]
        for family in ("fully_optimized", "maximum", "balanced"):
            row = best[(best.window_days == window) & best.benchmark.eq(family)].iloc[0]
            if not row.available:
                cells.append("No eligible configuration in the tested grid")
                continue
            config = f"{row.shared_limit / 1e6:g}M limit" if family == "fully_optimized" else row.configuration
            cells.append(f"{row.propagation_time_s:.1f}s, {config}<br>"
                         f"{row.metered_execution_gas / 1e6:.1f}M; {row.annualized_state_growth_gib:.1f} GiB/year")
        rows.append(cells)
    result = {"selection": table(["Elasticity vector", "Floor-adjusted + EIP-8368", "EIP-7999 maximum throughput",
                                   "EIP-7999 historically anchored"], rows)}

    for family in ("proposal_faithful", "fully_optimized"):
        rows = []
        for _, row in selected[selected.benchmark.eq(family)].sort_values(["window_days", "propagation_time_s"]).iterrows():
            rows.append([f"{row.window_days:.0f}-day", f"{row.propagation_time_s:.1f}s", f"{row.shared_limit / 1e6:.1f}M",
                         f"{row.equilibrium_execution_fee_wei:,.0f}", f"{row.metered_execution_gas / 1e6:.1f}M",
                         f"{row.annualized_state_growth_gib:.1f}", f"{row.state_binding_fraction:.2%}",
                         f"{row.hard_limit_fraction:.2%}", f"{row.execution_price_variation:.4f}"])
        result[family] = table(["Vector", "Propagation", "Common limit", "Equilibrium fee (wei)", "Mean execution",
                                "State growth (GiB/year)", "State is larger branch", "Blocks at common limit", "Fee variation"], rows)

    # Freeze the four globally selected central configurations. The underlying
    # fixed-candidate CSV also includes all five propagation-specific choices.
    rows = []
    for family in LABELS:
        central = best[best.window_days.eq(35) & best.benchmark.eq(family)].iloc[0]
        group = fixed[fixed.benchmark.eq(family) & fixed.propagation_time_s.eq(central.propagation_time_s)
                      & fixed.configuration.eq(central.configuration)].sort_values("window_days")
        assert len(group) == 4
        config = f"{central.shared_limit / 1e6:g}M limit" if family in ("proposal_faithful", "fully_optimized") else central.configuration
        for _, row in group.iterrows():
            rows.append([LABELS[family], f"{central.propagation_time_s:.1f}s, {config}", f"{row.window_days:.0f}-day",
                         f"{row.metered_execution_gas / 1e6:.1f}M", f"{row.annualized_state_growth_gib:.1f}",
                         f"{row.hard_limit_fraction:.2%}", f"{row.target_deviation:.2%}"])
    result["fixed"] = table(["Central design family", "Frozen configuration", "Vector", "Mean execution",
                              "State growth (GiB/year)", "Hard-limit blocks", "Target deviation"], rows)

    rows = []
    for _, row in gains.sort_values(["window_days", "propagation_time_s", "benchmark"]).iterrows():
        label = "Historically anchored" if row.benchmark == "balanced" else "Maximum throughput"
        if not row.available:
            rows.append([f"{row.window_days:.0f}-day", f"{row.propagation_time_s:.1f}s", label,
                         "No eligible configuration", "—", "—"])
        else:
            rows.append([f"{row.window_days:.0f}-day", f"{row.propagation_time_s:.1f}s", label,
                         f"{row.mean_gain / 1e6:.1f}", f"{row.week_p05 / 1e6:.1f}–{row.week_p95 / 1e6:.1f}",
                         f"{row.mean_ci95_low / 1e6:.1f}–{row.mean_ci95_high / 1e6:.1f}"])
    result["gains"] = table(["Vector", "Propagation", "EIP-7999 selection", "Mean gain (M)",
                              "Simulated-week p05–p95 (M)", "95% interval for mean gain (M)"], rows)
    return result


if __name__ == "__main__":
    print(json.dumps(report_tables(), indent=2))
