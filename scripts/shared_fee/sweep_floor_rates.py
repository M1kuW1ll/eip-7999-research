"""Calibrate the shared-fee data multiplier across a requested floor-rate grid.

The calculation replays the EIP-8131/EIP-8279 transaction floor on the exact
6,000-block calibration panel. It changes only the floor rate while keeping
the current execution and state accounting fixed. The 64-gas result remains
the bridge to the earlier EIP-7976/EIP-7981 calibration. Every tested rate is
materialized as an equilibrium anchor; the selected detailed rate controls the
transaction-decomposition outputs and figures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shared_fee.floor_accounting import (  # noqa: E402
    ACCOUNT_WRITE_8038,
    COLD_ACCOUNT_ACCESS_8038,
    COLD_STORAGE_ACCESS_8038,
    CREATE_ACCESS_8038,
    STORAGE_WRITE_8038,
)

DATA = ROOT / "data/shared_fee"
PLOTS = ROOT / "plots"
TAG = "2026-02-01_2026-06-01"
REFERENCE_RATE = 64
CENTRAL_RATE = 96
BOOTSTRAP_SEED = 8_279


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rates",
        type=int,
        nargs="+",
        required=True,
        help="Floor rates in gas per byte.",
    )
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=400,
        help="Day-block bootstrap replications.",
    )
    parser.add_argument(
        "--central-rate",
        type=int,
        default=CENTRAL_RATE,
        help="Rate to materialize for detailed decompositions and figures.",
    )
    return parser.parse_args()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def weighted_sum(
    block_values: pd.Series,
    block_dates: pd.Series,
    full_days: pd.DataFrame,
    sampled_blocks_per_day: pd.Series,
) -> float:
    daily = pd.DataFrame(
        {"date": block_dates.to_numpy(), "value": block_values.to_numpy()}
    ).groupby("date", as_index=False)["value"].sum()
    daily = daily.merge(
        sampled_blocks_per_day.rename("sampled_blocks"),
        left_on="date",
        right_index=True,
        validate="one_to_one",
    )
    daily = daily.merge(
        full_days[["date", "block_count"]],
        on="date",
        validate="one_to_one",
    )
    return float(
        (
            daily["value"]
            / daily["sampled_blocks"]
            * daily["block_count"]
        ).sum()
    )


def aggregate_blocks(
    panel: pd.DataFrame,
    sampled_blocks: pd.DataFrame,
    rates: list[int],
    state_multiplier: float,
) -> tuple[pd.DataFrame, dict[int, dict[str, np.ndarray]]]:
    execution = panel["execution_gas_for_floor"].to_numpy(dtype=float)
    intrinsic = panel["intrinsic_execution_base_2780"].to_numpy(dtype=float)
    static_bytes = panel["static_data_8131_bytes"].to_numpy(dtype=float)
    bal_bytes = panel["bal_floor_bytes_8279"].to_numpy(dtype=float)
    state = (
        state_multiplier
        * panel["state_reference_gas_capped"].to_numpy(dtype=float)
    )
    payment_branch = execution + state

    blocks = sampled_blocks[["date", "block_number"]].copy()
    blocks["date"] = pd.to_datetime(blocks["date"])
    transaction_arrays: dict[int, dict[str, np.ndarray]] = {}
    block_number = panel["block_number"].to_numpy()

    # Keep the accepted EIP-7976/EIP-7981 64-gas floor as the fixed bridge
    # beneath every candidate EIP-8131/EIP-8279 rate.  This lets the bootstrap
    # reproduce the existing uncertainty at the 64-gas reference rather than
    # treating that sampled estimate as known without error.
    charged_baseline = np.maximum(
        execution,
        panel["floor_gas_7976_7981"].to_numpy(dtype=float),
    )
    baseline_blocks = pd.DataFrame(
        {
            "block_number": block_number,
            "charged_baseline_7976_7981_64": charged_baseline,
        }
    ).groupby("block_number", as_index=False).sum()
    blocks = blocks.merge(
        baseline_blocks,
        on="block_number",
        how="left",
        validate="one_to_one",
    )

    for rate in rates:
        static_floor = intrinsic + rate * static_bytes
        total_floor = static_floor + rate * bal_bytes
        charged_static = np.maximum(execution, static_floor)
        charged_total = np.maximum(execution, total_floor)
        charged_payment_static = np.maximum(payment_branch, static_floor)
        charged_payment_total = np.maximum(payment_branch, total_floor)

        transaction_arrays[rate] = {
            "static_floor_bound": static_floor >= execution,
            "total_floor_bound": total_floor >= execution,
            "bal_affected": charged_total > charged_static,
            "bal_increment": charged_total - charged_static,
            "total_floor_uplift": charged_total - execution,
            "static_floor_uplift": charged_static - execution,
            "payment_floor_bound": total_floor >= payment_branch,
            "payment_bal_increment": (
                charged_payment_total - charged_payment_static
            ),
            "payment_total_floor_uplift": (
                charged_payment_total - payment_branch
            ),
        }

        tx_block = pd.DataFrame(
            {
                "block_number": block_number,
                f"charged_total_{rate}": charged_total,
                f"charged_static_{rate}": charged_static,
                f"bal_increment_{rate}": charged_total - charged_static,
                f"total_floor_uplift_{rate}": charged_total - execution,
                f"payment_bal_increment_{rate}": (
                    charged_payment_total - charged_payment_static
                ),
                f"payment_total_floor_uplift_{rate}": (
                    charged_payment_total - payment_branch
                ),
            }
        ).groupby("block_number", as_index=False).sum()
        blocks = blocks.merge(
            tx_block,
            on="block_number",
            how="left",
            validate="one_to_one",
        )

    value_columns = [column for column in blocks if column not in {"date", "block_number"}]
    blocks[value_columns] = blocks[value_columns].fillna(0.0)
    return blocks.sort_values("block_number").reset_index(drop=True), transaction_arrays


def bootstrap_multipliers(
    blocks: pd.DataFrame,
    full_days: pd.DataFrame,
    rates: list[int],
    baseline_multiplier: float,
    replications: int,
) -> pd.DataFrame:
    if replications <= 0:
        return pd.DataFrame(columns=["replication", "floor_rate", "m_data_block"])

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    dates = full_days["date"].to_numpy()
    block_count = dict(zip(full_days["date"], full_days["block_count"], strict=True))
    denominator = dict(
        zip(full_days["date"], full_days["data_gas_current"], strict=True)
    )
    by_day = {
        date: frame.reset_index(drop=True)
        for date, frame in blocks.groupby("date", sort=False)
    }
    rows: list[dict[str, float | int]] = []

    for replication in range(replications):
        sampled_dates = rng.choice(dates, size=len(dates), replace=True)
        delta = {rate: 0.0 for rate in rates}
        reference_data = 0.0
        for raw_date in sampled_dates:
            date = pd.Timestamp(raw_date)
            day = by_day[date]
            draw = rng.integers(0, len(day), size=len(day))
            weight = float(block_count[date])
            reference_data += float(denominator[date])
            baseline_charged = day[
                "charged_baseline_7976_7981_64"
            ].to_numpy()
            for rate in rates:
                charged = day[f"charged_total_{rate}"].to_numpy()
                delta[rate] += float(
                    (charged[draw] - baseline_charged[draw]).mean()
                ) * weight
        for rate in rates:
            rows.append(
                {
                    "replication": replication,
                    "floor_rate": rate,
                    "m_data_block": baseline_multiplier + delta[rate] / reference_data,
                }
            )
    return pd.DataFrame(rows)


def floor_activation_decomposition(
    panel: pd.DataFrame,
    rates: list[int],
) -> pd.DataFrame:
    """Reproduce the report's five floor classes at every selected rate."""

    execution = panel["execution_gas_for_floor"].to_numpy(dtype=float)
    intrinsic = panel["intrinsic_execution_base_2780"].to_numpy(dtype=float)
    static_bytes = panel["static_data_8131_bytes"].to_numpy(dtype=float)
    bal_bytes = panel["bal_floor_bytes_8279"].to_numpy(dtype=float)
    runtime_bal = panel["bal_runtime_bytes_8279"].to_numpy(dtype=float)
    deployed_code = panel["deployed_code_bytes_8279"].to_numpy(dtype=float)
    labels = [
        "already floor-bound under static EIP-8131",
        "within 10% of static floor",
        "newly floor-bound primarily because of deployed code",
        "newly floor-bound through other non-code BAL",
        "unaffected",
    ]
    rows: list[dict[str, float | int | str]] = []

    for rate in rates:
        static_floor = intrinsic + rate * static_bytes
        total_floor = static_floor + rate * bal_bytes
        charged_static = np.maximum(execution, static_floor)
        charged_total = np.maximum(execution, total_floor)
        increment = charged_total - charged_static
        affected = increment > 1e-8
        already = affected & (static_floor >= execution)
        newly = affected & ~already
        headroom_ratio = (execution - static_floor) / np.maximum(execution, 1.0)
        close = newly & (headroom_ratio <= 0.10)
        floor_without_code = total_floor - rate * deployed_code
        code_pivotal = (
            newly
            & ~close
            & (deployed_code > 0)
            & (floor_without_code <= execution)
        )
        other = newly & ~close & ~code_pivotal
        masks = [already, close, code_pivotal, other, ~affected]
        total_runtime_bal = max(float(runtime_bal.sum()), 1.0)
        total_increment = max(float(increment.sum()), 1.0)
        for label, mask in zip(labels, masks, strict=True):
            rows.append(
                {
                    "floor_rate": rate,
                    "floor_class": label,
                    "transactions": int(mask.sum()),
                    "transaction_share": float(mask.mean()),
                    "runtime_bal_bytes": float(runtime_bal[mask].sum()),
                    "runtime_bal_byte_share": float(
                        runtime_bal[mask].sum() / total_runtime_bal
                    ),
                    "incremental_bal_floor_gas": float(increment[mask].sum()),
                    "incremental_bal_floor_gas_share": float(
                        increment[mask].sum() / total_increment
                    ),
                }
            )
    return pd.DataFrame(rows)


FLOOR_CLASS_ORDER = [
    "already floor-bound under static EIP-8131",
    "close to static floor; pushed across by runtime BAL",
    "newly floor-bound primarily because of deployed code",
    "newly floor-bound through other non-code BAL",
    "unaffected",
]


def materialize_rate_panel(panel: pd.DataFrame, rate: int) -> pd.DataFrame:
    """Recalculate the complete transaction-floor panel at one rate."""

    out = panel.copy()
    execution = out["execution_gas_for_floor"].to_numpy(dtype=float)
    intrinsic = out["intrinsic_execution_base_2780"].to_numpy(dtype=float)
    static_bytes = out["static_data_8131_bytes"].to_numpy(dtype=float)
    bal_bytes = out["bal_floor_bytes_8279"].to_numpy(dtype=float)
    deployed_code = out["deployed_code_bytes_8279"].to_numpy(dtype=float)
    static_floor = intrinsic + rate * static_bytes
    total_floor = static_floor + rate * bal_bytes
    charged_static = np.maximum(execution, static_floor)
    charged_total = np.maximum(execution, total_floor)
    increment = charged_total - charged_static
    affected = increment > 1e-8
    already = affected & (static_floor >= execution)
    newly = affected & ~already
    headroom_ratio = (execution - static_floor) / np.maximum(execution, 1.0)
    close = newly & (headroom_ratio <= 0.10)
    floor_without_code = total_floor - rate * deployed_code
    code_pivotal = (
        newly
        & ~close
        & (deployed_code > 0)
        & (floor_without_code <= execution)
    )
    other = newly & ~close & ~code_pivotal

    out["floor_rate"] = rate
    out["floor_gas_8131"] = static_floor
    out["floor_gas_8279"] = total_floor
    out["charged_regular_gas_8131"] = charged_static
    out["charged_regular_gas_8279"] = charged_total
    out["incremental_data_gas_8279"] = increment
    out["floor_bound_8131"] = static_floor >= execution
    out["floor_bound_8279"] = total_floor >= execution
    out["newly_floor_bound_8279"] = newly
    out["headroom_ratio_8131"] = headroom_ratio
    out["floor_class"] = np.select(
        [already, close, code_pivotal, other],
        FLOOR_CLASS_ORDER[:4],
        default=FLOOR_CLASS_ORDER[4],
    )
    out["affected_by_8279"] = affected
    return out


def summarize_decomposition(
    panel: pd.DataFrame,
    group: str,
    output_name: str | None = None,
) -> pd.DataFrame:
    """Aggregate central-rate activation by one transaction classification."""

    total_runtime_bal = float(panel["bal_runtime_bytes_8279"].sum())
    total_uplift = float(panel["incremental_data_gas_8279"].sum())
    total_regular = float(panel["charged_regular_gas_8279"].sum())
    grouped = panel.groupby(group, observed=True, as_index=False).agg(
        transactions=("tx_hash", "size"),
        affected_transactions=("affected_by_8279", "sum"),
        runtime_bal_bytes=("bal_runtime_bytes_8279", "sum"),
        bal_floor_bytes=("bal_floor_bytes_8279", "sum"),
        incremental_data_gas=("incremental_data_gas_8279", "sum"),
        regular_branch_gas=("charged_regular_gas_8279", "sum"),
    )
    if output_name and output_name != group:
        grouped = grouped.rename(columns={group: output_name})
    grouped["transaction_share"] = grouped["transactions"] / len(panel)
    grouped["affected_fraction_within_group"] = (
        grouped["affected_transactions"] / grouped["transactions"]
    )
    grouped["affected_transaction_share_of_all"] = (
        grouped["affected_transactions"] / len(panel)
    )
    grouped["runtime_bal_byte_share"] = (
        grouped["runtime_bal_bytes"] / max(total_runtime_bal, 1.0)
    )
    grouped["incremental_gas_share"] = (
        grouped["incremental_data_gas"] / max(total_uplift, 1.0)
    )
    grouped["incremental_gas_as_share_of_group_regular_branch"] = (
        grouped["incremental_data_gas"]
        / grouped["regular_branch_gas"].clip(lower=1.0)
    )
    grouped["incremental_gas_as_share_of_all_regular_branch"] = (
        grouped["incremental_data_gas"] / max(total_regular, 1.0)
    )
    return grouped


def summarize_runtime_coverage(panel: pd.DataFrame, rate: int) -> pd.DataFrame:
    """Compare the current EIP-8038 charges with runtime BAL at one rate."""

    runtime = pd.read_parquet(DATA / "runtime_components_6000_blocks.parquet")
    keys = ["block_number", "tx_index", "tx_hash"]
    runtime["tx_hash"] = runtime["tx_hash"].astype(str)
    selected_columns = [
        *keys,
        "cold_account_accesses",
        "cold_storage_accesses",
        "storage_value_entries_observed",
        "positive_value_calls",
        "positive_value_selfdestructs",
        "internal_creates",
        "deployed_code_bytes_8279",
    ]
    out = panel.merge(
        runtime[selected_columns],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_runtime"),
    )
    component_columns = [
        column
        for column in selected_columns
        if column not in {*keys, "deployed_code_bytes_8279"}
    ]
    out[component_columns] = out[component_columns].fillna(0.0)
    out["deployed_code_bytes_8279_runtime"] = out[
        "deployed_code_bytes_8279_runtime"
    ].fillna(0.0)
    deployed_code = out["deployed_code_bytes_8279_runtime"]
    noncode_bytes = out["bal_runtime_bytes_8279"] - deployed_code
    paired_noncode = (
        COLD_ACCOUNT_ACCESS_8038 * out["cold_account_accesses"]
        + COLD_STORAGE_ACCESS_8038 * out["cold_storage_accesses"]
        + STORAGE_WRITE_8038 * out["storage_value_entries_observed"]
        + ACCOUNT_WRITE_8038 * out["positive_value_calls"]
        + 5_000 * out["positive_value_selfdestructs"]
        + CREATE_ACCESS_8038 * out["internal_creates"]
    )
    paired_all = paired_noncode + 6 * np.ceil(deployed_code / 32)
    noncode_floor = rate * noncode_bytes
    all_floor = rate * out["bal_runtime_bytes_8279"]
    carriers = out.loc[out["bal_runtime_bytes_8279"].gt(0)].copy()
    carriers["noncode_floor_gas_central"] = noncode_floor.loc[carriers.index]
    carriers["all_floor_gas_central"] = all_floor.loc[carriers.index]
    carriers["paired_noncode_execution_gas_central"] = paired_noncode.loc[
        carriers.index
    ]
    carriers["paired_all_runtime_execution_gas_central"] = paired_all.loc[
        carriers.index
    ]
    state = carriers["state_reference_gas_capped"].gt(0)
    rows: list[dict[str, float | int | str]] = []
    for label, mask in [
        ("all BAL-carrying transactions", pd.Series(True, index=carriers.index)),
        ("state-creating BAL-carrying transactions", state),
        ("BAL-carrying transactions without state creation", ~state),
    ]:
        selected = carriers.loc[mask]
        noncode_failure = selected["paired_noncode_execution_gas_central"].lt(
            selected["noncode_floor_gas_central"]
        )
        all_failure = selected["paired_all_runtime_execution_gas_central"].lt(
            selected["all_floor_gas_central"]
        )
        rows.append(
            {
                "floor_rate": rate,
                "transaction_class": label,
                "transactions": len(selected),
                "runtime_bal_bytes": int(selected["bal_runtime_bytes_8279"].sum()),
                "deployed_code_bytes": int(
                    selected["deployed_code_bytes_8279_runtime"].sum()
                ),
                "noncode_floor_gas": float(
                    selected["noncode_floor_gas_central"].sum()
                ),
                "paired_noncode_execution_gas": float(
                    selected["paired_noncode_execution_gas_central"].sum()
                ),
                "noncode_coverage_ratio": float(
                    selected["paired_noncode_execution_gas_central"].sum()
                    / max(selected["noncode_floor_gas_central"].sum(), 1.0)
                ),
                "noncode_coverage_failures": int(noncode_failure.sum()),
                "all_runtime_coverage_ratio": float(
                    selected["paired_all_runtime_execution_gas_central"].sum()
                    / max(selected["all_floor_gas_central"].sum(), 1.0)
                ),
                "all_runtime_coverage_failures": int(all_failure.sum()),
                "runtime_bal_byte_share_in_all_coverage_failures": float(
                    selected.loc[all_failure, "bal_runtime_bytes_8279"].sum()
                    / max(selected["bal_runtime_bytes_8279"].sum(), 1.0)
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_full_floor_coverage(panel: pd.DataFrame, rate: int) -> pd.DataFrame:
    """Summarize execution coverage of the complete central-rate floor."""

    out = panel.copy()
    out["state_creating"] = out["state_reference_gas_capped"].gt(0)
    out["coverage_ratio"] = (
        out["execution_gas_for_floor"] / out["floor_gas_8279"].clip(lower=1.0)
    )
    out["uncovered_floor_gas"] = (
        out["floor_gas_8279"] - out["execution_gas_for_floor"]
    ).clip(lower=0.0)
    groups = [
        ("all transactions", pd.Series(True, index=out.index)),
        ("state-creating transactions", out["state_creating"]),
        ("transactions without state creation", ~out["state_creating"]),
    ]
    total_bal = float(out["bal_floor_bytes_8279"].sum())
    total_uplift = float(out["incremental_data_gas_8279"].sum())
    rows: list[dict[str, float | int | str]] = []
    for label, mask in groups:
        selected = out.loc[mask]
        under = selected["coverage_ratio"].lt(1.0)
        rows.append(
            {
                "floor_rate": rate,
                "transaction_class": label,
                "transactions": len(selected),
                "transaction_share": len(selected) / len(out),
                "transactions_with_bal": int(
                    selected["bal_floor_bytes_8279"].gt(0).sum()
                ),
                "coverage_ratio_median": float(selected["coverage_ratio"].median()),
                "coverage_ratio_p05": float(
                    selected["coverage_ratio"].quantile(0.05)
                ),
                "coverage_ratio_p95": float(
                    selected["coverage_ratio"].quantile(0.95)
                ),
                "fraction_below_one": float(under.mean()),
                "bal_floor_bytes": float(selected["bal_floor_bytes_8279"].sum()),
                "bal_byte_share_of_all": float(
                    selected["bal_floor_bytes_8279"].sum() / max(total_bal, 1.0)
                ),
                "incremental_data_gas_8279": float(
                    selected["incremental_data_gas_8279"].sum()
                ),
                "incremental_gas_share_of_all": float(
                    selected["incremental_data_gas_8279"].sum()
                    / max(total_uplift, 1.0)
                ),
                "uncovered_floor_gas": float(selected["uncovered_floor_gas"].sum()),
            }
        )
    return pd.DataFrame(rows)


def write_central_outputs(
    *,
    panel: pd.DataFrame,
    blocks: pd.DataFrame,
    summary: pd.DataFrame,
    bootstrap: pd.DataFrame,
    full_days: pd.DataFrame,
    sampled_blocks_per_day: pd.Series,
    anchor: pd.Series,
    baseline_multiplier: float,
    central_rate: int,
) -> None:
    """Materialize the selected rate for equilibrium, replay, and reporting."""

    central_row = summary.loc[summary["floor_rate"].eq(central_rate)].iloc[0]
    central_panel = materialize_rate_panel(panel, central_rate)
    central_classes = summarize_decomposition(central_panel, "floor_class")
    central_classes["floor_class"] = pd.Categorical(
        central_classes["floor_class"],
        categories=FLOOR_CLASS_ORDER,
        ordered=True,
    )
    central_classes = central_classes.sort_values("floor_class").reset_index(drop=True)
    central_bootstrap = bootstrap.loc[
        bootstrap["floor_rate"].eq(central_rate)
    ].reset_index(drop=True)
    central_blocks = blocks[
        [
            "date",
            "block_number",
            f"charged_static_{central_rate}",
            f"charged_total_{central_rate}",
            f"bal_increment_{central_rate}",
        ]
    ].rename(
        columns={
            f"charged_static_{central_rate}": "charged_static_floor_gas",
            f"charged_total_{central_rate}": "charged_regular_gas_8279",
            f"bal_increment_{central_rate}": "incremental_data_gas_8279",
        }
    )
    weighted_bal_increment = weighted_sum(
        blocks[f"bal_increment_{central_rate}"],
        blocks["date"],
        full_days,
        sampled_blocks_per_day,
    )
    weighted_regular = weighted_sum(
        blocks[f"charged_total_{central_rate}"],
        blocks["date"],
        full_days,
        sampled_blocks_per_day,
    )
    affected = central_panel["affected_by_8279"]
    close_classes = central_panel["floor_class"].isin(FLOOR_CLASS_ORDER[:2])
    intervals = {
        "p05": float(central_row["m_data_block_p05"]),
        "p50": float(central_row["m_data_block_p50"]),
        "p95": float(central_row["m_data_block_p95"]),
    }
    multiplier_summary = {
        "start_date": "2026-02-01",
        "end_date_inclusive": "2026-05-31",
        "sampled_blocks": int(len(blocks)),
        "sampled_transactions": int(len(panel)),
        "full_anchor_blocks": int(full_days["block_count"].sum()),
        "floor_rate": central_rate,
        "applies_to_propagation_time_s": 3.0 if central_rate == 96 else None,
        "q_data_reference_per_block": float(anchor["q_data_per_block"]),
        "m_data_7976_7981_baseline": baseline_multiplier,
        "incremental_m_data_8131": float(
            central_row["m_data_without_bal"] - baseline_multiplier
        ),
        "incremental_m_data_8279": float(
            central_row["incremental_m_data_bal"]
        ),
        "m_data_8131_8279": float(central_row["m_data_block"]),
        "m_execution_current_eip8038": float(anchor["m_execution"]),
        "m_state_reused": float(anchor["m_state"]),
        "bootstrap_replications": int(central_bootstrap["replication"].nunique()),
        "bootstrap_p05_p95_conditional_on_7976_7981_baseline": {
            "m_data_8131_8279": intervals
        },
        "affected_transaction_fraction": float(affected.mean()),
        "runtime_bal_byte_share_carried_by_affected_transactions": float(
            central_panel.loc[affected, "bal_runtime_bytes_8279"].sum()
            / max(central_panel["bal_runtime_bytes_8279"].sum(), 1.0)
        ),
        "incremental_gas_per_weighted_block": float(
            weighted_bal_increment / full_days["block_count"].sum()
        ),
        "incremental_gas_share_of_regular_branch": float(
            weighted_bal_increment / max(weighted_regular, 1.0)
        ),
        "uplift_share_already_or_close_to_static_floor": float(
            central_panel.loc[close_classes, "incremental_data_gas_8279"].sum()
            / max(central_panel["incremental_data_gas_8279"].sum(), 1.0)
        ),
        "execution_path": "transaction-specific EIP-8038+EIP-2780, daily reconciled",
    }
    central_anchor = pd.DataFrame(
        [
            {
                "start_date": multiplier_summary["start_date"],
                "end_date_inclusive": multiplier_summary["end_date_inclusive"],
                "days": 120,
                "blocks": multiplier_summary["full_anchor_blocks"],
                "floor_rate": central_rate,
                "applies_to_propagation_time_s": (
                    3.0 if central_rate == 96 else None
                ),
                "base_fee_ref_wei": float(anchor["base_fee_ref_wei"]),
                "base_fee_ref_gwei": float(anchor["base_fee_ref_gwei"]),
                "q_execution_per_block": float(anchor["q_execution_per_block"]),
                "q_data_per_block": float(anchor["q_data_per_block"]),
                "q_state_per_block": float(anchor["q_state_per_block"]),
                "m_execution": float(anchor["m_execution"]),
                "m_data": float(central_row["m_data_block"]),
                "m_state": float(anchor["m_state"]),
                "m_data_7976_7981_baseline": baseline_multiplier,
                "incremental_m_data_8131": multiplier_summary[
                    "incremental_m_data_8131"
                ],
                "incremental_m_data_8279": multiplier_summary[
                    "incremental_m_data_8279"
                ],
            }
        ]
    )
    anchors_by_rate = pd.DataFrame(
        [
            {
                "start_date": multiplier_summary["start_date"],
                "end_date_inclusive": multiplier_summary["end_date_inclusive"],
                "days": 120,
                "blocks": multiplier_summary["full_anchor_blocks"],
                "floor_rate": int(rate_row.floor_rate),
                "base_fee_ref_wei": float(anchor["base_fee_ref_wei"]),
                "base_fee_ref_gwei": float(anchor["base_fee_ref_gwei"]),
                "q_execution_per_block": float(anchor["q_execution_per_block"]),
                "q_data_per_block": float(anchor["q_data_per_block"]),
                "q_state_per_block": float(anchor["q_state_per_block"]),
                "m_execution": float(anchor["m_execution"]),
                "m_data": float(rate_row.m_data_block),
                "m_state": float(anchor["m_state"]),
                "m_data_7976_7981_baseline": baseline_multiplier,
                "static_floor_change_from_64_reference": float(
                    rate_row.m_data_without_bal - baseline_multiplier
                ),
                "runtime_bal_contribution_8279": float(
                    rate_row.incremental_m_data_bal
                ),
            }
            for rate_row in summary.itertuples(index=False)
        ]
    )

    central_blocks.insert(0, "floor_rate", central_rate)
    central_classes.insert(0, "floor_rate", central_rate)
    write_csv(central_blocks, DATA / "eip8279_block_uplift.csv")
    write_csv(central_classes, DATA / "eip8279_floor_activation_by_class.csv")
    for group, suffix in [
        ("static_content_decile", "static_content_decile"),
        ("state_creating_status", "state_creating_status"),
        ("deployment_status", "contract_deployment"),
        ("transaction_type_label", "transaction_type"),
    ]:
        detail = summarize_decomposition(central_panel, group)
        detail.insert(0, "floor_rate", central_rate)
        write_csv(detail, DATA / f"eip8279_floor_activation_by_{suffix}.csv")
    write_csv(
        summarize_runtime_coverage(central_panel, central_rate),
        DATA / "state_creating_tx_runtime_component_coverage.csv",
    )
    write_csv(
        summarize_full_floor_coverage(central_panel, central_rate),
        DATA / "state_creating_tx_bal_floor_coverage.csv",
    )
    write_csv(central_bootstrap, DATA / "data_multiplier_bootstrap.csv")
    write_csv(central_anchor, DATA / "equilibrium_anchor_8279.csv")
    write_csv(anchors_by_rate, DATA / "equilibrium_anchor_by_floor_rate.csv")
    (DATA / "eip8279_data_multiplier.json").write_text(
        json.dumps(multiplier_summary, indent=2, sort_keys=True) + "\n"
    )


def make_multiplier_plot(summary: pd.DataFrame) -> None:
    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.titlesize": 16,
            "axes.labelsize": 14,
            "legend.fontsize": 13,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
        }
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        summary["floor_rate"],
        summary["m_data_block"],
        marker="o",
        linewidth=2.4,
        label="EIP-8131 + EIP-8279",
    )
    ax.fill_between(
        summary["floor_rate"],
        summary["m_data_block_p05"],
        summary["m_data_block_p95"],
        alpha=0.18,
        label="conditional 90% interval",
    )
    ax.plot(
        summary["floor_rate"],
        summary["m_data_without_bal"],
        marker="o",
        linewidth=2.1,
        label="static EIP-8131 floor only",
    )
    ax.axvline(REFERENCE_RATE, color="0.45", linestyle="--", linewidth=1.4)
    ax.set_xticks([rate for rate in (40, 50, 64, 72, 82, 89, 96) if rate in set(summary["floor_rate"])])
    ax.set_xlabel("floor price (gas per byte)")
    ax.set_ylabel("shared-fee data multiplier")
    ax.grid(alpha=0.3)
    ax.legend(frameon=True)
    fig.tight_layout()
    fig.savefig(PLOTS / "shared_fee_floor_rate_multiplier.png", dpi=180)
    plt.close(fig)


def make_binding_plot(summary: pd.DataFrame) -> None:
    plt.rcParams.update({"font.size": 14})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    axes[0].plot(
        summary["floor_rate"],
        100 * summary["static_floor_bound_tx_share"],
        marker="o",
        linewidth=2.2,
        label="static floor bound",
    )
    axes[0].plot(
        summary["floor_rate"],
        100 * summary["newly_bound_by_bal_tx_share"],
        marker="o",
        linewidth=2.2,
        label="newly bound by BAL",
    )
    axes[0].set_ylabel("share of transactions (%)")
    axes[0].legend(frameon=True)

    axes[1].plot(
        summary["floor_rate"],
        summary["incremental_m_data_bal"],
        marker="o",
        linewidth=2.2,
        color="#2ca02c",
    )
    axes[1].set_ylabel("BAL contribution to data multiplier")

    for ax in axes:
        ax.axvline(REFERENCE_RATE, color="0.45", linestyle="--", linewidth=1.4)
        ax.set_xticks([rate for rate in (40, 50, 64, 72, 82, 89, 96) if rate in set(summary["floor_rate"])])
        ax.set_xlabel("floor rate (gas per byte)")
        ax.grid(alpha=0.3)
    fig.tight_layout(w_pad=3.0)
    fig.savefig(PLOTS / "shared_fee_floor_rate_binding.png", dpi=180)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    rates = sorted(set(args.rates))
    if REFERENCE_RATE not in rates:
        raise ValueError("The selected rates must include the 64-gas reference")
    if any(rate <= 0 for rate in rates):
        raise ValueError("Floor rates must be positive")
    if args.central_rate not in rates:
        raise ValueError("The central rate must be included in --rates")

    panel = pd.read_parquet(DATA / "transaction_floor_panel_6000_blocks.parquet")
    sampled_blocks = pd.read_csv(
        ROOT / f"data/calibration_xatu_bal_runtime_8279_blocks_{TAG}.csv"
    )
    full_days = pd.read_csv(
        ROOT / "data/glamsterdam/anchor_accounting_panel_2026-02-01_2026-05-31.csv"
    )
    anchor = pd.read_csv(DATA / "equilibrium_anchor_8279.csv").iloc[0]
    panel["date"] = pd.to_datetime(panel["date"])
    sampled_blocks["date"] = pd.to_datetime(sampled_blocks["date"])
    full_days["date"] = pd.to_datetime(full_days["date"])

    blocks, arrays = aggregate_blocks(
        panel,
        sampled_blocks,
        rates,
        state_multiplier=float(anchor["m_state"]),
    )
    sampled_per_day = sampled_blocks.groupby("date").size()
    if len(sampled_per_day) != 120 or not sampled_per_day.eq(50).all():
        raise ValueError("Expected 50 sampled blocks on each of 120 days")

    denominator = float(full_days["data_gas_current"].sum())
    baseline_multiplier = float(anchor["m_data_7976_7981_baseline"])
    baseline_charged = weighted_sum(
        blocks["charged_baseline_7976_7981_64"],
        blocks["date"],
        full_days,
        sampled_per_day,
    )
    charged_reference = weighted_sum(
        blocks[f"charged_total_{REFERENCE_RATE}"],
        blocks["date"],
        full_days,
        sampled_per_day,
    )
    reference_multiplier = (
        baseline_multiplier + (charged_reference - baseline_charged) / denominator
    )
    transaction_day_weight = panel["date"].map(
        full_days.set_index("date")["block_count"] / sampled_per_day
    ).to_numpy(dtype=float)

    rows: list[dict[str, float | int]] = []
    for rate in rates:
        charged = weighted_sum(
            blocks[f"charged_total_{rate}"],
            blocks["date"],
            full_days,
            sampled_per_day,
        )
        bal_increment = weighted_sum(
            blocks[f"bal_increment_{rate}"],
            blocks["date"],
            full_days,
            sampled_per_day,
        )
        total_floor_uplift = weighted_sum(
            blocks[f"total_floor_uplift_{rate}"],
            blocks["date"],
            full_days,
            sampled_per_day,
        )
        payment_bal_increment = weighted_sum(
            blocks[f"payment_bal_increment_{rate}"],
            blocks["date"],
            full_days,
            sampled_per_day,
        )
        payment_total_floor_uplift = weighted_sum(
            blocks[f"payment_total_floor_uplift_{rate}"],
            blocks["date"],
            full_days,
            sampled_per_day,
        )
        m_data = baseline_multiplier + (charged - baseline_charged) / denominator
        tx = arrays[rate]
        total_tx_weight = float(transaction_day_weight.sum())
        static_bound = tx["static_floor_bound"]
        newly_bal_bound = ~static_bound & tx["total_floor_bound"]
        bal_uplift = tx["bal_increment"]
        bal_uplift_total = float(np.dot(transaction_day_weight, bal_uplift))
        deployed = panel["deployed_code_bytes_8279"].to_numpy(dtype=float) > 0
        state_creating = (
            panel["state_reference_gas_capped"].to_numpy(dtype=float) > 0
        )
        rows.append(
            {
                "floor_rate": rate,
                "m_data_block": m_data,
                "m_data_without_bal": m_data - bal_increment / denominator,
                "incremental_m_data_bal": bal_increment / denominator,
                "change_in_m_data_from_64": m_data - reference_multiplier,
                "total_floor_uplift_equivalent": total_floor_uplift / denominator,
                "payment_floor_uplift_equivalent": (
                    payment_total_floor_uplift / denominator
                ),
                "payment_bal_increment_equivalent": (
                    payment_bal_increment / denominator
                ),
                "static_floor_bound_tx_share": float(
                    transaction_day_weight[static_bound].sum() / total_tx_weight
                ),
                "newly_bound_by_bal_tx_share": float(
                    transaction_day_weight[newly_bal_bound].sum() / total_tx_weight
                ),
                "bal_affected_tx_share": float(
                    transaction_day_weight[tx["bal_affected"]].sum()
                    / total_tx_weight
                ),
                "payment_floor_bound_tx_share": float(
                    transaction_day_weight[tx["payment_floor_bound"]].sum()
                    / total_tx_weight
                ),
                "deployment_share_of_bal_uplift": float(
                    np.dot(transaction_day_weight[deployed], bal_uplift[deployed])
                    / max(bal_uplift_total, 1.0)
                ),
                "state_creating_share_of_bal_uplift": float(
                    np.dot(
                        transaction_day_weight[state_creating],
                        bal_uplift[state_creating],
                    )
                    / max(bal_uplift_total, 1.0)
                ),
            }
        )

    summary = pd.DataFrame(rows)
    bootstrap = bootstrap_multipliers(
        blocks,
        full_days,
        rates,
        baseline_multiplier,
        replications=args.bootstrap,
    )
    if bootstrap.empty:
        summary["m_data_block_p05"] = summary["m_data_block"]
        summary["m_data_block_p50"] = summary["m_data_block"]
        summary["m_data_block_p95"] = summary["m_data_block"]
    else:
        intervals = bootstrap.groupby("floor_rate")["m_data_block"].quantile(
            [0.05, 0.50, 0.95]
        ).unstack()
        intervals.columns = ["m_data_block_p05", "m_data_block_p50", "m_data_block_p95"]
        summary = summary.merge(
            intervals.reset_index(), on="floor_rate", validate="one_to_one"
        )

    reference_row = summary.loc[summary["floor_rate"].eq(REFERENCE_RATE)].iloc[0]
    if not np.isclose(
        reference_row["m_data_block"], reference_multiplier, rtol=0, atol=1e-12
    ):
        raise AssertionError("The 64-gas multiplier does not reconcile")
    if not summary["m_data_block"].is_monotonic_increasing:
        raise AssertionError("The block multiplier must be monotone in the floor rate")
    if not summary["incremental_m_data_bal"].is_monotonic_increasing:
        raise AssertionError("The BAL increment must be monotone in the floor rate")

    DATA.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    write_csv(summary, DATA / "floor_rate_multiplier_sweep.csv")
    write_csv(bootstrap, DATA / "floor_rate_multiplier_bootstrap.csv")
    write_csv(blocks, DATA / "floor_rate_block_accounting.csv")
    write_csv(
        floor_activation_decomposition(panel, rates),
        DATA / "floor_rate_activation_by_class.csv",
    )
    write_central_outputs(
        panel=panel,
        blocks=blocks,
        summary=summary,
        bootstrap=bootstrap,
        full_days=full_days,
        sampled_blocks_per_day=sampled_per_day,
        anchor=anchor,
        baseline_multiplier=baseline_multiplier,
        central_rate=args.central_rate,
    )
    make_multiplier_plot(summary)
    make_binding_plot(summary)

    display = summary[
        [
            "floor_rate",
            "m_data_block",
            "m_data_block_p05",
            "m_data_block_p95",
            "incremental_m_data_bal",
            "static_floor_bound_tx_share",
            "newly_bound_by_bal_tx_share",
            "bal_affected_tx_share",
        ]
    ].copy()
    print(display.to_string(index=False, float_format=lambda value: f"{value:.6f}"))


if __name__ == "__main__":
    main()
