"""Extract EIP-7999 static-data quantities from full RPC block bodies.

The full transaction object returned by ``eth_getBlockByNumber(..., true)``
contains every field needed here.  No receipts, execution traces, or state
lookups are required.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
from typing import Any

import pandas as pd

from .rpc_access_lists import access_list_bytes, access_list_counts
from .rpc_authorizations import (
    AUTH_TUPLE_BYTES_8131,
    BLOB_VERSIONED_HASH_BYTES_8131,
    normalize_hash,
    parse_quantity,
)
from .rpc_bal import rpc_call


DATA_GAS_PER_BYTE_7999 = 16


@dataclass(frozen=True)
class StaticDataTransactionRecord:
    """Transaction-level content entering the counterfactual data resource."""

    block_number: int
    tx_index: int
    tx_hash: str
    tx_type: int
    calldata_bytes: int
    access_list_address_count: int
    access_list_storage_key_count: int
    access_list_bytes: int
    authorization_tuple_count: int
    authorization_tuple_bytes: int
    blob_versioned_hash_count: int
    blob_versioned_hash_bytes: int
    static_data_bytes: int
    static_data_gas: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "block_number": self.block_number,
            "tx_index": self.tx_index,
            "tx_hash": self.tx_hash,
            "tx_type": self.tx_type,
            "calldata_bytes": self.calldata_bytes,
            "tx_access_list_address_count": self.access_list_address_count,
            "tx_access_list_storage_key_count": self.access_list_storage_key_count,
            "tx_access_list_bytes": self.access_list_bytes,
            "authorization_tuple_count": self.authorization_tuple_count,
            "authorization_tuple_8131_bytes": self.authorization_tuple_bytes,
            "blob_versioned_hash_count": self.blob_versioned_hash_count,
            "blob_versioned_hash_8131_bytes": self.blob_versioned_hash_bytes,
            "static_data_8131_bytes": self.static_data_bytes,
            "static_data_gas_7999": self.static_data_gas,
        }


TRANSACTION_COLUMNS = list(
    StaticDataTransactionRecord(
        block_number=0,
        tx_index=0,
        tx_hash="",
        tx_type=0,
        calldata_bytes=0,
        access_list_address_count=0,
        access_list_storage_key_count=0,
        access_list_bytes=0,
        authorization_tuple_count=0,
        authorization_tuple_bytes=0,
        blob_versioned_hash_count=0,
        blob_versioned_hash_bytes=0,
        static_data_bytes=0,
        static_data_gas=0,
    ).as_dict()
)


def calldata_byte_length(value: Any) -> int:
    """Return the byte length of a hex-encoded transaction input."""

    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    text = str(value)
    if text.startswith("0x"):
        text = text[2:]
    if not text:
        return 0
    if len(text) % 2:
        raise ValueError("Transaction input must contain complete bytes")
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("Transaction input is not valid hexadecimal data") from exc
    return len(text) // 2


def decode_static_data_transaction_record(
    *,
    block_number: int,
    tx_index: int,
    tx: dict[str, Any],
) -> StaticDataTransactionRecord:
    """Decode all fixed-content static-data fields from one RPC transaction."""

    tx_block_number = tx.get("blockNumber")
    if tx_block_number is not None and parse_quantity(tx_block_number) != int(
        block_number
    ):
        raise ValueError("Transaction block number does not match its RPC block")
    rpc_tx_index = tx.get("transactionIndex")
    if rpc_tx_index is not None and parse_quantity(rpc_tx_index) != int(tx_index):
        raise ValueError("Transaction index does not match its position in the RPC block")

    input_bytes = calldata_byte_length(tx.get("input", tx.get("data")))
    access_addresses, access_keys = access_list_counts(tx)
    access_bytes = access_list_bytes(
        address_count=access_addresses,
        storage_key_count=access_keys,
    )
    authorization_count = len(tx.get("authorizationList") or [])
    authorization_bytes = authorization_count * AUTH_TUPLE_BYTES_8131
    blob_hash_count = len(
        tx.get("blobVersionedHashes", tx.get("blob_versioned_hashes")) or []
    )
    blob_hash_bytes = blob_hash_count * BLOB_VERSIONED_HASH_BYTES_8131
    static_bytes = (
        input_bytes + access_bytes + authorization_bytes + blob_hash_bytes
    )

    return StaticDataTransactionRecord(
        block_number=int(block_number),
        tx_index=int(tx_index),
        tx_hash=normalize_hash(tx.get("hash", "")),
        tx_type=parse_quantity(tx.get("type"), default=0),
        calldata_bytes=input_bytes,
        access_list_address_count=access_addresses,
        access_list_storage_key_count=access_keys,
        access_list_bytes=access_bytes,
        authorization_tuple_count=authorization_count,
        authorization_tuple_bytes=authorization_bytes,
        blob_versioned_hash_count=blob_hash_count,
        blob_versioned_hash_bytes=blob_hash_bytes,
        static_data_bytes=static_bytes,
        static_data_gas=static_bytes * DATA_GAS_PER_BYTE_7999,
    )


def decode_static_data_block(
    *,
    requested_block_number: int,
    rpc_block: dict[str, Any],
) -> list[dict[str, Any]]:
    """Decode a full RPC block and validate its identifying fields."""

    rpc_number = rpc_block.get("number")
    if rpc_number is None or parse_quantity(rpc_number) != int(requested_block_number):
        raise ValueError(
            f"RPC returned the wrong block for {requested_block_number}"
        )

    rows: list[dict[str, Any]] = []
    for tx_index, tx in enumerate(rpc_block.get("transactions") or []):
        if not isinstance(tx, dict):
            raise ValueError(
                "RPC returned transaction hashes instead of full transaction objects"
            )
        rows.append(
            decode_static_data_transaction_record(
                block_number=requested_block_number,
                tx_index=tx_index,
                tx=tx,
            ).as_dict()
        )
    return rows


def empty_static_data_records() -> pd.DataFrame:
    return pd.DataFrame(columns=TRANSACTION_COLUMNS)


def fetch_static_data_records_for_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    rpc_headers: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_sleep_seconds: float = 1.0,
    max_workers: int = 8,
    rpc_timeout_seconds: int = 180,
) -> pd.DataFrame:
    """Fetch one full transaction body per block and return compact static data.

    This path intentionally performs no receipt, trace, or per-transaction RPC
    calls.  A failed block causes the current caller batch to fail, allowing a
    checkpointing caller to retry that batch without accepting partial data.
    """

    blocks = sorted({int(block) for block in block_numbers})
    if not blocks:
        return empty_static_data_records()

    def fetch_one(block_number: int) -> list[dict[str, Any]]:
        attempts = max(1, int(max_retries))
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                rpc_block = rpc_call(
                    rpc_url,
                    "eth_getBlockByNumber",
                    [hex(block_number), True],
                    timeout=int(rpc_timeout_seconds),
                    headers=rpc_headers,
                )
                if rpc_block is None:
                    raise RuntimeError(f"RPC returned no block for {block_number}")
                return decode_static_data_block(
                    requested_block_number=block_number,
                    rpc_block=rpc_block,
                )
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(float(retry_sleep_seconds))
        assert last_error is not None
        raise last_error

    rows: list[dict[str, Any]] = []
    workers = max(1, int(max_workers))
    if workers == 1:
        for block_number in blocks:
            rows.extend(fetch_one(block_number))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_one, block_number): block_number
                for block_number in blocks
            }
            for future in as_completed(futures):
                rows.extend(future.result())

    if not rows:
        return empty_static_data_records()
    records = pd.DataFrame(rows, columns=TRANSACTION_COLUMNS)
    if records.duplicated(["block_number", "tx_index"]).any():
        raise ValueError("RPC static-data records contain duplicate transaction positions")
    if records["tx_hash"].eq("").any() or records["tx_hash"].duplicated().any():
        raise ValueError("RPC static-data records contain missing or duplicate hashes")
    return records.sort_values(["block_number", "tx_index"]).reset_index(drop=True)


def summarize_static_data_by_block(
    records: pd.DataFrame,
    block_numbers: Sequence[int],
) -> pd.DataFrame:
    """Aggregate static-data records while retaining requested empty blocks."""

    blocks = pd.DataFrame(
        {"block_number": sorted({int(block) for block in block_numbers})}
    )
    summary_columns = [
        "transactions",
        "calldata_bytes",
        "tx_access_list_address_count",
        "tx_access_list_storage_key_count",
        "tx_access_list_bytes",
        "authorization_tuple_count",
        "authorization_tuple_8131_bytes",
        "blob_versioned_hash_count",
        "blob_versioned_hash_8131_bytes",
        "static_data_8131_bytes",
        "static_data_gas_7999",
    ]
    if records.empty:
        out = blocks.copy()
        for column in summary_columns:
            out[column] = 0
        return out

    sums = [column for column in summary_columns if column != "transactions"]
    grouped = records.groupby("block_number", as_index=False).agg(
        transactions=("tx_hash", "size"),
        **{column: (column, "sum") for column in sums},
    )
    out = blocks.merge(grouped, on="block_number", how="left", validate="one_to_one")
    out[summary_columns] = out[summary_columns].fillna(0).astype("int64")
    return out
