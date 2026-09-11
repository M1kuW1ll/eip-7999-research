"""Xatu queries used only by the independent shared-fee calibration."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def _normalize(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def query_transaction_identity(
    client,
    block_numbers: Sequence[int],
    *,
    network: str = "mainnet",
) -> pd.DataFrame:
    """Return the transaction properties needed for the EIP-2780 floor base."""

    blocks = sorted({int(block) for block in block_numbers})
    columns = [
        "block_number",
        "tx_index",
        "tx_hash",
        "has_recipient",
        "self_transfer",
        "transfers_value",
    ]
    if not blocks:
        return pd.DataFrame(columns=columns)

    hashes_frame = client.query_df(
        """
        SELECT block_number, block_hash
        FROM default.canonical_execution_block FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        ORDER BY block_number
        """,
        parameters={"network": network, "blocks": blocks},
    )
    if hashes_frame.empty:
        return pd.DataFrame(columns=columns)
    hashes = [_normalize(value) for value in hashes_frame["block_hash"]]

    frame = client.query_df(
        """
        SELECT
            block_number,
            position AS tx_index,
            hash AS tx_hash,
            `to` IS NOT NULL AS has_recipient,
            `to` IS NOT NULL AND lower(`from`) = lower(`to`) AS self_transfer,
            value > 0 AS transfers_value
        FROM default.execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_hash IN {hashes:Array(FixedString(66))}
        ORDER BY block_number, position
        """,
        parameters={"network": network, "hashes": hashes},
    )
    frame["tx_hash"] = frame["tx_hash"].map(_normalize)
    frame[["block_number", "tx_index"]] = frame[
        ["block_number", "tx_index"]
    ].astype("int64")
    for column in ["has_recipient", "self_transfer", "transfers_value"]:
        frame[column] = frame[column].astype(bool)
    if frame.duplicated(["block_number", "tx_index", "tx_hash"]).any():
        raise ValueError("Xatu transaction identity contains duplicate transactions")
    return frame[columns]


def query_execution_repricing_components(
    client,
    block_numbers: Sequence[int],
    *,
    network: str = "mainnet",
) -> pd.DataFrame:
    """Return sparse per-transaction inputs for EIP-8038 repricing.

    This query is intentionally separate from the already cached transaction
    membership. It retrieves only fields absent from that cache.
    """

    blocks = sorted({int(block) for block in block_numbers})
    keys = ["block_number", "tx_index", "tx_hash"]
    value_columns = [
        "sstore_count",
        "sstore_gas_current",
        "sstore_cold_count",
        "sload_cold_count",
        "account_cold_count",
        "ext_second_read_count",
        "internal_create_opcode_count",
        "refund_counter_current",
        "changed_slots",
        "zero_to_nonzero_slots",
        "original_nonzero_changed",
        "net_cleared_slots",
        "positive_value_internal_calls",
        "successful_internal_creates",
    ]
    if not blocks:
        return pd.DataFrame(columns=[*keys, *value_columns])
    params = {"network": network, "blocks": blocks, "zero": "0x" + "00" * 32}
    settings = {"max_execution_time": 900}

    operations = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            sumIf(opcode_count, operation = 'SSTORE') AS sstore_count,
            sumIf(gas, operation = 'SSTORE') AS sstore_gas_current,
            sumIf(cold_access_count, operation = 'SSTORE') AS sstore_cold_count,
            sumIf(cold_access_count, operation = 'SLOAD') AS sload_cold_count,
            sumIf(cold_access_count, operation IN (
                'BALANCE', 'EXTCODEHASH', 'EXTCODESIZE', 'EXTCODECOPY',
                'CALL', 'CALLCODE', 'DELEGATECALL', 'STATICCALL', 'SELFDESTRUCT'
            )) AS account_cold_count,
            sumIf(opcode_count, operation IN ('EXTCODESIZE', 'EXTCODECOPY'))
                AS ext_second_read_count,
            sumIf(opcode_count, operation IN ('CREATE', 'CREATE2'))
                AS internal_create_opcode_count,
            maxIf(ifNull(gas_refund, 0), operation = '' AND call_frame_id = 0)
                AS refund_counter_current
        FROM default.canonical_execution_transaction_structlog_agg FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
        settings=settings,
    )
    storage = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            count() AS changed_slots,
            countIf(lower(from_value) = {zero:String} AND lower(to_value) != {zero:String})
                AS zero_to_nonzero_slots,
            countIf(lower(from_value) != {zero:String}) AS original_nonzero_changed,
            countIf(lower(from_value) != {zero:String} AND lower(to_value) = {zero:String})
                AS net_cleared_slots
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
        settings=settings,
    )
    traces = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            countIf(
                action_type = 'call' AND trace_address IS NOT NULL
                AND action_call_type IN ('call', 'call_code') AND action_value > 0
            ) AS positive_value_internal_calls,
            countIf(
                action_type = 'create' AND trace_address IS NOT NULL
                AND error IS NULL AND result_address IS NOT NULL
            ) AS successful_internal_creates
        FROM default.canonical_execution_traces FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
        settings=settings,
    )

    frames = []
    for frame in (operations, storage, traces):
        if frame.empty:
            continue
        frame = frame.copy()
        frame["tx_hash"] = frame["tx_hash"].map(_normalize)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=[*keys, *value_columns])
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on=keys, how="outer", validate="one_to_one")
    for column in value_columns:
        if column not in out:
            out[column] = 0
        out[column] = pd.to_numeric(out[column], errors="raise").fillna(0).astype("int64")
    if out.duplicated(keys).any():
        raise ValueError("Execution repricing inputs contain duplicate transactions")
    return out[[*keys, *value_columns]].sort_values(keys).reset_index(drop=True)
