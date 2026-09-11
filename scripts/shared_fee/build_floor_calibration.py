"""Build the cached 120-day EIP-8131/EIP-8279 data multiplier calibration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shared_fee.panel import (  # noqa: E402
    KEYS,
    aggregate_sample_blocks,
    build_transaction_floor_panel,
)
from shared_fee.floor_accounting import (  # noqa: E402
    ACCOUNT_WRITE_8038,
    COLD_ACCOUNT_ACCESS_8038,
    COLD_STORAGE_ACCESS_8038,
    CREATE_ACCESS_8038,
    FLOOR_GAS_PER_BYTE,
    STORAGE_WRITE_8038,
)


TAG = "2026-02-01_2026-06-01"
OUT = ROOT / "data/shared_fee"


def write_atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def weighted_totals(block: pd.DataFrame, full_days: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "current_data_gas_proxy",
        "incremental_data_gas_8131",
        "incremental_data_gas_8279",
        "incremental_data_gas_8131_8279",
        "bal_runtime_bytes_8279",
    ]
    sampled = block.groupby("date", as_index=False).agg(
        sampled_blocks=("block_number", "size"),
        **{column: (column, "mean") for column in columns},
    )
    days = full_days.copy()
    days["date"] = pd.to_datetime(days["date"])
    merged = days.merge(sampled, on="date", how="inner", validate="one_to_one")
    if len(merged) != 120 or not merged["sampled_blocks"].eq(50).all():
        raise ValueError("Expected 50 sampled blocks on each of 120 days")
    for column in columns:
        merged[f"weighted_{column}"] = merged[column] * merged["block_count"]
    return merged


def bootstrap_multiplier(
    block: pd.DataFrame,
    full_days: pd.DataFrame,
    baseline_multiplier: float,
    *,
    replications: int = 400,
    seed: int = 8_279,
) -> pd.DataFrame:
    """Day-block bootstrap preserving the 50-block daily sample design."""

    rng = np.random.default_rng(seed)
    full = full_days.copy()
    full["date"] = pd.to_datetime(full["date"])
    by_day = {date: frame for date, frame in block.groupby("date")}
    dates = full["date"].to_numpy()
    blocks_by_date = dict(zip(full["date"], full["block_count"], strict=True))
    denominator_by_date = dict(
        zip(full["date"], full["data_gas_current"], strict=True)
    )
    rows = []
    for replication in range(replications):
        sampled_dates = rng.choice(dates, size=len(dates), replace=True)
        denominator = 0.0
        increment_8131 = 0.0
        increment_8279 = 0.0
        for raw_date in sampled_dates:
            date = pd.Timestamp(raw_date)
            day = by_day[date]
            draw = day.iloc[rng.integers(0, len(day), size=len(day))]
            weight = float(blocks_by_date[date])
            denominator += float(denominator_by_date[date])
            increment_8131 += (
                float(draw["incremental_data_gas_8131"].mean()) * weight
            )
            increment_8279 += (
                float(draw["incremental_data_gas_8279"].mean()) * weight
            )
        delta_8131 = increment_8131 / denominator
        delta_8279 = increment_8279 / denominator
        rows.append(
            {
                "replication": replication,
                "incremental_m_data_8131": delta_8131,
                "incremental_m_data_8279": delta_8279,
                "incremental_m_data_8131_8279": delta_8131 + delta_8279,
                "m_data_8131_8279": (
                    float(baseline_multiplier) + delta_8131 + delta_8279
                ),
            }
        )
    return pd.DataFrame(rows)


FLOOR_CLASS_ORDER = [
    "already floor-bound under EIP-8131",
    "close to static floor; pushed across by runtime BAL",
    "newly floor-bound primarily because of deployed code",
    "newly floor-bound through other non-code BAL",
    "unaffected",
]


def assign_floor_classes(
    panel: pd.DataFrame, near_threshold: float = 0.10
) -> pd.DataFrame:
    """Assign the five mutually exclusive EIP-8279 activation classes."""

    out = panel.copy()
    affected = out["incremental_data_gas_8279"].gt(1e-8)
    already = affected & out["floor_bound_8131"]
    newly = affected & ~out["floor_bound_8131"]
    close = newly & out["headroom_ratio_8131"].le(near_threshold)
    floor_without_code = (
        out["floor_gas_8279"]
        - FLOOR_GAS_PER_BYTE * out["deployed_code_bytes_8279"]
    )
    code_pivotal = (
        newly
        & ~close
        & out["deployed_code_bytes_8279"].gt(0)
        & floor_without_code.le(out["execution_gas_for_floor"])
    )
    other = newly & ~close & ~code_pivotal
    out["floor_class"] = np.select(
        [already, close, code_pivotal, other],
        FLOOR_CLASS_ORDER[:4],
        default=FLOOR_CLASS_ORDER[4],
    )
    out["affected_by_8279"] = affected
    return out


def summarize_decomposition(
    panel: pd.DataFrame, group: str, output_name: str | None = None
) -> pd.DataFrame:
    """Aggregate transaction, BAL-byte, and gas shares by one classification."""

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
        grouped["runtime_bal_bytes"] / max(total_runtime_bal, 1)
    )
    grouped["incremental_gas_share"] = (
        grouped["incremental_data_gas"] / max(total_uplift, 1)
    )
    grouped["incremental_gas_as_share_of_group_regular_branch"] = (
        grouped["incremental_data_gas"] / grouped["regular_branch_gas"].clip(lower=1)
    )
    grouped["incremental_gas_as_share_of_all_regular_branch"] = (
        grouped["incremental_data_gas"] / max(total_regular, 1)
    )
    return grouped


def classify_floor(panel: pd.DataFrame, near_threshold: float = 0.10) -> pd.DataFrame:
    out = assign_floor_classes(panel, near_threshold=near_threshold)
    grouped = summarize_decomposition(out, "floor_class")
    grouped["floor_class"] = pd.Categorical(
        grouped["floor_class"], categories=FLOOR_CLASS_ORDER, ordered=True
    )
    return grouped.sort_values("floor_class").reset_index(drop=True)


def floor_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarize how much EIP-8279 floor gas is covered by execution gas."""

    out = panel.copy()
    out["state_creating"] = out["state_reference_gas_capped"].gt(0)
    out["coverage_ratio"] = (
        out["execution_gas_for_floor"] / out["floor_gas_8279"].clip(lower=1)
    )
    out["uncovered_floor_gas"] = (
        out["floor_gas_8279"] - out["execution_gas_for_floor"]
    ).clip(lower=0)
    groups: list[tuple[str, pd.Series]] = [
        ("all transactions", pd.Series(True, index=out.index)),
        ("state-creating transactions", out["state_creating"]),
        ("transactions without state creation", ~out["state_creating"]),
    ]
    rows = []
    total_bal = float(out["bal_floor_bytes_8279"].sum())
    total_uplift = float(out["incremental_data_gas_8279"].sum())
    for label, mask in groups:
        selected = out.loc[mask]
        under = selected["coverage_ratio"].lt(1)
        rows.append(
            {
                "transaction_class": label,
                "transactions": len(selected),
                "transaction_share": len(selected) / len(out),
                "transactions_with_bal": int(
                    selected["bal_floor_bytes_8279"].gt(0).sum()
                ),
                "coverage_ratio_median": float(selected["coverage_ratio"].median()),
                "coverage_ratio_p05": float(selected["coverage_ratio"].quantile(0.05)),
                "coverage_ratio_p95": float(selected["coverage_ratio"].quantile(0.95)),
                "fraction_below_one": float(under.mean()),
                "bal_floor_bytes": float(selected["bal_floor_bytes_8279"].sum()),
                "bal_byte_share_of_all": float(
                    selected["bal_floor_bytes_8279"].sum() / max(total_bal, 1)
                ),
                "bal_byte_share_below_one": float(
                    selected.loc[under, "bal_floor_bytes_8279"].sum()
                    / max(selected["bal_floor_bytes_8279"].sum(), 1)
                ),
                "incremental_data_gas_8279": float(
                    selected["incremental_data_gas_8279"].sum()
                ),
                "incremental_gas_share_of_all": float(
                    selected["incremental_data_gas_8279"].sum()
                    / max(total_uplift, 1)
                ),
                "uncovered_floor_gas": float(selected["uncovered_floor_gas"].sum()),
            }
        )
    return pd.DataFrame(rows)


def attach_runtime_component_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """Compare runtime BAL floor gas with its paired regular execution charges."""

    out = panel.copy()
    out["noncode_runtime_bal_bytes_8279"] = (
        out["bal_runtime_bytes_8279"] - out["deployed_code_bytes_8279"]
    )
    out["noncode_runtime_bal_floor_gas"] = (
        FLOOR_GAS_PER_BYTE * out["noncode_runtime_bal_bytes_8279"]
    )
    # Current EIP-8038 charges paired with the reconstructed runtime events.
    # Cold account access is 3,000 gas; cold storage access remains 2,100.
    out["paired_noncode_execution_gas"] = (
        COLD_ACCOUNT_ACCESS_8038 * out["cold_account_accesses"]
        + COLD_STORAGE_ACCESS_8038 * out["cold_storage_accesses"]
        + STORAGE_WRITE_8038 * out["storage_value_entries_observed"]
        + ACCOUNT_WRITE_8038 * out["positive_value_calls"]
        + 5_000 * out["positive_value_selfdestructs"]
        + CREATE_ACCESS_8038 * out["internal_creates"]
    )
    out["code_hash_execution_gas"] = 6 * np.ceil(
        out["deployed_code_bytes_8279"] / 32
    )
    out["paired_all_runtime_execution_gas"] = (
        out["paired_noncode_execution_gas"] + out["code_hash_execution_gas"]
    )
    out["all_runtime_bal_floor_gas"] = (
        FLOOR_GAS_PER_BYTE * out["bal_runtime_bytes_8279"]
    )
    out["noncode_runtime_covered"] = out["paired_noncode_execution_gas"].ge(
        out["noncode_runtime_bal_floor_gas"]
    )
    out["all_runtime_covered"] = out["paired_all_runtime_execution_gas"].ge(
        out["all_runtime_bal_floor_gas"]
    )
    return out


def summarize_runtime_component_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    carriers = panel.loc[panel["bal_runtime_bytes_8279"].gt(0)].copy()
    state = carriers["state_reference_gas_capped"].gt(0)
    rows = []
    for label, mask in [
        ("all BAL-carrying transactions", pd.Series(True, index=carriers.index)),
        ("state-creating BAL-carrying transactions", state),
        ("BAL-carrying transactions without state creation", ~state),
    ]:
        selected = carriers.loc[mask]
        all_failure = ~selected["all_runtime_covered"]
        rows.append(
            {
                "transaction_class": label,
                "transactions": len(selected),
                "runtime_bal_bytes": int(selected["bal_runtime_bytes_8279"].sum()),
                "deployed_code_bytes": int(selected["deployed_code_bytes_8279"].sum()),
                "noncode_floor_gas": int(
                    selected["noncode_runtime_bal_floor_gas"].sum()
                ),
                "paired_noncode_execution_gas": int(
                    selected["paired_noncode_execution_gas"].sum()
                ),
                "noncode_coverage_ratio": float(
                    selected["paired_noncode_execution_gas"].sum()
                    / max(selected["noncode_runtime_bal_floor_gas"].sum(), 1)
                ),
                "noncode_coverage_failures": int(
                    (~selected["noncode_runtime_covered"]).sum()
                ),
                "all_runtime_coverage_ratio": float(
                    selected["paired_all_runtime_execution_gas"].sum()
                    / max(selected["all_runtime_bal_floor_gas"].sum(), 1)
                ),
                "all_runtime_coverage_failures": int(all_failure.sum()),
                "runtime_bal_byte_share_in_all_coverage_failures": float(
                    selected.loc[all_failure, "bal_runtime_bytes_8279"].sum()
                    / max(selected["bal_runtime_bytes_8279"].sum(), 1)
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tx = pd.read_parquet(OUT / "transaction_inputs_6000_blocks.parquet")
    static = pd.read_parquet(
        ROOT / f"data/calibration_rpc_static_data_transactions_{TAG}.parquet"
    )
    carriers = pd.read_parquet(
        ROOT / f"data/calibration_xatu_bal_runtime_8279_carrier_panel_{TAG}.parquet"
    )
    execution_components = pd.read_parquet(
        OUT / "execution_repricing_components_6000_blocks.parquet"
    )
    runtime_components = pd.read_parquet(
        OUT / "runtime_components_6000_blocks.parquet"
    )
    sampled_blocks = pd.read_csv(
        ROOT / f"data/calibration_xatu_bal_runtime_8279_blocks_{TAG}.csv"
    )
    daily_execution = pd.read_csv(
        OUT / f"execution_repricing_daily_eip8038_current_{TAG}.csv"
    )
    full_days = pd.read_csv(
        ROOT / "data/glamsterdam/anchor_accounting_panel_2026-02-01_2026-05-31.csv"
    )
    glam_anchor = pd.read_csv(ROOT / "data/glamsterdam/equilibrium_anchor.csv").iloc[0]
    m_execution_current = float(
        daily_execution["execution_8038_2780_refund_corrected"].sum()
        / daily_execution["execution_current"].sum()
    )

    panel = build_transaction_floor_panel(
        transaction_inputs=tx,
        static_content=static,
        carrier_runtime=carriers,
        execution_components=execution_components,
        sampled_blocks=sampled_blocks,
        daily_execution=daily_execution,
    )
    runtime_components["tx_hash"] = runtime_components["tx_hash"].astype(str)
    if runtime_components.duplicated(KEYS).any():
        raise ValueError("Runtime component input contains duplicate transactions")
    runtime_components = runtime_components.drop(columns="bal_runtime_bytes_8279")
    panel = panel.merge(
        runtime_components,
        on=KEYS,
        how="left",
        validate="one_to_one",
    )
    runtime_value_columns = [
        column for column in runtime_components if column not in KEYS
    ]
    panel[runtime_value_columns] = panel[runtime_value_columns].fillna(0)
    panel = attach_runtime_component_coverage(panel)
    classified = assign_floor_classes(panel)
    # Static content has many ties (especially zero-byte transfers). Use a
    # deterministic transaction-order tie break so the requested deciles have
    # equal counts; the report states this convention explicitly.
    classified["static_content_decile"] = pd.qcut(
        classified["static_data_8131_bytes"].rank(method="first"),
        10,
        labels=[f"D{value}" for value in range(1, 11)],
    )
    classified["state_creating_status"] = np.where(
        classified["state_reference_gas_capped"].gt(0),
        "state-creating",
        "no state creation",
    )
    has_code = classified["deployed_code_bytes_8279"].gt(0)
    classified["deployment_status"] = np.select(
        [
            ~classified["has_recipient"].astype(bool) & has_code,
            classified["has_recipient"].astype(bool) & has_code,
            ~classified["has_recipient"].astype(bool) & ~has_code,
        ],
        [
            "top-level deployment observed",
            "internal deployment observed",
            "contract creation without deployed code",
        ],
        default="no deployment observed",
    )
    classified["transaction_type_label"] = classified["transaction_type"].map(
        lambda value: f"type {int(value)}"
    )
    block = aggregate_sample_blocks(panel, sampled_blocks)
    weighted = weighted_totals(block, full_days)
    reference = float(full_days["data_gas_current"].sum())
    baseline_7976_7981 = float(glam_anchor["m_data"])
    incremental_8131 = float(
        weighted["weighted_incremental_data_gas_8131"].sum() / reference
    )
    incremental_8279 = float(
        weighted["weighted_incremental_data_gas_8279"].sum() / reference
    )
    m_8279 = baseline_7976_7981 + incremental_8131 + incremental_8279

    boot = bootstrap_multiplier(
        block, full_days, baseline_multiplier=baseline_7976_7981
    )
    intervals = {
        column: {
            "p05": float(boot[column].quantile(0.05)),
            "p50": float(boot[column].quantile(0.50)),
            "p95": float(boot[column].quantile(0.95)),
        }
        for column in [
            "incremental_m_data_8131",
            "incremental_m_data_8279",
            "incremental_m_data_8131_8279",
            "m_data_8131_8279",
        ]
    }
    summary = {
        "start_date": "2026-02-01",
        "end_date_inclusive": "2026-05-31",
        "sampled_blocks": int(len(block)),
        "sampled_nonempty_blocks": int(block["transactions"].gt(0).sum()),
        "sampled_transactions": int(len(panel)),
        "full_anchor_blocks": int(full_days["block_count"].sum()),
        "q_data_reference_per_block": float(glam_anchor["q_data_per_block"]),
        "m_data_7976_7981_baseline": baseline_7976_7981,
        "incremental_m_data_8131": incremental_8131,
        "incremental_m_data_8279": incremental_8279,
        "m_data_8131_8279": m_8279,
        "m_data_glamsterdam_7976_7981": float(glam_anchor["m_data"]),
        "m_execution_current_eip8038": m_execution_current,
        "m_state_reused": float(glam_anchor["m_state"]),
        "bootstrap_replications": int(len(boot)),
        "bootstrap_p05_p95_conditional_on_7976_7981_baseline": intervals,
        "execution_path": "transaction-specific EIP-8038+EIP-2780, daily reconciled",
    }
    class_summary = classify_floor(panel)
    runtime_coverage = summarize_runtime_component_coverage(panel)
    affected = classified["affected_by_8279"]
    already_or_close = classified["floor_class"].isin(FLOOR_CLASS_ORDER[:2])
    summary.update(
        {
            "near_static_floor_threshold": 0.10,
            "affected_transaction_fraction": float(affected.mean()),
            "runtime_bal_byte_share_carried_by_affected_transactions": float(
                classified.loc[affected, "bal_runtime_bytes_8279"].sum()
                / classified["bal_runtime_bytes_8279"].sum()
            ),
            "incremental_gas_per_sampled_block": float(
                classified["incremental_data_gas_8279"].sum() / len(block)
            ),
            "incremental_gas_share_of_regular_branch": float(
                classified["incremental_data_gas_8279"].sum()
                / classified["charged_regular_gas_8279"].sum()
            ),
            "uplift_share_already_or_close_to_static_floor": float(
                classified.loc[already_or_close, "incremental_data_gas_8279"].sum()
                / classified["incremental_data_gas_8279"].sum()
            ),
        }
    )

    anchor = pd.DataFrame(
        [
            {
                "start_date": summary["start_date"],
                "end_date_inclusive": summary["end_date_inclusive"],
                "days": 120,
                "blocks": summary["full_anchor_blocks"],
                "base_fee_ref_wei": float(glam_anchor["base_fee_ref_wei"]),
                "base_fee_ref_gwei": float(glam_anchor["base_fee_ref_gwei"]),
                "q_execution_per_block": float(glam_anchor["q_execution_per_block"]),
                "q_data_per_block": float(glam_anchor["q_data_per_block"]),
                "q_state_per_block": float(glam_anchor["q_state_per_block"]),
                "m_execution": m_execution_current,
                "m_data": m_8279,
                "m_state": float(glam_anchor["m_state"]),
                "m_data_7976_7981_baseline": baseline_7976_7981,
                "incremental_m_data_8131": incremental_8131,
                "incremental_m_data_8279": incremental_8279,
            }
        ]
    )

    compact_columns = [
        *KEYS,
        "date",
        "transaction_type",
        "receipt_gas_used",
        "static_data_8131_bytes",
        "bal_runtime_bytes_8279",
        "bal_floor_bytes_8279",
        "state_reference_gas_capped",
        "execution_reference_gas",
        "intrinsic_execution_base_2780",
        "execution_gas_for_floor_daily_proxy",
        "access_list_data_gas_7981",
        "execution_gas_for_floor",
        "floor_gas_7976_7981",
        "floor_gas_8131",
        "floor_gas_8279",
        "incremental_data_gas_8131",
        "incremental_data_gas_8279",
        "incremental_data_gas_8131_8279",
        "floor_bound_7976_7981",
        "floor_bound_8131",
        "floor_bound_8279",
        "newly_floor_bound_8279",
        "headroom_ratio_8131",
        "deployed_code_bytes_8279",
        "noncode_runtime_bal_bytes_8279",
        "noncode_runtime_bal_floor_gas",
        "paired_noncode_execution_gas",
        "paired_all_runtime_execution_gas",
        "all_runtime_bal_floor_gas",
        "noncode_runtime_covered",
        "all_runtime_covered",
        "floor_class",
        "affected_by_8279",
        "static_content_decile",
        "state_creating_status",
        "deployment_status",
        "transaction_type_label",
    ]
    classified[compact_columns].to_parquet(
        OUT / "transaction_floor_panel_6000_blocks.parquet", index=False
    )
    write_atomic_csv(block, OUT / "eip8279_block_uplift.csv")
    write_atomic_csv(class_summary, OUT / "eip8279_floor_activation_by_class.csv")
    write_atomic_csv(
        summarize_decomposition(classified, "static_content_decile"),
        OUT / "eip8279_floor_activation_by_static_content_decile.csv",
    )
    write_atomic_csv(
        summarize_decomposition(classified, "state_creating_status"),
        OUT / "eip8279_floor_activation_by_state_creating_status.csv",
    )
    write_atomic_csv(
        summarize_decomposition(classified, "deployment_status"),
        OUT / "eip8279_floor_activation_by_contract_deployment.csv",
    )
    write_atomic_csv(
        summarize_decomposition(classified, "transaction_type_label"),
        OUT / "eip8279_floor_activation_by_transaction_type.csv",
    )
    write_atomic_csv(
        floor_coverage(panel), OUT / "state_creating_tx_bal_floor_coverage.csv"
    )
    write_atomic_csv(
        runtime_coverage,
        OUT / "state_creating_tx_runtime_component_coverage.csv",
    )
    write_atomic_csv(boot, OUT / "data_multiplier_bootstrap.csv")
    write_atomic_csv(anchor, OUT / "equilibrium_anchor_8279.csv")
    (OUT / "eip8279_data_multiplier.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
