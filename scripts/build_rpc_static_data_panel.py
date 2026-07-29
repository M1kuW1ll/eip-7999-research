"""Build a resumable 6,000-block transaction-level static-data panel.

Each requested block needs one lightweight
``eth_getBlockByNumber(block, true)`` call.  The script does not request
receipts, traces, or state.  Completed chunks are retained as Parquet parts,
so rerunning the command only queries blocks that have not been checkpointed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sim.rpc_static_data import (  # noqa: E402
    TRANSACTION_COLUMNS,
    fetch_static_data_records_for_blocks,
    summarize_static_data_by_block,
)


START_DATE = "2026-02-01"
END_DATE = "2026-06-01"
DATE_TAG = f"{START_DATE}_{END_DATE}"
DEFAULT_BLOCK_INPUT = (
    ROOT / "data" / f"calibration_xatu_bal_runtime_8279_blocks_{DATE_TAG}.csv"
)
DEFAULT_OUTPUT = (
    ROOT / "data" / f"calibration_rpc_static_data_transactions_{DATE_TAG}.parquet"
)
DEFAULT_BLOCK_SUMMARY = (
    ROOT / "data" / f"calibration_rpc_static_data_blocks_{DATE_TAG}.csv"
)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _load_completed_parts(part_dir: Path) -> tuple[set[int], list[Path]]:
    completed: set[int] = set()
    parts: list[Path] = []
    for manifest in sorted(part_dir.glob("part-*.blocks.csv")):
        part = manifest.with_name(manifest.name.removesuffix(".blocks.csv") + ".parquet")
        if not part.exists():
            continue
        block_frame = pd.read_csv(manifest)
        if list(block_frame.columns) != ["block_number"]:
            raise ValueError(f"Invalid checkpoint manifest: {manifest}")
        block_values = set(block_frame["block_number"].astype(int))
        overlap = completed.intersection(block_values)
        if overlap:
            raise ValueError(
                f"Checkpoint blocks occur in multiple parts: {sorted(overlap)[:5]}"
            )
        completed.update(block_values)
        parts.append(part)
    return completed, parts


def _write_checkpoint(
    *,
    part_dir: Path,
    part_number: int,
    block_numbers: list[int],
    records: pd.DataFrame,
) -> None:
    stem = f"part-{part_number:05d}"
    part_path = part_dir / f"{stem}.parquet"
    manifest_path = part_dir / f"{stem}.blocks.csv"
    _atomic_parquet(records, part_path)
    _atomic_csv(
        pd.DataFrame({"block_number": [int(block) for block in block_numbers]}),
        manifest_path,
    )


def _finalize(
    *,
    part_dir: Path,
    requested_blocks: list[int],
    output: Path,
    block_summary: Path,
) -> tuple[int, int]:
    completed, parts = _load_completed_parts(part_dir)
    requested = set(requested_blocks)
    if completed != requested:
        missing = sorted(requested - completed)
        unexpected = sorted(completed - requested)
        raise ValueError(
            "Cannot finalize an incomplete panel: "
            f"{len(missing)} missing and {len(unexpected)} unexpected blocks"
        )

    temporary_output = output.with_suffix(output.suffix + ".tmp")
    writer: pq.ParquetWriter | None = None
    summaries: list[pd.DataFrame] = []
    transaction_count = 0
    try:
        for part in parts:
            frame = pd.read_parquet(part)
            if list(frame.columns) != TRANSACTION_COLUMNS:
                raise ValueError(f"Unexpected columns in checkpoint part: {part}")
            if frame.duplicated(["block_number", "tx_index"]).any():
                raise ValueError(f"Duplicate transaction positions in checkpoint: {part}")
            transaction_count += len(frame)
            manifest = part.with_name(part.stem + ".blocks.csv")
            part_blocks = pd.read_csv(manifest)["block_number"].astype(int).tolist()
            summaries.append(summarize_static_data_by_block(frame, part_blocks))

            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temporary_output, table.schema)
            writer.write_table(table)
        if writer is None:
            empty = pd.DataFrame(columns=TRANSACTION_COLUMNS)
            empty.to_parquet(temporary_output, index=False)
        else:
            writer.close()
            writer = None
        temporary_output.replace(output)
    finally:
        if writer is not None:
            writer.close()

    summary = pd.concat(summaries, ignore_index=True)
    if summary["block_number"].duplicated().any():
        raise ValueError("Final block summary contains duplicate blocks")
    block_order = pd.DataFrame(
        {
            "block_number": requested_blocks,
            "input_order": range(len(requested_blocks)),
        }
    )
    summary = (
        block_order.merge(summary, on="block_number", how="left", validate="one_to_one")
        .sort_values("input_order")
        .drop(columns="input_order")
        .reset_index(drop=True)
    )
    if summary.isna().any().any():
        raise ValueError("Final block summary is missing checkpointed data")
    _atomic_csv(summary, block_summary)
    return transaction_count, len(summary)


def _rpc_configuration(args: argparse.Namespace) -> tuple[str, dict[str, str] | None]:
    load_dotenv(ROOT / ".env")
    ethnodeops_key = args.api_key or os.environ.get("ETHNODEOPS_API_KEY") or os.environ.get(
        "hoodi_api_key"
    )
    ethnodeops_url = os.environ.get(
        "ETHNODEOPS_RPC", "https://erigon.mainnet.rpc.ethnodeops.xyz"
    )
    if args.rpc_url:
        rpc_url = args.rpc_url
        headers = {"X-API-Key": args.api_key} if args.api_key else None
    elif ethnodeops_key:
        rpc_url = ethnodeops_url
        headers = {"X-API-Key": ethnodeops_key}
    elif os.environ.get("ALCHEMY_RPC"):
        rpc_url = os.environ["ALCHEMY_RPC"]
        headers = None
    else:
        raise RuntimeError(
            "Missing ETHNODEOPS_API_KEY (or hoodi_api_key), ALCHEMY_RPC, or --rpc-url"
        )
    return rpc_url, headers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block-input", type=Path, default=DEFAULT_BLOCK_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--block-summary", type=Path, default=DEFAULT_BLOCK_SUMMARY)
    parser.add_argument("--part-dir", type=Path)
    parser.add_argument("--rpc-url")
    parser.add_argument("--api-key")
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--retry-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="Validate and combine existing checkpoint parts without querying RPC.",
    )
    args = parser.parse_args()
    if args.chunk_size <= 0 or args.max_workers <= 0:
        raise ValueError("--chunk-size and --max-workers must be positive")

    block_input = pd.read_csv(args.block_input)
    if "block_number" not in block_input:
        raise ValueError("Block input must contain block_number")
    if block_input["block_number"].duplicated().any():
        raise ValueError("Block input contains duplicate block numbers")
    requested_blocks = block_input["block_number"].astype(int).tolist()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.block_summary.parent.mkdir(parents=True, exist_ok=True)
    part_dir = args.part_dir or args.output.with_suffix(".parts")
    part_dir.mkdir(parents=True, exist_ok=True)

    completed, existing_parts = _load_completed_parts(part_dir)
    unexpected = completed - set(requested_blocks)
    if unexpected:
        raise ValueError(
            f"Checkpoint directory contains {len(unexpected)} blocks outside the input"
        )
    missing = [block for block in requested_blocks if block not in completed]
    print(
        f"Using {len(completed):,} checkpointed blocks; "
        f"{len(missing):,} blocks remain.",
        flush=True,
    )

    if not args.finalize_only and missing:
        rpc_url, rpc_headers = _rpc_configuration(args)
        next_part = max(
            (int(path.stem.removeprefix("part-")) for path in existing_parts),
            default=-1,
        ) + 1
        for start in range(0, len(missing), args.chunk_size):
            chunk = missing[start : start + args.chunk_size]
            records = fetch_static_data_records_for_blocks(
                rpc_url,
                chunk,
                rpc_headers=rpc_headers,
                max_retries=args.max_retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
                max_workers=args.max_workers,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
            )
            _write_checkpoint(
                part_dir=part_dir,
                part_number=next_part,
                block_numbers=chunk,
                records=records,
            )
            next_part += 1
            print(
                f"Checkpointed {min(start + len(chunk), len(missing)):,}/"
                f"{len(missing):,} remaining blocks.",
                flush=True,
            )

    transactions, blocks = _finalize(
        part_dir=part_dir,
        requested_blocks=requested_blocks,
        output=args.output,
        block_summary=args.block_summary,
    )
    print(
        f"Wrote {transactions:,} transactions across {blocks:,} blocks to "
        f"{args.output}",
        flush=True,
    )
    print(f"Wrote block reconciliation summary to {args.block_summary}", flush=True)


if __name__ == "__main__":
    main()
