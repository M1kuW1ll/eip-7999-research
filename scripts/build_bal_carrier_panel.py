"""Build the compact 6,000-block EIP-8279 BAL carrier panel.

Each completed query chunk is written as an atomic pair of Parquet files. A
restart discovers completed block chunks and queries only missing blocks. The
final transaction panel contains BAL carriers only; a separate block cache
retains all-transaction gas totals and is reconciled against the established
6,000-block EIP-8279 attribution cache.

Xatu provides exact calldata and blob-versioned-hash fields. Complete static
data additionally requires an optional transaction-body file with access-list
and authorization counts. Its schema is:

    block_number, tx_index, tx_hash,
    access_list_address_count, access_list_storage_key_count,
    authorization_tuple_count
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import clickhouse_connect
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sim.bal_carrier_panel import (  # noqa: E402
    aggregate_bal_carrier_blocks,
    align_runtime_meter_to_transactions,
    build_bal_carrier_transaction_panel,
    compact_carrier_columns,
    normalize_compact_carrier_static_accounting,
    validate_bal_carrier_block_reconciliation,
    validate_compact_carriers_against_blocks,
)
from sim.xatu_bal_8279 import (  # noqa: E402
    attribute_direct_state_runtime_bytes,
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
BLOCK_REFERENCE = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_state_execution_blocks_{DATE_TAG}.csv"
)
OUTPUT = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_carrier_panel_{DATE_TAG}.parquet"
)
BLOCK_OUTPUT = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_carrier_blocks_{DATE_TAG}.parquet"
)
CARD_OUTPUT = (
    ROOT
    / "data"
    / f"calibration_xatu_bal_runtime_8279_carrier_panel_card_{DATE_TAG}.csv"
)
CACHE_ROOT = ROOT / "data" / f".bal_carrier_chunks_{DATE_TAG}"


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


def _part_stem(blocks: list[int]) -> str:
    payload = ",".join(map(str, blocks)).encode()
    digest = hashlib.sha256(payload).hexdigest()[:12]
    return f"part_{min(blocks)}_{max(blocks)}_{len(blocks)}_{digest}"


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _completed_parts(cache_dir: Path) -> list[tuple[Path, Path, pd.DataFrame]]:
    """Return only atomic chunk pairs; ignore an interrupted orphan file."""

    completed = []
    for blocks_path in sorted(cache_dir.glob("part_*.blocks.parquet")):
        carriers_path = blocks_path.with_name(
            blocks_path.name.replace(".blocks.parquet", ".carriers.parquet")
        )
        if not carriers_path.exists():
            continue
        block = pd.read_parquet(blocks_path)
        if block.empty or block["block_number"].duplicated().any():
            raise ValueError(f"Invalid cached block chunk: {blocks_path}")
        completed.append((blocks_path, carriers_path, block))
    return completed


def _load_transaction_body_content(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        content = pd.read_parquet(path)
    elif suffix in {".csv", ".gz"}:
        content = pd.read_csv(path)
    else:
        raise ValueError(
            "--transaction-body-content must be a CSV or Parquet file"
        )
    return content


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_directory(
    transaction_body_path: Path | None,
    *,
    execution_multiplier: float,
    cpsb: int,
) -> tuple[Path, dict[str, object]]:
    if transaction_body_path is None:
        static_source = {"complete": False, "source": "xatu_only"}
        tag = "xatu_only"
    else:
        resolved = transaction_body_path.resolve()
        checksum = _file_sha256(resolved)
        static_source = {
            "complete": True,
            "source": str(resolved),
            "sha256": checksum,
        }
        tag = f"complete_{checksum[:12]}"
    manifest = {
        "schema_version": 1,
        "date_tag": DATE_TAG,
        "execution_multiplier": float(execution_multiplier),
        "state_cpsb": int(cpsb),
        "static_detail": static_source,
    }
    return CACHE_ROOT / tag, manifest


def _ensure_cache_manifest(cache_dir: Path, manifest: dict[str, object]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "manifest.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing != manifest:
            raise ValueError(
                f"Cache settings differ from {path}; use a separate cache directory"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _query_chunk(
    client,
    blocks: list[int],
    reference: pd.DataFrame,
    transaction_body_content: pd.DataFrame | None,
    *,
    network: str,
    execution_multiplier: float,
    cpsb: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    runtime = query_xatu_eip8279_runtime_meter(client, blocks, network=network)
    state = query_xatu_tx_state_creation(client, blocks, network=network)
    gas = query_xatu_transaction_gas_inputs(client, blocks, network=network)
    runtime = align_runtime_meter_to_transactions(runtime, gas)
    attributed = attribute_direct_state_runtime_bytes(
        attach_state_bundle(runtime, state)
    )
    detail = None
    if transaction_body_content is not None:
        detail = transaction_body_content.loc[
            transaction_body_content["block_number"].isin(blocks)
        ]
    panel = build_bal_carrier_transaction_panel(
        attributed,
        gas,
        detail,
        execution_multiplier=execution_multiplier,
        cpsb=cpsb,
    )
    block = aggregate_bal_carrier_blocks(panel)
    # Preserve sampled empty blocks in the block-level reconciliation output.
    block = pd.DataFrame({"block_number": blocks}).merge(
        block,
        on="block_number",
        how="left",
        validate="one_to_one",
    )
    value_columns = [column for column in block if column != "block_number"]
    block[value_columns] = block[value_columns].fillna(0)
    expected = reference.loc[reference["block_number"].isin(blocks)]
    validate_bal_carrier_block_reconciliation(block, expected)
    return compact_carrier_columns(panel), block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=200)
    parser.add_argument("--network", default="mainnet")
    parser.add_argument("--execution-multiplier", type=float, default=1.537898)
    parser.add_argument("--cpsb", type=int, default=1530)
    parser.add_argument(
        "--transaction-body-content",
        type=Path,
        help="Optional per-transaction access-list/authorization count file",
    )
    parser.add_argument(
        "--allow-incomplete-static",
        action="store_true",
        help=(
            "Permit an Xatu-only panel with nullable access-list/authorization "
            "fields; omitted by default to prevent incomplete final caches"
        ),
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        help="Stop after this many new chunks, preserving resumable checkpoints",
    )
    args = parser.parse_args()
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if args.max_chunks is not None and args.max_chunks <= 0:
        raise ValueError("--max-chunks must be positive")
    if args.transaction_body_content is None and not args.allow_incomplete_static:
        raise ValueError(
            "Complete static data requires --transaction-body-content. "
            "Use --allow-incomplete-static only for an explicit Xatu-only diagnostic."
        )

    block_input = pd.read_csv(BLOCK_INPUT)
    reference = pd.read_csv(BLOCK_REFERENCE)
    for label, frame in [("block input", block_input), ("reference", reference)]:
        if frame["block_number"].duplicated().any():
            raise ValueError(f"{label} contains duplicate block numbers")
        frame["block_number"] = frame["block_number"].astype("int64")
    requested = block_input["block_number"].tolist()
    requested_set = set(requested)
    if set(reference["block_number"]) != requested_set:
        raise ValueError("Block input and 6,000-block reference membership differ")

    transaction_body_content = _load_transaction_body_content(
        args.transaction_body_content
    )
    if transaction_body_content is not None:
        transaction_body_content["block_number"] = transaction_body_content[
            "block_number"
        ].astype("int64")

    cache_dir, manifest = _cache_directory(
        args.transaction_body_content,
        execution_multiplier=args.execution_multiplier,
        cpsb=args.cpsb,
    )
    _ensure_cache_manifest(cache_dir, manifest)
    completed = _completed_parts(cache_dir)
    completed_numbers: list[int] = []
    for _, _, block in completed:
        completed_numbers.extend(block["block_number"].astype(int).tolist())
    if len(completed_numbers) != len(set(completed_numbers)):
        raise ValueError("Cached chunks contain overlapping block membership")
    if not set(completed_numbers).issubset(requested_set):
        raise ValueError("Cached chunks contain blocks outside the requested panel")
    missing = [block for block in requested if block not in set(completed_numbers)]
    print(
        f"Using {len(completed_numbers):,} completed blocks; querying "
        f"{len(missing):,} blocks in chunks of {args.chunk_size:,}.",
        flush=True,
    )

    client = _client() if missing else None
    new_chunks = 0
    for start in range(0, len(missing), args.chunk_size):
        if args.max_chunks is not None and new_chunks >= args.max_chunks:
            break
        chunk = missing[start : start + args.chunk_size]
        carriers, block = _query_chunk(
            client,
            chunk,
            reference,
            transaction_body_content,
            network=args.network,
            execution_multiplier=args.execution_multiplier,
            cpsb=args.cpsb,
        )
        stem = _part_stem(chunk)
        carriers_path = cache_dir / f"{stem}.carriers.parquet"
        blocks_path = cache_dir / f"{stem}.blocks.parquet"
        # The block file is the completion marker and is written last.
        _atomic_parquet(carriers, carriers_path)
        _atomic_parquet(block, blocks_path)
        new_chunks += 1
        print(
            f"Completed {min(start + len(chunk), len(missing)):,}/"
            f"{len(missing):,} missing blocks; {len(carriers):,} carriers in chunk.",
            flush=True,
        )

    completed = _completed_parts(cache_dir)
    block_parts = [item[2] for item in completed]
    covered = set().union(
        *(set(part["block_number"].astype(int)) for part in block_parts)
    ) if block_parts else set()
    if covered != requested_set:
        print(
            f"Checkpointed {len(covered):,}/{len(requested_set):,} blocks. "
            "Run the command again to resume.",
            flush=True,
        )
        return

    block_panel = pd.concat(block_parts, ignore_index=True)
    if block_panel["block_number"].duplicated().any():
        raise ValueError("Final cached block panel contains duplicate blocks")
    block_panel = block_input[["date", "block_number", "sample_rank"]].merge(
        block_panel,
        on="block_number",
        how="left",
        validate="one_to_one",
    )
    validate_bal_carrier_block_reconciliation(block_panel, reference)

    carrier_parts = [
        normalize_compact_carrier_static_accounting(pd.read_parquet(item[1]))
        for item in completed
    ]
    carriers = pd.concat(carrier_parts, ignore_index=True)
    if carriers.duplicated(["block_number", "tx_index", "tx_hash"]).any():
        raise ValueError("Final carrier panel contains duplicate transactions")
    carriers = block_input[["date", "block_number", "sample_rank"]].merge(
        carriers,
        on="block_number",
        how="right",
        validate="one_to_many",
    ).sort_values(["block_number", "tx_index"])
    validate_compact_carriers_against_blocks(carriers, block_panel)

    _atomic_parquet(carriers, OUTPUT)
    _atomic_parquet(block_panel, BLOCK_OUTPUT)
    component_total = (
        carriers["bal_runtime_bytes_direct_state_8279"].sum()
        + carriers["bal_runtime_bytes_coproduced_state_txs_8279"].sum()
        + carriers["bal_runtime_bytes_nonstate_txs_8279"].sum()
    )
    bal_total = int(carriers["bal_runtime_bytes_8279"].sum())
    if int(component_total) != bal_total:
        raise ValueError("Final carrier components do not reconcile")
    card = pd.DataFrame(
        [
            {
                "start_date": START_DATE,
                "end_date_exclusive": END_DATE,
                "blocks": len(block_panel),
                "transactions": int(block_panel["transaction_count"].sum()),
                "carrier_transactions": len(carriers),
                "bal_runtime_bytes_8279": bal_total,
                "bal_runtime_bytes_per_block_8279": bal_total / len(block_panel),
                "bal_runtime_mean_weighting": (
                    "unweighted mean across the 6,000 sampled blocks; "
                    "the equilibrium anchor is weighted by canonical blocks per day"
                ),
                "direct_state_share": (
                    carriers["bal_runtime_bytes_direct_state_8279"].sum()
                    / bal_total
                ),
                "coproduced_share": (
                    carriers[
                        "bal_runtime_bytes_coproduced_state_txs_8279"
                    ].sum()
                    / bal_total
                ),
                "nonstate_share": (
                    carriers["bal_runtime_bytes_nonstate_txs_8279"].sum()
                    / bal_total
                ),
                "static_data_detail_complete": bool(
                    carriers["static_data_detail_complete"].all()
                ),
                "static_data_xatu_fields": (
                    "exact calldata zero/nonzero bytes and blob hash count"
                ),
                "static_data_supplement": (
                    str(args.transaction_body_content)
                    if args.transaction_body_content is not None
                    else "access-list and authorization counts pending"
                ),
                "execution_multiplier": args.execution_multiplier,
                "state_cpsb": args.cpsb,
                "reconciliation_reference": str(BLOCK_REFERENCE.relative_to(ROOT)),
            }
        ]
    )
    _atomic_csv(card, CARD_OUTPUT)
    print(f"Wrote {OUTPUT}", flush=True)
    print(f"Wrote {BLOCK_OUTPUT}", flush=True)
    print(f"Wrote {CARD_OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
