"""Build a resumable all-transaction input cache for the 6,000-block sample."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import clickhouse_connect
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shared_fee.xatu import query_transaction_identity  # noqa: E402
from sim.xatu_glamsterdam import query_xatu_transaction_gas_inputs  # noqa: E402


DATE_TAG = "2026-02-01_2026-06-01"
BLOCKS = ROOT / "data" / f"calibration_xatu_bal_runtime_8279_blocks_{DATE_TAG}.csv"
OUTPUT = ROOT / "data/shared_fee/transaction_inputs_6000_blocks.parquet"
PARTS = ROOT / "data/shared_fee/.transaction_input_parts"


def client():
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


def stem(blocks: list[int]) -> str:
    digest = hashlib.sha256(",".join(map(str, blocks)).encode()).hexdigest()[:12]
    return f"part_{min(blocks)}_{max(blocks)}_{len(blocks)}_{digest}.parquet"


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--max-new-chunks", type=int)
    parser.add_argument("--network", default="mainnet")
    args = parser.parse_args()
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")

    block_frame = pd.read_csv(BLOCKS)
    sampled_blocks = block_frame["block_number"].astype("int64").tolist()
    static_keys = pd.read_parquet(
        ROOT
        / f"data/calibration_rpc_static_data_transactions_{DATE_TAG}.parquet",
        columns=["block_number", "tx_index", "tx_hash"],
    )
    # Empty blocks have no transaction-level rows to query or cache. Keep them
    # in the 6,000-block calibration denominator, but exclude them from this
    # transaction-membership pull.
    requested = sorted(set(static_keys["block_number"].astype("int64")))
    empty_blocks = sorted(set(sampled_blocks).difference(requested))
    PARTS.mkdir(parents=True, exist_ok=True)
    completed: set[int] = set()
    for part in PARTS.glob("part_*.parquet"):
        completed.update(pd.read_parquet(part, columns=["block_number"])[
            "block_number"
        ].astype(int))
    missing = [block for block in requested if block not in completed]
    print(
        f"sampled blocks={len(sampled_blocks):,}; empty blocks={len(empty_blocks):,}; "
        f"completed non-empty blocks={len(completed):,}; missing={len(missing):,}; "
        f"chunk_size={args.chunk_size:,}",
        flush=True,
    )
    raw_client = client() if missing else None
    new_chunks = 0
    for start in range(0, len(missing), args.chunk_size):
        if args.max_new_chunks is not None and new_chunks >= args.max_new_chunks:
            break
        chunk = missing[start : start + args.chunk_size]
        gas = query_xatu_transaction_gas_inputs(
            raw_client, chunk, network=args.network
        )
        identity = query_transaction_identity(
            raw_client, chunk, network=args.network
        )
        keys = ["block_number", "tx_index", "tx_hash"]
        panel = gas.merge(identity, on=keys, how="inner", validate="one_to_one")
        if len(panel) != len(gas) or len(panel) != len(identity):
            raise RuntimeError("Transaction gas and identity pulls do not reconcile")
        write_atomic(panel, PARTS / stem(chunk))
        new_chunks += 1
        print(
            f"new chunk {new_chunks}: blocks={len(chunk):,}; txs={len(panel):,}",
            flush=True,
        )

    parts = sorted(PARTS.glob("part_*.parquet"))
    frames = [pd.read_parquet(path) for path in parts]
    if not frames:
        return
    panel = pd.concat(frames, ignore_index=True)
    keys = ["block_number", "tx_index", "tx_hash"]
    if panel.duplicated(keys).any():
        raise ValueError("Cached transaction chunks overlap")
    covered = set(panel["block_number"].astype(int))
    if covered != set(requested):
        print(
            f"checkpointed blocks={len(covered):,}/{len(requested):,}; rerun to resume",
            flush=True,
        )
        return
    static = static_keys[keys]
    if set(map(tuple, panel[keys].to_numpy())) != set(
        map(tuple, static[keys].to_numpy())
    ):
        raise ValueError("Xatu inputs do not match the exact static-data transaction set")
    write_atomic(panel.sort_values(keys), OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)} rows={len(panel):,}", flush=True)


if __name__ == "__main__":
    main()
