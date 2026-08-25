"""Build a contiguous per-block panel of primitive resource activity.

Phase 1 of the empirical block-shock workstream. The 6,000-block calibration
sample is deliberately spaced (median gap ~102 blocks), so it identifies
within-day dispersion but not block-to-block persistence. Every dynamic metric
that depends on serial structure -- fee volatility, longest limit-hit run,
weekly maximum spike, recovery time -- needs contiguous blocks instead.

This pulls only the cheap fields: block headers, transaction-level calldata and
receipt gas, and the state-creation diff counts. It does not touch
`canonical_execution_transaction_structlog_agg` or `canonical_execution_traces`,
which are what make the EIP-8279 runtime-BAL reconstruction expensive. The
access-composition residual a_t is Phase 2 and is sized from what this shows.

Usage:
    python3 scripts/build_contiguous_block_panel.py --start 2026-05-25 --days 1
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NETWORK = "mainnet"
DEFAULT_STATE_CALIBRATION = PROJECT_ROOT / (
    "data/calibration_state_access_auth_daily_rates_2026-02-01_2026-06-01.csv"
)


def allocate_weighted_with_caps(
    total: float,
    weights: np.ndarray,
    capacities: np.ndarray,
) -> np.ndarray:
    """Allocate a calibrated daily total without exceeding block gas budgets."""

    weights = np.asarray(weights, dtype=float)
    remaining_capacity = np.asarray(capacities, dtype=float).clip(min=0.0)
    allocation = np.zeros_like(remaining_capacity)
    remaining = float(total)
    tolerance = max(1e-7, 1e-12 * max(1.0, remaining))
    if remaining < -tolerance or not np.isfinite(remaining):
        raise ValueError("allocation total must be finite and non-negative")
    if remaining > remaining_capacity.sum() + tolerance:
        raise ValueError("calibrated state total exceeds the day's gas budget")

    while remaining > tolerance:
        active = remaining_capacity > tolerance
        if not active.any():
            raise ValueError("calibrated state allocation exhausted block capacity")
        active_weights = np.where(active, weights.clip(min=0.0), 0.0)
        if active_weights.sum() <= 0:
            active_weights = np.where(active, remaining_capacity, 0.0)
        proposal = remaining * active_weights / active_weights.sum()
        saturated = active & (proposal >= remaining_capacity - tolerance)
        if not saturated.any():
            allocation += proposal
            remaining = 0.0
            break
        allocation[saturated] += remaining_capacity[saturated]
        remaining -= float(remaining_capacity[saturated].sum())
        remaining_capacity[saturated] = 0.0

    return allocation


def client():
    load_dotenv(PROJECT_ROOT / ".env")
    missing = [k for k in ("CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_RAW_HOST", "clickhouse-raw.xatu.ethpandaops.io"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,
    )


def resolve_range(conn, start_ts, end_ts):
    df = conn.query_df(
        """
        SELECT min(block_number) AS lo, max(block_number) AS hi, count() AS blocks
        FROM default.canonical_execution_block FINAL
        WHERE meta_network_name = {network:String}
          AND block_date_time >= parseDateTime64BestEffort({start_ts:String})
          AND block_date_time <  parseDateTime64BestEffort({end_ts:String})
        """,
        parameters={"network": NETWORK, "start_ts": start_ts, "end_ts": end_ts},
        settings={"max_execution_time": 300},
    )
    return int(df.loc[0, "lo"]), int(df.loc[0, "hi"]), int(df.loc[0, "blocks"])


HEADERS = """
    SELECT block_number,
           any(block_date_time)     AS block_date_time,
           any(gas_used)            AS gas_used,
           any(gas_limit)           AS gas_limit,
           any(base_fee_per_gas)    AS base_fee_per_gas
    FROM default.canonical_execution_block FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
    GROUP BY block_number
"""

# Charged calldata gas under current rules, including the EIP-7623 floor when
# the transaction-level floor proxy binds, plus the receipt gas needed to
# separate execution from data. The dynamic source window is post-Pectra.
CALLDATA = """
    SELECT block_number,
           count()                                            AS tx_count,
           sum(toUInt64(gas_used))                            AS receipt_gas_used,
           sum(toUInt64(n_input_zero_bytes))                  AS calldata_zero_bytes,
           sum(toUInt64(n_input_nonzero_bytes))               AS calldata_nonzero_bytes,
           sum(toUInt64(4 * n_input_zero_bytes + 16 * n_input_nonzero_bytes))
                                                              AS standard_calldata_gas,
           sum(
               if(
                   greatest(toInt64(gas_used) - 21000, 0)
                       <= toInt64(10 * (n_input_zero_bytes + 4 * n_input_nonzero_bytes))
                   AND (n_input_zero_bytes + n_input_nonzero_bytes) > 0,
                   toInt64(6 * (n_input_zero_bytes + 4 * n_input_nonzero_bytes)),
                   0
               )
           )                                                  AS eip7623_floor_uplift
    FROM default.canonical_execution_transaction FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
    GROUP BY block_number
"""

TYPE4_TRANSACTIONS = """
    SELECT block_number,
           countIf(type = 4) AS type4_tx_count
    FROM default.execution_transaction FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
    GROUP BY block_number
"""

# Persistent state creation: slots moving off zero, plus deployed contract code.
STORAGE = """
    SELECT block_number,
           uniqExact(tuple(lower(address), lower(slot))) AS new_storage_slots
    FROM default.canonical_execution_storage_diffs FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
      AND lower(from_value) = '0x0000000000000000000000000000000000000000000000000000000000000000'
      AND lower(to_value) != '0x0000000000000000000000000000000000000000000000000000000000000000'
    GROUP BY block_number
"""

CONTRACTS = """
    SELECT block_number,
           count()                       AS new_contract_accounts,
           sum(toUInt64(n_code_bytes))   AS code_bytes
    FROM default.canonical_execution_contracts FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
    GROUP BY block_number
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--out-dir", default="data/contiguous")
    parser.add_argument(
        "--state-calibration",
        type=Path,
        default=DEFAULT_STATE_CALIBRATION,
        help=(
            "Daily RPC-sample means for new accounts and delegation indicators. "
            "These supply expected per-block contributions that are unavailable "
            "from the cheap Xatu block pull."
        ),
    )
    args = parser.parse_args()

    start_ts = f"{args.start} 00:00:00"
    end_ts = (pd.Timestamp(args.start) + pd.Timedelta(days=args.days)).strftime("%Y-%m-%d 00:00:00")

    conn = client()
    lo, hi, expected = resolve_range(conn, start_ts, end_ts)
    print(f"range {args.start} +{args.days}d -> blocks {lo}..{hi}  ({expected:,} canonical)")

    params = {"network": NETWORK, "lo": lo, "hi": hi}
    frames = {}
    for name, sql in (("headers", HEADERS), ("calldata", CALLDATA),
                      ("type4", TYPE4_TRANSACTIONS),
                      ("storage", STORAGE), ("contracts", CONTRACTS)):
        t0 = time.time()
        frames[name] = conn.query_df(sql, parameters=params, settings={"max_execution_time": 1800})
        print(f"  {name:10s} {len(frames[name]):>8,} rows  {time.time() - t0:6.1f}s")

    panel = frames["headers"]
    for name in ("calldata", "type4", "storage", "contracts"):
        panel = panel.merge(frames[name], on="block_number", how="left")
    panel = panel.sort_values("block_number").reset_index(drop=True)
    panel[["tx_count", "type4_tx_count", "receipt_gas_used", "calldata_zero_bytes", "calldata_nonzero_bytes",
           "standard_calldata_gas", "eip7623_floor_uplift", "new_storage_slots",
           "new_contract_accounts", "code_bytes"]] = panel[[
        "tx_count", "type4_tx_count", "receipt_gas_used", "calldata_zero_bytes", "calldata_nonzero_bytes",
        "standard_calldata_gas", "eip7623_floor_uplift", "new_storage_slots",
        "new_contract_accounts", "code_bytes"]].fillna(0)

    state_rates = pd.read_csv(args.state_calibration)
    required_rates = {
        "date",
        "new_accounts_per_block",
        "new_delegation_indicators_per_block",
    }
    missing_rates = required_rates - set(state_rates.columns)
    if missing_rates:
        raise ValueError(
            f"state calibration is missing columns: {sorted(missing_rates)}"
        )
    state_rates = state_rates.loc[:, sorted(required_rates)].copy()
    state_rates["date"] = pd.to_datetime(state_rates["date"]).dt.normalize()
    if state_rates["date"].duplicated().any():
        raise ValueError("state calibration contains duplicate dates")
    panel["date"] = pd.to_datetime(panel["block_date_time"]).dt.normalize()
    panel = panel.merge(state_rates, on="date", how="left", validate="many_to_one")
    calibration_columns = [
        "new_accounts_per_block",
        "new_delegation_indicators_per_block",
    ]
    if panel[calibration_columns].isna().any().any():
        missing_dates = panel.loc[
            panel[calibration_columns].isna().any(axis=1), "date"
        ].dt.strftime("%Y-%m-%d").unique()
        raise ValueError(
            "state calibration does not cover panel dates: "
            + ", ".join(missing_dates)
        )

    daily_txs = panel.groupby("date")["tx_count"].transform("sum")
    if (daily_txs <= 0).any():
        raise ValueError("a panel day contains no transactions")

    # Preserve each day's RPC-calibrated totals while using cheap block-level
    # activity to allocate the unobserved components. Account creation is routed
    # in proportion to all transactions; delegation indicators are routed in
    # proportion to type-4 transactions. A capacity-constrained allocation
    # prevents sampled mean counts from assigning more state gas to a low-gas
    # block than that block could have carried. Delegation gas is routed first
    # because type-4 activity is its more specific observable proxy.
    panel["base_state_creation_gas"] = (
        20_000 * panel.new_storage_slots + 200 * panel.code_bytes
    )
    panel["cal_new_accounts"] = 0.0
    panel["cal_new_delegation_indicators"] = 0.0
    for _, positions in panel.groupby("date", sort=False).indices.items():
        positions = np.asarray(positions, dtype=int)
        day = panel.iloc[positions]
        capacity = (
            day["gas_used"].fillna(0)
            - day["standard_calldata_gas"]
            - day["eip7623_floor_uplift"]
            - day["base_state_creation_gas"]
        ).to_numpy(dtype=float)
        if (capacity < -1e-7).any():
            raise ValueError("observed storage/code state gas exceeds a block gas budget")
        capacity = capacity.clip(min=0.0)
        n_blocks = float(len(day))
        delegation_gas = allocate_weighted_with_caps(
            float(day["new_delegation_indicators_per_block"].iloc[0])
            * n_blocks
            * 12_500,
            day["type4_tx_count"].to_numpy(dtype=float),
            capacity,
        )
        capacity -= delegation_gas
        account_gas = allocate_weighted_with_caps(
            float(day["new_accounts_per_block"].iloc[0]) * n_blocks * 25_000,
            day["tx_count"].to_numpy(dtype=float),
            capacity,
        )
        panel.loc[panel.index[positions], "cal_new_delegation_indicators"] = (
            delegation_gas / 12_500
        )
        panel.loc[panel.index[positions], "cal_new_accounts"] = account_gas / 25_000

    # Current-rule resource split, matching the calibrated daily accounting:
    # data gas includes the EIP-7623 floor only for floor-bound transactions;
    # state combines block-observed storage/code with calibrated account and
    # delegation proxies; execution is the intrinsic-inclusive remainder. The
    # calibrated additions reproduce the daily totals but remain proxy
    # allocations rather than observed per-block counts.
    panel["data_gas_current"] = panel.standard_calldata_gas + panel.eip7623_floor_uplift
    panel["state_creation_gas"] = (
        panel.base_state_creation_gas
        + 25_000 * panel.cal_new_accounts
        + 12_500 * panel.cal_new_delegation_indicators
    )
    panel["execution_gas"] = (
        panel.gas_used.fillna(0) - panel.data_gas_current - panel.state_creation_gas
    )
    panel["gap_to_previous"] = panel.block_number.diff()
    panel["is_full_block"] = panel.gas_used >= 0.98 * panel.gas_limit

    out_dir = PROJECT_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"contiguous_block_panel_{args.start}_{args.days}d.csv"
    panel.to_csv(out, index=False)

    contiguous = int((panel.gap_to_previous == 1).sum())
    print(f"\nwrote {out.relative_to(PROJECT_ROOT)}  ({len(panel):,} blocks)")
    print(f"  adjacent pairs: {contiguous:,} of {len(panel) - 1:,}")
    print(f"  full blocks (>=98% of limit): {int(panel.is_full_block.sum()):,}")
    print(f"  negative execution gas rows: {int((panel.execution_gas < 0).sum()):,}")


if __name__ == "__main__":
    main()
