"""Build the 6,000-block EIP-8279 state/execution BAL attribution cache.

The script reuses the existing 1,200-block transaction cache and queries Xatu
for the remaining sampled blocks in bounded chunks. Only block-level
attribution is persisted for the wider panel, which avoids a second very large
transaction cache while preserving the component sums needed by notebook 1.11.
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
    attach_state_bundle,
    query_xatu_eip8279_runtime_meter,
)
from sim.xatu_glamsterdam import query_xatu_tx_state_creation  # noqa: E402


START_DATE = "2026-02-01"
END_DATE = "2026-06-01"
DATE_TAG = f"{START_DATE}_{END_DATE}"
BLOCK_INPUT = (
    ROOT / "data" / f"calibration_xatu_bal_runtime_8279_blocks_{DATE_TAG}.csv"
)
TX_CACHE = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_transactions_{DATE_TAG}.csv"
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


def _aggregate_cached_transactions(path: Path) -> pd.DataFrame:
    cached = pd.read_csv(path)
    attributed = attribute_direct_state_runtime_bytes(cached)
    return aggregate_state_execution_runtime_blocks(attributed)


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
    cached_blocks = _aggregate_cached_transactions(TX_CACHE)
    partial_blocks = pd.DataFrame()
    if PARTIAL_OUTPUT.exists():
        partial_blocks = pd.read_csv(PARTIAL_OUTPUT)
        cached_blocks = pd.concat(
            [cached_blocks, partial_blocks], ignore_index=True
        )
        cached_blocks = cached_blocks.drop_duplicates("block_number", keep="last")
    cached_numbers = set(cached_blocks["block_number"].astype(int))
    requested = runtime_blocks["block_number"].astype(int).tolist()
    missing = [block for block in requested if block not in cached_numbers]

    print(
        f"Using {len(cached_blocks):,} cached blocks; querying {len(missing):,} "
        f"blocks in chunks of {args.chunk_size:,}.",
        flush=True,
    )
    client = _client()
    pieces = [cached_blocks]
    for start in range(0, len(missing), args.chunk_size):
        chunk = missing[start : start + args.chunk_size]
        runtime = query_xatu_eip8279_runtime_meter(
            client, chunk, network=args.network
        )
        state = query_xatu_tx_state_creation(client, chunk, network=args.network)
        attributed = attribute_direct_state_runtime_bytes(
            attach_state_bundle(runtime, state)
        )
        block = aggregate_state_execution_runtime_blocks(attributed)

        expected = pd.DataFrame({"block_number": chunk}).merge(
            block, on="block_number", how="left", validate="one_to_one"
        )
        value_columns = [
            column for column in expected.columns if column != "block_number"
        ]
        expected[value_columns] = expected[value_columns].fillna(0).astype("int64")
        pieces.append(expected)
        checkpoint = pd.concat(
            [partial_blocks, *pieces[1:]], ignore_index=True
        ).drop_duplicates("block_number", keep="last")
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
