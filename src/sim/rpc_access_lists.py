"""Pull and summarize transaction access lists from JSON-RPC."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Sequence
from dataclasses import dataclass
import time
from typing import Any

import pandas as pd

from .rpc_authorizations import normalize_hash, parse_quantity
from .rpc_bal import rpc_call

ACCESS_LIST_ADDRESS_BYTES = 20
ACCESS_LIST_STORAGE_KEY_BYTES = 32
ACCESS_LIST_DATA_GAS_PER_BYTE = 64


@dataclass(frozen=True)
class AccessListTransactionRecord:
    block_number: int
    tx_index: int
    tx_hash: str
    tx_type: int
    access_list_address_count: int
    access_list_storage_key_count: int
    access_list_bytes: int
    access_list_gas: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "block_number": self.block_number,
            "tx_index": self.tx_index,
            "tx_hash": self.tx_hash,
            "tx_type": self.tx_type,
            "tx_access_list_address_count": self.access_list_address_count,
            "tx_access_list_storage_key_count": self.access_list_storage_key_count,
            "tx_access_list_bytes": self.access_list_bytes,
            "tx_access_list_gas": self.access_list_gas,
        }


def access_list_counts(tx: dict[str, Any]) -> tuple[int, int]:
    """Return address-entry and storage-key counts from an RPC transaction."""

    access_list = tx.get("accessList") or []
    address_count = len(access_list)
    storage_key_count = 0
    for entry in access_list:
        storage_key_count += len(entry.get("storageKeys") or [])
    return address_count, storage_key_count


def access_list_bytes(
    *,
    address_count: int,
    storage_key_count: int,
) -> int:
    """EIP-7981 byte count: 20 bytes per address, 32 per storage key."""

    if address_count < 0 or storage_key_count < 0:
        raise ValueError("access-list counts must be non-negative")
    return (
        int(address_count) * ACCESS_LIST_ADDRESS_BYTES
        + int(storage_key_count) * ACCESS_LIST_STORAGE_KEY_BYTES
    )


def decode_access_list_transaction_record(
    *,
    block_number: int,
    tx_index: int,
    tx: dict[str, Any],
) -> AccessListTransactionRecord:
    address_count, storage_key_count = access_list_counts(tx)
    byte_count = access_list_bytes(
        address_count=address_count,
        storage_key_count=storage_key_count,
    )
    return AccessListTransactionRecord(
        block_number=int(block_number),
        tx_index=int(tx_index),
        tx_hash=normalize_hash(tx.get("hash", "")),
        tx_type=parse_quantity(tx.get("type"), default=0),
        access_list_address_count=address_count,
        access_list_storage_key_count=storage_key_count,
        access_list_bytes=byte_count,
        access_list_gas=byte_count * ACCESS_LIST_DATA_GAS_PER_BYTE,
    )


def _empty_records_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "block_number",
            "tx_index",
            "tx_hash",
            "tx_type",
            "tx_access_list_address_count",
            "tx_access_list_storage_key_count",
            "tx_access_list_bytes",
            "tx_access_list_gas",
        ]
    )


def fetch_access_list_records_for_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    rpc_headers: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    max_workers: int = 16,
) -> pd.DataFrame:
    """Fetch full RPC block transactions and summarize their access lists."""

    def fetch_block_records(block_number: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        rpc_block = None
        for attempt in range(max(1, int(max_retries))):
            try:
                rpc_block = rpc_call(
                    rpc_url,
                    "eth_getBlockByNumber",
                    [hex(block_number), True],
                    headers=rpc_headers,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt + 1 < max(1, int(max_retries)):
                    time.sleep(float(retry_sleep_seconds))
        if rpc_block is None and last_error is not None:
            raise last_error
        if rpc_block is None:
            raise RuntimeError(f"RPC returned no block for {block_number}")

        block_rows: list[dict[str, Any]] = []
        for tx_index, tx in enumerate(rpc_block.get("transactions") or []):
            record = decode_access_list_transaction_record(
                block_number=block_number,
                tx_index=tx_index,
                tx=tx,
            )
            block_rows.append(record.as_dict())
        return block_rows

    rows: list[dict[str, Any]] = []
    blocks = sorted({int(block) for block in block_numbers})
    workers = max(1, int(max_workers))
    if workers == 1:
        for block_number in blocks:
            rows.extend(fetch_block_records(block_number))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_block_records, block_number): block_number
                for block_number in blocks
            }
            for future in as_completed(futures):
                rows.extend(future.result())

    if not rows:
        return _empty_records_frame()
    return (
        pd.DataFrame(rows, columns=_empty_records_frame().columns)
        .sort_values(["block_number", "tx_index"])
        .reset_index(drop=True)
    )


def summarize_access_lists_by_block(
    records: pd.DataFrame,
    block_numbers: Sequence[int],
) -> pd.DataFrame:
    """Aggregate transaction access-list counts to one row per block."""

    blocks = pd.DataFrame({"block_number": sorted({int(b) for b in block_numbers})})
    columns = [
        "block_number",
        "tx_access_list_tx_count",
        "tx_access_list_address_count",
        "tx_access_list_storage_key_count",
        "tx_access_list_bytes",
        "tx_access_list_gas",
    ]

    if records.empty:
        out = blocks.copy()
        for column in columns[1:]:
            out[column] = 0
        return out[columns]

    grouped = (
        records.groupby("block_number", as_index=False)
        .agg(
            tx_access_list_tx_count=(
                "tx_access_list_bytes",
                lambda values: int((values > 0).sum()),
            ),
            tx_access_list_address_count=(
                "tx_access_list_address_count",
                "sum",
            ),
            tx_access_list_storage_key_count=(
                "tx_access_list_storage_key_count",
                "sum",
            ),
            tx_access_list_bytes=("tx_access_list_bytes", "sum"),
            tx_access_list_gas=("tx_access_list_gas", "sum"),
        )
    )

    out = blocks.merge(grouped, on="block_number", how="left")
    for column in columns[1:]:
        out[column] = out[column].fillna(0).astype("int64")
    return out[columns]


def fetch_access_list_data_for_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    rpc_headers: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    max_workers: int = 16,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = fetch_access_list_records_for_blocks(
        rpc_url,
        block_numbers,
        rpc_headers=rpc_headers,
        max_retries=max_retries,
        retry_sleep_seconds=retry_sleep_seconds,
        max_workers=max_workers,
    )
    summary = summarize_access_lists_by_block(records, block_numbers)
    return records, summary
