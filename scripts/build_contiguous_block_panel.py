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

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NETWORK = "mainnet"


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

# Charged calldata gas under current rules, including the EIP-7623 floor, plus
# the receipt gas needed to separate execution from data.
CALLDATA = """
    SELECT block_number,
           count()                                            AS tx_count,
           sum(toUInt64(gas_used))                            AS receipt_gas_used,
           sum(toUInt64(n_input_zero_bytes))                  AS calldata_zero_bytes,
           sum(toUInt64(n_input_nonzero_bytes))               AS calldata_nonzero_bytes,
           sum(toUInt64(4 * n_input_zero_bytes + 16 * n_input_nonzero_bytes))
                                                              AS standard_calldata_gas,
           sum(
               greatest(
                   toInt64(10 * (n_input_zero_bytes + 4 * n_input_nonzero_bytes))
                   - toInt64(4 * (n_input_zero_bytes + 4 * n_input_nonzero_bytes)),
                   0
               )
           )                                                  AS eip7623_floor_uplift
    FROM default.canonical_execution_transaction FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
    GROUP BY block_number
"""

# Persistent state creation: slots moving off zero, plus deployed contract code.
STORAGE = """
    SELECT block_number,
           countIf(from_value = '0x0000000000000000000000000000000000000000000000000000000000000000'
                   AND to_value != '0x0000000000000000000000000000000000000000000000000000000000000000')
               AS new_storage_slots
    FROM default.canonical_execution_storage_diffs FINAL
    WHERE meta_network_name = {network:String}
      AND block_number BETWEEN {lo:UInt64} AND {hi:UInt64}
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
    args = parser.parse_args()

    start_ts = f"{args.start} 00:00:00"
    end_ts = (pd.Timestamp(args.start) + pd.Timedelta(days=args.days)).strftime("%Y-%m-%d 00:00:00")

    conn = client()
    lo, hi, expected = resolve_range(conn, start_ts, end_ts)
    print(f"range {args.start} +{args.days}d -> blocks {lo}..{hi}  ({expected:,} canonical)")

    params = {"network": NETWORK, "lo": lo, "hi": hi}
    frames = {}
    for name, sql in (("headers", HEADERS), ("calldata", CALLDATA),
                      ("storage", STORAGE), ("contracts", CONTRACTS)):
        t0 = time.time()
        frames[name] = conn.query_df(sql, parameters=params, settings={"max_execution_time": 1800})
        print(f"  {name:10s} {len(frames[name]):>8,} rows  {time.time() - t0:6.1f}s")

    panel = frames["headers"]
    for name in ("calldata", "storage", "contracts"):
        panel = panel.merge(frames[name], on="block_number", how="left")
    panel = panel.sort_values("block_number").reset_index(drop=True)
    panel[["tx_count", "receipt_gas_used", "calldata_zero_bytes", "calldata_nonzero_bytes",
           "standard_calldata_gas", "eip7623_floor_uplift", "new_storage_slots",
           "new_contract_accounts", "code_bytes"]] = panel[[
        "tx_count", "receipt_gas_used", "calldata_zero_bytes", "calldata_nonzero_bytes",
        "standard_calldata_gas", "eip7623_floor_uplift", "new_storage_slots",
        "new_contract_accounts", "code_bytes"]].fillna(0)

    # Current-rule resource split, matching the daily accounting convention:
    # data gas includes the EIP-7623 floor, state uses the gas-equivalent proxy,
    # and execution is the intrinsic-inclusive remainder.
    panel["data_gas_current"] = panel.standard_calldata_gas + panel.eip7623_floor_uplift
    panel["state_creation_gas"] = (
        20_000 * panel.new_storage_slots + 200 * panel.code_bytes
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
