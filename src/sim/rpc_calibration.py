"""Daily sampled-block calibration helpers.

The daily accounting panel (notebook 1.1) is Xatu-only and cannot see
access-list bytes, authorization tuples, BAL bytes, or exact new-account /
delegation counts. This module calibrates those from deterministic daily
block samples. The light path fetches:

    1x debug_traceBlockByNumber (prestateTracer, diffMode=True)
    1x eth_getBlockReceipts
    1x eth_getBlockByNumber (full transactions)

That feeds EIP-8037 state, EIP-7981 access-list data, and EIP-7702
authorization tuple calibration. The expensive BAL path additionally fetches
the non-diff prestate trace for storage reads and can optionally add system
changes.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd
import rlp

from .rpc_access_lists import decode_access_list_transaction_record
from .rpc_authorizations import decode_authorization_record, parse_quantity
from .rpc_bal import build_rpc_bal_from_traces, fetch_block_trace, rpc_call
from .rpc_state_growth import summarize_rpc_state_growth_from_traces


def sample_blocks_per_day(
    days: pd.DataFrame,
    n_per_day: int,
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministic uniform block sample per day with a stable rank.

    ``days`` needs ``date``, ``min_block``, ``max_block`` columns (the daily
    panel provides them). Ranks are draw order, so running the calibration on
    ``sample_rank < k`` is itself a uniform subsample and later top-ups to a
    larger ``k`` extend the same plan instead of re-sampling.
    """

    if n_per_day <= 0:
        raise ValueError("n_per_day must be positive")
    required = {"date", "min_block", "max_block"}
    missing = required - set(days.columns)
    if missing:
        raise ValueError(f"days frame is missing columns: {sorted(missing)}")

    rng = np.random.default_rng(seed)
    rows = []
    for day in days.sort_values("date").itertuples(index=False):
        low = int(day.min_block)
        high = int(day.max_block)
        if high < low:
            raise ValueError(f"day {day.date} has max_block < min_block")
        count = min(int(n_per_day), high - low + 1)
        blocks = rng.choice(np.arange(low, high + 1), size=count, replace=False)
        for rank, block_number in enumerate(blocks):
            rows.append(
                {
                    "date": day.date,
                    "block_number": int(block_number),
                    "sample_rank": rank,
                }
            )
    return pd.DataFrame(rows)


def _summarize_access_lists(
    block_number: int,
    transactions: Sequence[dict[str, Any]],
) -> dict[str, int]:
    tx_count = 0
    address_count = 0
    storage_key_count = 0
    byte_count = 0
    gas_7981 = 0
    for tx_index, tx in enumerate(transactions):
        if not tx.get("accessList"):
            continue
        record = decode_access_list_transaction_record(
            block_number=block_number,
            tx_index=tx_index,
            tx=tx,
        )
        tx_count += 1
        address_count += record.access_list_address_count
        storage_key_count += record.access_list_storage_key_count
        byte_count += record.access_list_bytes
        gas_7981 += record.access_list_gas
    return {
        "tx_access_list_tx_count": tx_count,
        "tx_access_list_address_count": address_count,
        "tx_access_list_storage_key_count": storage_key_count,
        "tx_access_list_bytes": byte_count,
        "tx_access_list_gas_7981": gas_7981,
    }


def _summarize_authorizations(
    block_number: int,
    transactions: Sequence[dict[str, Any]],
    network_chain_id: int,
) -> dict[str, int]:
    type4_tx_count = 0
    tuple_count = 0
    rlp_bytes = 0
    bytes_8131 = 0
    set_count = 0
    clear_count = 0
    for tx_index, tx in enumerate(transactions):
        if parse_quantity(tx.get("type"), default=0) != 4:
            continue
        type4_tx_count += 1
        for auth_index, auth in enumerate(tx.get("authorizationList") or []):
            record = decode_authorization_record(
                block_number=block_number,
                tx_index=tx_index,
                tx_hash=str(tx.get("hash", "")),
                auth_index=auth_index,
                auth=auth,
                network_chain_id=network_chain_id,
            )
            tuple_count += 1
            rlp_bytes += record.authorization_tuple_rlp_bytes
            bytes_8131 += record.authorization_tuple_8131_bytes
            if record.is_clear:
                clear_count += 1
            else:
                set_count += 1
    return {
        "type4_tx_count": type4_tx_count,
        "authorization_tuple_count": tuple_count,
        "authorization_tuple_rlp_bytes": rlp_bytes,
        "authorization_tuple_8131_bytes": bytes_8131,
        "authorization_set_tuple_count": set_count,
        "authorization_clear_tuple_count": clear_count,
    }


def _calldata_bytes(transactions: Sequence[dict[str, Any]]) -> int:
    total = 0
    for tx in transactions:
        data = tx.get("input") or "0x"
        total += max(0, (len(data) - 2) // 2)
    return total


def _summarize_blob_versioned_hashes(
    transactions: Sequence[dict[str, Any]],
) -> dict[str, int]:
    count = 0
    for tx in transactions:
        count += len(tx.get("blobVersionedHashes") or [])
    return {
        "blob_versioned_hash_count": count,
        "blob_versioned_hash_bytes": 32 * count,
    }


def calibration_row_from_block_data(
    *,
    block_number: int,
    diff_trace: list[dict[str, Any]],
    full_trace: list[dict[str, Any]] | None,
    block_info: dict[str, Any],
    receipts: list[dict[str, Any]],
    cpsb: int = 1530,
    include_reads: bool = True,
    include_system_changes: bool = True,
    include_bal: bool = True,
    network_chain_id: int = 1,
    rpc_url: str | None = None,
    rpc_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one combined calibration row from pre-fetched block data."""

    transactions = block_info.get("transactions") or []

    state = summarize_rpc_state_growth_from_traces(
        block_number=block_number,
        diff_trace=diff_trace,
        receipts=receipts,
        cpsb=cpsb,
    )
    row: dict[str, Any] = state.as_dict()
    row["calldata_bytes_rpc"] = _calldata_bytes(transactions)
    row.update(_summarize_blob_versioned_hashes(transactions))
    if include_bal:
        bal = build_rpc_bal_from_traces(
            block_number=block_number,
            diff_trace=diff_trace,
            full_trace=full_trace,
            block_info=block_info,
            receipts=receipts,
            rpc_url=rpc_url,
            rpc_headers=rpc_headers,
            include_reads=include_reads,
            include_system_changes=include_system_changes,
        ).summary
        row["bal_rlp_bytes"] = bal.bal_rlp_bytes
        row["bal_accounts"] = bal.accounts
        row["bal_storage_write_slots"] = bal.storage_write_slots
        row["bal_storage_write_changes"] = bal.storage_write_changes
        row["bal_storage_reads"] = bal.storage_reads
        row["bal_balance_changes"] = bal.balance_changes
        row["bal_nonce_changes"] = bal.nonce_changes
        row["bal_code_bytes"] = bal.code_bytes
        row["bal_storage_writes_rlp_bytes"] = bal.storage_writes_rlp_bytes
        row["bal_storage_reads_rlp_bytes"] = bal.storage_reads_rlp_bytes
        row["bal_balance_changes_rlp_bytes"] = bal.balance_changes_rlp_bytes
        row["bal_nonce_changes_rlp_bytes"] = bal.nonce_changes_rlp_bytes
        row["bal_code_changes_rlp_bytes"] = bal.code_changes_rlp_bytes
        row["bal_account_shell_rlp_bytes"] = bal.account_shell_rlp_bytes
        row["bal_include_reads"] = bal.include_reads
        row["bal_include_system_changes"] = bal.include_system_changes
    row.update(_summarize_access_lists(block_number, transactions))
    row.update(
        _summarize_authorizations(block_number, transactions, network_chain_id)
    )
    return row


def calibrate_block(
    rpc_url: str,
    block_number: int,
    *,
    cpsb: int = 1530,
    include_reads: bool = True,
    include_system_changes: bool = True,
    include_bal: bool = True,
    network_chain_id: int = 1,
    rpc_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch one block's shared RPC data and build its calibration row."""

    diff_trace = fetch_block_trace(
        rpc_url,
        block_number,
        diff_mode=True,
        headers=rpc_headers,
    )
    full_trace = (
        fetch_block_trace(
            rpc_url,
            block_number,
            diff_mode=False,
            headers=rpc_headers,
        )
        if include_bal and include_reads
        else None
    )
    receipts = rpc_call(
        rpc_url,
        "eth_getBlockReceipts",
        [hex(block_number)],
        timeout=120,
        headers=rpc_headers,
    )
    block_info = rpc_call(
        rpc_url,
        "eth_getBlockByNumber",
        [hex(block_number), True],
        timeout=120,
        headers=rpc_headers,
    )
    return calibration_row_from_block_data(
        block_number=block_number,
        diff_trace=diff_trace,
        full_trace=full_trace,
        block_info=block_info,
        receipts=receipts,
        cpsb=cpsb,
        include_reads=include_reads,
        include_system_changes=include_system_changes,
        include_bal=include_bal,
        network_chain_id=network_chain_id,
        rpc_url=rpc_url,
        rpc_headers=rpc_headers,
    )


def calibrate_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    cpsb: int = 1530,
    include_reads: bool = True,
    include_system_changes: bool = True,
    include_bal: bool = True,
    network_chain_id: int = 1,
    rpc_headers: dict[str, str] | None = None,
    max_workers: int = 8,
    max_retries: int = 4,
    retry_sleep_seconds: float = 2.0,
    on_error: str = "raise",
) -> tuple[pd.DataFrame, list[int]]:
    """Calibrate many blocks in parallel.

    Returns ``(frame, failed_blocks)``. With ``on_error="skip"``, blocks that
    still fail after retries are collected in ``failed_blocks`` instead of
    aborting the run, so long resumable loops can retry them later.
    """

    if on_error not in {"raise", "skip"}:
        raise ValueError("on_error must be 'raise' or 'skip'")

    def run_one(block_number: int) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(int(max_retries)):
            try:
                return calibrate_block(
                    rpc_url,
                    int(block_number),
                    cpsb=cpsb,
                    include_reads=include_reads,
                    include_system_changes=include_system_changes,
                    include_bal=include_bal,
                    network_chain_id=network_chain_id,
                    rpc_headers=rpc_headers,
                )
            except Exception as exc:  # noqa: BLE001 - retried, then surfaced.
                last_error = exc
                time.sleep(retry_sleep_seconds * (attempt + 1))
        if on_error == "raise":
            raise RuntimeError(
                f"calibration failed for block {block_number}: {last_error}"
            )
        return None

    blocks = [int(block) for block in block_numbers]
    rows: list[dict[str, Any]] = []
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for block_number, row in zip(blocks, pool.map(run_one, blocks)):
            if row is None:
                failed.append(block_number)
            else:
                rows.append(row)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("block_number").reset_index(drop=True)
    return frame, failed


def per_tx_bal_bytes(
    *,
    block_number: int,
    diff_trace: list[dict[str, Any]],
    full_trace: list[dict[str, Any]] | None,
    block_info: dict[str, Any],
    receipts: list[dict[str, Any]],
    include_reads: bool = True,
) -> dict[int, int]:
    """Attribute a block's BAL RLP bytes to its transactions.

    Builds the block BAL once, then attributes bytes to transactions in a
    single pass over the built account structure: every write/balance/nonce/
    code change already carries its block-access index (``tx_index + 1``), so
    each change's own RLP tuple bytes are credited to that transaction. The
    unattributed remainder (read entries, storage-slot keys, account shells,
    list framing) is distributed pro-rata to each transaction's change bytes,
    so the per-tx totals sum to the block ``bal_rlp_bytes``. Reads carry no
    transaction index and so contribute only through that shared remainder;
    with ``include_reads=False`` the attribution is purely the write/balance/
    nonce/code state-access signal, which is what the bundle-coupling
    exposures need. System-call changes are excluded (they are not
    transactions).
    """

    result = build_rpc_bal_from_traces(
        block_number=block_number,
        diff_trace=diff_trace,
        full_trace=full_trace,
        block_info=block_info,
        receipts=receipts,
        include_reads=include_reads,
        include_system_changes=False,
    )

    raw: dict[int, int] = defaultdict(int)
    for _address, writes, _reads, balances, nonces, codes in result.accounts:
        for _slot, changes in writes:
            for access_index, value in changes:
                if access_index >= 1:
                    raw[access_index - 1] += len(rlp.encode([access_index, value]))
        for entries in (balances, nonces, codes):
            for access_index, value in entries:
                if access_index >= 1:
                    raw[access_index - 1] += len(rlp.encode([access_index, value]))

    total_raw = sum(raw.values())
    n_tx = len(diff_trace)
    if total_raw <= 0:
        return {i: 0 for i in range(n_tx)}

    scale = float(result.summary.bal_rlp_bytes) / total_raw
    out = {i: 0 for i in range(n_tx)}
    for tx_index, byte_count in raw.items():
        out[tx_index] = int(round(byte_count * scale))
    return out


def fetch_per_tx_bal_for_block(
    rpc_url: str,
    block_number: int,
    *,
    include_reads: bool = True,
    rpc_headers: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fetch traces for one block and return per-tx BAL bytes rows."""

    diff_trace = fetch_block_trace(
        rpc_url, block_number, diff_mode=True, headers=rpc_headers
    )
    full_trace = (
        fetch_block_trace(rpc_url, block_number, diff_mode=False, headers=rpc_headers)
        if include_reads
        else None
    )
    receipts = rpc_call(
        rpc_url,
        "eth_getBlockReceipts",
        [hex(block_number)],
        timeout=120,
        headers=rpc_headers,
    )
    block_info = rpc_call(
        rpc_url,
        "eth_getBlockByNumber",
        [hex(block_number), True],
        timeout=120,
        headers=rpc_headers,
    )
    per_tx = per_tx_bal_bytes(
        block_number=block_number,
        diff_trace=diff_trace,
        full_trace=full_trace,
        block_info=block_info,
        receipts=receipts,
        include_reads=include_reads,
    )
    return pd.DataFrame(
        [
            {"block_number": int(block_number), "tx_index": int(i), "bal_rlp_bytes": int(b)}
            for i, b in sorted(per_tx.items())
        ]
    )


def fetch_per_tx_bal_for_blocks(
    rpc_url: str,
    block_numbers: Sequence[int],
    *,
    include_reads: bool = True,
    rpc_headers: dict[str, str] | None = None,
    max_workers: int = 8,
    max_retries: int = 4,
    retry_sleep_seconds: float = 2.0,
) -> tuple[pd.DataFrame, list[int]]:
    """Per-tx BAL bytes for many blocks, parallel and retrying."""

    def run_one(block_number: int) -> pd.DataFrame | None:
        for attempt in range(int(max_retries)):
            try:
                return fetch_per_tx_bal_for_block(
                    rpc_url,
                    int(block_number),
                    include_reads=include_reads,
                    rpc_headers=rpc_headers,
                )
            except Exception:  # noqa: BLE001 - retried then skipped.
                time.sleep(retry_sleep_seconds * (attempt + 1))
        return None

    blocks = [int(b) for b in block_numbers]
    frames: list[pd.DataFrame] = []
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for block_number, frame in zip(blocks, pool.map(run_one, blocks)):
            if frame is None:
                failed.append(block_number)
            else:
                frames.append(frame)
    combined = (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=["block_number", "tx_index", "bal_rlp_bytes"]
        )
    )
    return combined, failed
