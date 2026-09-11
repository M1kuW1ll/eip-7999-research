"""Cache only the per-transaction EIP-8038 inputs absent from local data."""

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

from shared_fee.xatu import query_execution_repricing_components  # noqa: E402


TAG = "2026-02-01_2026-06-01"
BLOCKS = ROOT / "data" / f"calibration_xatu_bal_runtime_8279_blocks_{TAG}.csv"
OUTPUT = ROOT / "data/shared_fee/execution_repricing_components_6000_blocks.parquet"
PARTS = ROOT / "data/shared_fee/.execution_repricing_parts"


def client():
    load_dotenv(ROOT / ".env")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_RAW_HOST", "clickhouse-raw.xatu.ethpandaops.io"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "443")),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,
    )


def name(blocks: list[int]) -> str:
    digest = hashlib.sha256(",".join(map(str, blocks)).encode()).hexdigest()[:12]
    return f"part_{min(blocks)}_{max(blocks)}_{len(blocks)}_{digest}"


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

    requested = sorted(
        set(pd.read_csv(BLOCKS)["block_number"].astype("int64"))
    )
    PARTS.mkdir(parents=True, exist_ok=True)
    completed: set[int] = set()
    for marker in PARTS.glob("*.blocks.csv"):
        completed.update(pd.read_csv(marker)["block_number"].astype(int))
    missing = [block for block in requested if block not in completed]
    print(
        f"completed blocks={len(completed):,}; missing={len(missing):,}; "
        f"chunk_size={args.chunk_size:,}",
        flush=True,
    )
    raw_client = client() if missing else None
    new_chunks = 0
    for start in range(0, len(missing), args.chunk_size):
        if args.max_new_chunks is not None and new_chunks >= args.max_new_chunks:
            break
        chunk = missing[start : start + args.chunk_size]
        frame = query_execution_repricing_components(
            raw_client, chunk, network=args.network
        )
        stem = name(chunk)
        write_atomic(frame, PARTS / f"{stem}.parquet")
        pd.DataFrame({"block_number": chunk}).to_csv(
            PARTS / f"{stem}.blocks.csv", index=False
        )
        new_chunks += 1
        print(
            f"new chunk {new_chunks}: blocks={len(chunk):,}; sparse txs={len(frame):,}",
            flush=True,
        )

    completed = set()
    frames = []
    for marker in sorted(PARTS.glob("*.blocks.csv")):
        completed.update(pd.read_csv(marker)["block_number"].astype(int))
        frames.append(pd.read_parquet(marker.with_suffix("").with_suffix(".parquet")))
    if completed != set(requested):
        print(
            f"checkpointed blocks={len(completed):,}/{len(requested):,}; rerun to resume",
            flush=True,
        )
        return
    panel = pd.concat(frames, ignore_index=True)
    keys = ["block_number", "tx_index", "tx_hash"]
    if panel.duplicated(keys).any():
        raise ValueError("Cached execution chunks overlap")
    membership = pd.read_parquet(
        ROOT / "data/shared_fee/transaction_inputs_6000_blocks.parquet",
        columns=keys,
    )
    unmatched = panel.merge(
        membership, on=keys, how="left", validate="one_to_one", indicator=True
    )
    if not unmatched["_merge"].eq("both").all():
        raise ValueError("Execution components contain non-canonical transactions")
    write_atomic(panel.sort_values(keys), OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)} rows={len(panel):,}", flush=True)


if __name__ == "__main__":
    main()
