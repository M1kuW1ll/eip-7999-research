"""Cache exact EIP-8279 runtime-meter components for the 6,000-block panel."""

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

from sim.xatu_bal_8279 import query_xatu_eip8279_runtime_meter  # noqa: E402


TAG = "2026-02-01_2026-06-01"
BLOCK_INPUT = ROOT / f"data/calibration_xatu_bal_runtime_8279_blocks_{TAG}.csv"
CARRIER_REFERENCE = (
    ROOT / f"data/calibration_xatu_bal_runtime_8279_carrier_panel_{TAG}.parquet"
)
OUTPUT = ROOT / "data/shared_fee/runtime_components_6000_blocks.parquet"
CACHE = ROOT / "data/shared_fee/.runtime_component_chunks"
KEYS = ["block_number", "tx_index", "tx_hash"]


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


def _part_path(blocks: list[int]) -> Path:
    digest = hashlib.sha256(",".join(map(str, blocks)).encode()).hexdigest()[:12]
    return CACHE / f"part_{min(blocks)}_{max(blocks)}_{len(blocks)}_{digest}.parquet"


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=200)
    parser.add_argument("--network", default="mainnet")
    args = parser.parse_args()
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")

    blocks = pd.read_csv(BLOCK_INPUT)["block_number"].astype("int64").tolist()
    chunks = [
        blocks[start : start + args.chunk_size]
        for start in range(0, len(blocks), args.chunk_size)
    ]
    missing = [chunk for chunk in chunks if not _part_path(chunk).exists()]
    print(
        f"Using {len(chunks) - len(missing):,} cached chunks; "
        f"querying {len(missing):,} chunks.",
        flush=True,
    )
    if missing:
        client = _client()
        for number, chunk in enumerate(missing, start=1):
            frame = query_xatu_eip8279_runtime_meter(
                client, chunk, network=args.network
            )
            _write_atomic(frame, _part_path(chunk))
            print(f"Completed {number:,}/{len(missing):,} new chunks.", flush=True)

    pieces = [pd.read_parquet(_part_path(chunk)) for chunk in chunks]
    combined = pd.concat(pieces, ignore_index=True)
    combined["tx_hash"] = combined["tx_hash"].astype(str)
    # The component query aligns its three source tables on the complete
    # transaction set, including rows whose runtime counter is exactly zero.
    # The established carrier cache intentionally keeps only positive counters.
    combined = combined.loc[combined["bal_runtime_bytes_8279"].gt(0)].copy()
    if combined.duplicated(KEYS).any():
        raise ValueError("Runtime component cache contains duplicate transactions")

    reference = pd.read_parquet(
        CARRIER_REFERENCE,
        columns=[*KEYS, "bal_runtime_bytes_8279"],
    )
    reference["tx_hash"] = reference["tx_hash"].astype(str)
    check = reference.merge(
        combined[[*KEYS, "bal_runtime_bytes_8279"]],
        on=KEYS,
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_reference", "_components"),
    )
    if not check["_merge"].eq("both").all():
        raise ValueError("Runtime component and carrier transaction sets differ")
    if not check["bal_runtime_bytes_8279_reference"].equals(
        check["bal_runtime_bytes_8279_components"]
    ):
        raise ValueError("Runtime component bytes do not reconcile to carrier cache")

    _write_atomic(combined.sort_values(KEYS), OUTPUT)
    print(f"Wrote {OUTPUT} with {len(combined):,} BAL-carrying transactions.")


if __name__ == "__main__":
    main()
