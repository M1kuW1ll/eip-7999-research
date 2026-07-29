"""Build the 6,000-block EIP-8279 BAL attribution cache.

The transaction-level reconstruction is queried in bounded chunks and reduced
to block aggregates.  The compact output preserves the direct-state,
co-produced, and non-state decomposition by runtime-meter component, complete
transaction counts, and the cost-weighted diagnostic used by notebook 1.11.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import clickhouse_connect
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sim.xatu_bal_8279 import (  # noqa: E402
    aggregate_state_execution_runtime_blocks,
    attribute_direct_state_runtime_bytes,
    attach_normalized_composite_costs,
    attach_state_bundle,
    query_xatu_eip8279_runtime_meter,
)
from sim.xatu_glamsterdam import (  # noqa: E402
    query_xatu_transaction_gas_inputs,
    query_xatu_tx_state_creation,
)


START_DATE = "2026-02-01"
END_DATE = "2026-06-01"
DATE_TAG = f"{START_DATE}_{END_DATE}"
BLOCK_INPUT = (
    ROOT / "data" / f"calibration_xatu_bal_runtime_8279_blocks_{DATE_TAG}.csv"
)
OUTPUT = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_state_execution_blocks_{DATE_TAG}.csv"
)
PARTIAL_OUTPUT = OUTPUT.with_suffix(".partial.csv")


def _client():
    load_dotenv(ROOT / ".env")
    return clickhouse_connect.get_client(
        host=os.environ.get(
            "CLICKHOUSE_RAW_HOST", "clickhouse-raw.xatu.ethpandaops.io"
        ),
        port=int(os.environ.get("CLICKHOUSE_PORT", "443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,
    )


def _aggregate_chunk(runtime, state, gas) -> pd.DataFrame:
    attributed = attribute_direct_state_runtime_bytes(
        attach_state_bundle(runtime, state)
    )
    cost = attach_normalized_composite_costs(attributed, gas)
    block = aggregate_state_execution_runtime_blocks(attributed)

    transaction_counts = (
        gas.groupby("block_number", as_index=False)
        .size()
        .rename(columns={"size": "transactions"})
    )
    state_counts = (
        state.loc[state["historical_state_creation_gas"].gt(0)]
        .groupby("block_number", as_index=False)
        .size()
        .rename(columns={"size": "state_transactions"})
    )
    transaction_counts = transaction_counts.merge(
        state_counts, on="block_number", how="left", validate="one_to_one"
    )
    transaction_counts["state_transactions"] = (
        transaction_counts["state_transactions"].fillna(0).astype("int64")
    )
    transaction_counts["nonstate_transactions"] = (
        transaction_counts["transactions"]
        - transaction_counts["state_transactions"]
    )

    weighted_columns = []
    for resource in ["execution", "data", "state"]:
        runtime_column = f"runtime_x_{resource}_cost_share"
        coproduced_column = f"coproduced_x_{resource}_cost_share"
        cost[runtime_column] = (
            cost["bal_runtime_bytes_8279"]
            * cost[f"{resource}_composite_cost_share"]
        )
        cost[coproduced_column] = (
            cost["bal_runtime_bytes_coproduced_state_txs_8279"]
            * cost[f"{resource}_composite_cost_share"]
        )
        weighted_columns.extend([runtime_column, coproduced_column])
    weighted = cost.groupby("block_number", as_index=False)[weighted_columns].sum()

    return (
        block.merge(transaction_counts, on="block_number", how="outer")
        .merge(weighted, on="block_number", how="outer")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=200)
    parser.add_argument("--network", default="mainnet")
    args = parser.parse_args()
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")

    runtime_blocks = pd.read_csv(BLOCK_INPUT)
    if runtime_blocks["block_number"].duplicated().any():
        raise ValueError("Block input contains duplicate block numbers")
    partial_blocks = pd.DataFrame()
    if PARTIAL_OUTPUT.exists():
        partial_blocks = pd.read_csv(PARTIAL_OUTPUT)
    cached_numbers = set(partial_blocks.get("block_number", pd.Series(dtype=int)).astype(int))
    requested = runtime_blocks["block_number"].astype(int).tolist()
    missing = [block for block in requested if block not in cached_numbers]

    print(
        f"Using {len(partial_blocks):,} completed blocks; querying {len(missing):,} "
        f"blocks in chunks of {args.chunk_size:,}.",
        flush=True,
    )
    client = _client()
    pieces = [partial_blocks]
    for start in range(0, len(missing), args.chunk_size):
        chunk = missing[start : start + args.chunk_size]
        runtime = query_xatu_eip8279_runtime_meter(
            client, chunk, network=args.network
        )
        state = query_xatu_tx_state_creation(client, chunk, network=args.network)
        gas = query_xatu_transaction_gas_inputs(
            client, chunk, network=args.network
        )
        block = _aggregate_chunk(runtime, state, gas)

        expected = pd.DataFrame({"block_number": chunk}).merge(
            block, on="block_number", how="left", validate="one_to_one"
        )
        value_columns = [
            column for column in expected.columns if column != "block_number"
        ]
        expected[value_columns] = expected[value_columns].fillna(0)
        integer_columns = [
            column
            for column in value_columns
            if not column.startswith(("runtime_x_", "coproduced_x_"))
        ]
        expected[integer_columns] = expected[integer_columns].astype("int64")
        pieces.append(expected)
        checkpoint = pd.concat(pieces, ignore_index=True).drop_duplicates(
            "block_number", keep="last"
        )
        checkpoint.to_csv(PARTIAL_OUTPUT, index=False)
        print(
            f"Completed {min(start + len(chunk), len(missing)):,}/"
            f"{len(missing):,} queried blocks.",
            flush=True,
        )

    combined = pd.concat(pieces, ignore_index=True)
    if combined["block_number"].duplicated().any():
        raise ValueError("Combined attribution contains duplicate blocks")
    combined = runtime_blocks[["date", "block_number", "sample_rank"]].merge(
        combined, on="block_number", how="left", validate="one_to_one"
    )
    if combined.isna().any().any():
        missing_columns = combined.columns[combined.isna().any()].tolist()
        raise ValueError(f"Missing values in combined attribution: {missing_columns}")
    if not combined["bal_runtime_bytes_8279"].equals(
        runtime_blocks["bal_runtime_bytes_8279"]
    ):
        diff = (
            combined["bal_runtime_bytes_8279"]
            - runtime_blocks["bal_runtime_bytes_8279"]
        )
        raise ValueError(
            "Transaction and block runtime reconstructions differ: "
            f"max absolute difference {int(diff.abs().max())}"
        )
    if not (
        combined["bal_runtime_bytes_state_8279"]
        + combined["bal_runtime_bytes_execution_8279"]
    ).equals(combined["bal_runtime_bytes_8279"]):
        raise ValueError("Final state/execution attribution does not reconcile")
    if not (
        combined["state_transactions"] + combined["nonstate_transactions"]
    ).equals(combined["transactions"]):
        raise ValueError("State/non-state transaction counts do not reconcile")

    combined.to_csv(OUTPUT, index=False)
    if PARTIAL_OUTPUT.exists():
        PARTIAL_OUTPUT.unlink()
    state = int(combined["bal_runtime_bytes_state_8279"].sum())
    total = int(combined["bal_runtime_bytes_8279"].sum())
    print(f"Wrote {OUTPUT}", flush=True)
    print(f"State-linked runtime weight: {state / total:.9f}", flush=True)
    print(f"Execution-linked runtime weight: {1 - state / total:.9f}", flush=True)


if __name__ == "__main__":
    main()
