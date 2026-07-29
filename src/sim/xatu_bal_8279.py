"""Reconstruct the EIP-8279 transaction-local runtime BAL byte counter.

The public Xatu tables expose the runtime events needed for most EIP-8279
components. Cold accesses and value-bearing calls remain observable when their
call frame reverts, so they are included. Storage diffs contain only changes
that remain after transaction execution. EIP-8279 retains the 32-byte charge
for a storage-value change inside a reverted frame, but Xatu has no final diff
from which to recover it. The reconstructed total can therefore understate the
counter by these specific reverted storage-value charges.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


BAL_BYTES_PER_ADDRESS = 20
BAL_BYTES_PER_STORAGE_KEY = 32
BAL_BYTES_PER_STORAGE_VALUE = 32
BAL_BYTES_PER_BALANCE = 32
BAL_BYTES_PER_NONCE = 8

STATE_BYTES_PER_STORAGE_SET = 64
STATE_BYTES_PER_NEW_ACCOUNT = 120
STATE_BYTES_PER_DELEGATION_INDICATOR = 23

RUNTIME_COUNT_COLUMNS = [
    "cold_account_accesses",
    "cold_storage_accesses",
    "storage_value_entries_observed",
    "positive_value_calls",
    "positive_value_selfdestructs",
    "internal_creates",
    "internal_create_endowments",
    "internal_deployed_code_bytes",
]

RUNTIME_BYTE_COLUMNS = [
    "account_access_bytes_8279",
    "storage_key_bytes_8279",
    "storage_value_bytes_8279_observed",
    "balance_call_bytes_8279",
    "balance_selfdestruct_bytes_8279",
    "create_address_bytes_8279",
    "create_nonce_bytes_8279",
    "create_endowment_bytes_8279",
    "deployed_code_bytes_8279",
]

DIRECT_STATE_BYTE_COLUMNS = [
    "direct_new_storage_key_bytes_8279",
    "direct_new_storage_value_bytes_8279",
    "direct_new_account_access_bytes_8279",
    "direct_new_account_balance_bytes_8279",
    "direct_create_address_bytes_8279",
    "direct_create_nonce_bytes_8279",
    "direct_create_endowment_bytes_8279",
    "direct_deployed_code_bytes_8279",
]

RUNTIME_COMPONENT_SPECS = [
    (
        "storage_key",
        ["storage_key_bytes_8279"],
        ["direct_new_storage_key_bytes_8279"],
    ),
    (
        "storage_value",
        ["storage_value_bytes_8279_observed"],
        ["direct_new_storage_value_bytes_8279"],
    ),
    (
        "account_access",
        ["account_access_bytes_8279"],
        ["direct_new_account_access_bytes_8279"],
    ),
    (
        "value_transfer",
        [
            "balance_call_bytes_8279",
            "balance_selfdestruct_bytes_8279",
            "create_endowment_bytes_8279",
        ],
        [
            "direct_new_account_balance_bytes_8279",
            "direct_create_endowment_bytes_8279",
        ],
    ),
    (
        "contract_creation",
        ["create_address_bytes_8279", "create_nonce_bytes_8279"],
        ["direct_create_address_bytes_8279", "direct_create_nonce_bytes_8279"],
    ),
    (
        "deployed_code",
        ["deployed_code_bytes_8279"],
        ["direct_deployed_code_bytes_8279"],
    ),
]


def _blocks(block_numbers: Sequence[int]) -> list[int]:
    return sorted({int(block) for block in block_numbers})


def _normalize_hash(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def empty_runtime_meter_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "block_number",
            "tx_index",
            "tx_hash",
            *RUNTIME_COUNT_COLUMNS,
            *RUNTIME_BYTE_COLUMNS,
            "bal_runtime_bytes_8279",
            "meter_reconstruction_status",
        ]
    )


def empty_runtime_block_frame() -> pd.DataFrame:
    """Return the schema for block-level EIP-8279 runtime reconstruction."""

    return pd.DataFrame(
        columns=[
            "block_number",
            *RUNTIME_COUNT_COLUMNS,
            *RUNTIME_BYTE_COLUMNS,
            "bal_runtime_bytes_8279",
            "meter_reconstruction_status",
        ]
    )


def compute_eip8279_runtime_bytes(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert transaction-level event counts into EIP-8279 runtime bytes."""

    required = {"block_number", "tx_index", "tx_hash", *RUNTIME_COUNT_COLUMNS}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing EIP-8279 runtime count columns: {missing}")

    out = frame.copy()
    for column in RUNTIME_COUNT_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="raise").fillna(0)
        if (out[column] < 0).any():
            raise ValueError(f"EIP-8279 runtime count cannot be negative: {column}")
        out[column] = out[column].astype("int64")

    out["account_access_bytes_8279"] = (
        BAL_BYTES_PER_ADDRESS * out["cold_account_accesses"]
    )
    out["storage_key_bytes_8279"] = (
        BAL_BYTES_PER_STORAGE_KEY * out["cold_storage_accesses"]
    )
    out["storage_value_bytes_8279_observed"] = (
        BAL_BYTES_PER_STORAGE_VALUE * out["storage_value_entries_observed"]
    )
    out["balance_call_bytes_8279"] = BAL_BYTES_PER_BALANCE * out["positive_value_calls"]
    out["balance_selfdestruct_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * out["positive_value_selfdestructs"]
    )
    out["create_address_bytes_8279"] = BAL_BYTES_PER_ADDRESS * out["internal_creates"]
    out["create_nonce_bytes_8279"] = BAL_BYTES_PER_NONCE * out["internal_creates"]
    out["create_endowment_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * out["internal_create_endowments"]
    )
    out["deployed_code_bytes_8279"] = out["internal_deployed_code_bytes"]
    out["bal_runtime_bytes_8279"] = out[RUNTIME_BYTE_COLUMNS].sum(axis=1)
    out["meter_reconstruction_status"] = (
        "xatu_observed_path; excludes storage-value bytes from reverted frames"
    )

    int_columns = [
        "block_number",
        "tx_index",
        *RUNTIME_COUNT_COLUMNS,
        *RUNTIME_BYTE_COLUMNS,
        "bal_runtime_bytes_8279",
    ]
    out[int_columns] = out[int_columns].astype("int64")
    return out[empty_runtime_meter_frame().columns]


def compute_eip8279_runtime_block_bytes(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert block-level event counts into EIP-8279 runtime bytes."""

    required = {"block_number", *RUNTIME_COUNT_COLUMNS}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing block-level EIP-8279 count columns: {missing}")

    out = frame.copy()
    for column in RUNTIME_COUNT_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="raise").fillna(0)
        if (out[column] < 0).any():
            raise ValueError(f"EIP-8279 runtime count cannot be negative: {column}")
        out[column] = out[column].astype("int64")

    out["account_access_bytes_8279"] = (
        BAL_BYTES_PER_ADDRESS * out["cold_account_accesses"]
    )
    out["storage_key_bytes_8279"] = (
        BAL_BYTES_PER_STORAGE_KEY * out["cold_storage_accesses"]
    )
    out["storage_value_bytes_8279_observed"] = (
        BAL_BYTES_PER_STORAGE_VALUE * out["storage_value_entries_observed"]
    )
    out["balance_call_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * out["positive_value_calls"]
    )
    out["balance_selfdestruct_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * out["positive_value_selfdestructs"]
    )
    out["create_address_bytes_8279"] = BAL_BYTES_PER_ADDRESS * out["internal_creates"]
    out["create_nonce_bytes_8279"] = BAL_BYTES_PER_NONCE * out["internal_creates"]
    out["create_endowment_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * out["internal_create_endowments"]
    )
    out["deployed_code_bytes_8279"] = out["internal_deployed_code_bytes"]
    out["bal_runtime_bytes_8279"] = out[RUNTIME_BYTE_COLUMNS].sum(axis=1)
    out["meter_reconstruction_status"] = (
        "xatu block-level observed path; excludes storage-value bytes from reverted frames"
    )

    int_columns = [
        "block_number",
        *RUNTIME_COUNT_COLUMNS,
        *RUNTIME_BYTE_COLUMNS,
        "bal_runtime_bytes_8279",
    ]
    out[int_columns] = out[int_columns].astype("int64")
    return out[empty_runtime_block_frame().columns]


def query_xatu_eip8279_runtime_meter(
    client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Query Xatu and reconstruct the transaction-level EIP-8279 counter.

    Top-level transaction entries and the 51-byte authorization contribution
    are intentionally excluded: EIP-8279 covers those through transaction-base
    headroom and the static floor, respectively, rather than ``bal_data_bytes``.
    """

    blocks = _blocks(block_numbers)
    if not blocks:
        return empty_runtime_meter_frame()
    params = {"network": network, "blocks": blocks}

    operations = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            sumIf(cold_access_count, operation IN (
                'BALANCE', 'EXTCODEHASH', 'EXTCODESIZE', 'EXTCODECOPY',
                'CALL', 'CALLCODE', 'DELEGATECALL', 'STATICCALL',
                'SELFDESTRUCT'
            )) AS cold_account_accesses,
            sumIf(cold_access_count, operation IN ('SLOAD', 'SSTORE'))
                AS cold_storage_accesses
        FROM default.canonical_execution_transaction_structlog_agg FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    storage = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            uniqExact(tuple(lower(address), lower(slot)))
                AS storage_value_entries_observed
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
          AND lower(from_value) != lower(to_value)
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    traces = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'call'
                AND action_call_type = 'call'
                AND action_value > 0
                AND lower(action_from) != lower(ifNull(action_to, ''))
            ) AS positive_value_calls,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'suicide'
                AND action_value > 0
                AND lower(action_from) != lower(ifNull(action_to, ''))
            ) AS positive_value_selfdestructs,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'create'
            ) AS internal_creates,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'create'
                AND action_value > 0
            ) AS internal_create_endowments,
            sumIf(
                if(
                    result_code IS NULL OR length(result_code) < 2,
                    0,
                    intDiv(length(result_code) - 2, 2)
                ),
                trace_address IS NOT NULL
                AND action_type = 'create'
                AND error IS NULL
                AND result_address IS NOT NULL
            ) AS internal_deployed_code_bytes
        FROM default.canonical_execution_traces FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    frames = []
    for frame in [operations, storage, traces]:
        if frame.empty:
            continue
        frame = frame.copy()
        frame["tx_hash"] = frame["tx_hash"].map(_normalize_hash)
        frames.append(frame)
    if not frames:
        return empty_runtime_meter_frame()

    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(
            frame,
            on=["block_number", "tx_index", "tx_hash"],
            how="outer",
            validate="one_to_one",
        )
    for column in RUNTIME_COUNT_COLUMNS:
        if column not in out:
            out[column] = 0
        out[column] = out[column].fillna(0)
    return compute_eip8279_runtime_bytes(out)


def query_xatu_eip8279_runtime_blocks(
    client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Reconstruct EIP-8279 runtime bytes directly for a block panel.

    This block-level query uses the same protocol event counts as the
    transaction-level reconstruction but returns only one row per requested
    block.  It is intended for wider anchor panels where transaction-level
    attribution is unnecessary.
    """

    blocks = _blocks(block_numbers)
    if not blocks:
        return empty_runtime_block_frame()
    params = {"network": network, "blocks": blocks}

    operations = client.query_df(
        """
        SELECT
            block_number,
            sumIf(cold_access_count, operation IN (
                'BALANCE', 'EXTCODEHASH', 'EXTCODESIZE', 'EXTCODECOPY',
                'CALL', 'CALLCODE', 'DELEGATECALL', 'STATICCALL',
                'SELFDESTRUCT'
            )) AS cold_account_accesses,
            sumIf(cold_access_count, operation IN ('SLOAD', 'SSTORE'))
                AS cold_storage_accesses
        FROM default.canonical_execution_transaction_structlog_agg FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number
        """,
        parameters=params,
    )

    storage = client.query_df(
        """
        SELECT
            block_number,
            uniqExact(tuple(transaction_index, lower(address), lower(slot)))
                AS storage_value_entries_observed
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
          AND lower(from_value) != lower(to_value)
        GROUP BY block_number
        """,
        parameters=params,
    )

    traces = client.query_df(
        """
        SELECT
            block_number,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'call'
                AND action_call_type = 'call'
                AND action_value > 0
                AND lower(action_from) != lower(ifNull(action_to, ''))
            ) AS positive_value_calls,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'suicide'
                AND action_value > 0
                AND lower(action_from) != lower(ifNull(action_to, ''))
            ) AS positive_value_selfdestructs,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'create'
            ) AS internal_creates,
            countIf(
                trace_address IS NOT NULL
                AND action_type = 'create'
                AND action_value > 0
            ) AS internal_create_endowments,
            sumIf(
                if(
                    result_code IS NULL OR length(result_code) < 2,
                    0,
                    intDiv(length(result_code) - 2, 2)
                ),
                trace_address IS NOT NULL
                AND action_type = 'create'
                AND error IS NULL
                AND result_address IS NOT NULL
            ) AS internal_deployed_code_bytes
        FROM default.canonical_execution_traces FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number
        """,
        parameters=params,
    )

    out = pd.DataFrame({"block_number": blocks})
    for frame in [operations, storage, traces]:
        if frame.empty:
            continue
        out = out.merge(frame, on="block_number", how="left", validate="one_to_one")
    for column in RUNTIME_COUNT_COLUMNS:
        if column not in out:
            out[column] = 0
        out[column] = out[column].fillna(0)
    return compute_eip8279_runtime_block_bytes(out)


def attach_state_bundle(
    runtime_meter: pd.DataFrame,
    state_creation: pd.DataFrame,
) -> pd.DataFrame:
    """Classify runtime-meter bytes by positive transaction-level state gas."""

    required_meter = {"block_number", "tx_index", "tx_hash", "bal_runtime_bytes_8279"}
    missing_meter = sorted(required_meter.difference(runtime_meter.columns))
    if missing_meter:
        raise ValueError(f"Missing runtime-meter columns: {missing_meter}")

    state_columns = [
        "block_number",
        "tx_index",
        "tx_hash",
        "new_storage_slots",
        "new_accounts",
        "code_bytes",
        "new_delegation_indicators",
        "historical_state_creation_gas",
    ]
    missing_state = sorted(set(state_columns).difference(state_creation.columns))
    if missing_state:
        raise ValueError(f"Missing state-creation columns: {missing_state}")

    meter = runtime_meter.copy()
    meter["tx_hash"] = meter["tx_hash"].map(_normalize_hash)
    state = state_creation[state_columns].copy()
    state["tx_hash"] = state["tx_hash"].map(_normalize_hash)
    out = meter.merge(
        state,
        on=["block_number", "tx_index", "tx_hash"],
        how="left",
        validate="one_to_one",
    )
    state_numeric = state_columns[3:]
    out[state_numeric] = out[state_numeric].fillna(0).astype("int64")
    out["state_bundle"] = out["historical_state_creation_gas"] > 0
    out["bal_runtime_bytes_state_bundle_8279"] = out["bal_runtime_bytes_8279"].where(
        out["state_bundle"], 0
    )
    out["bal_runtime_bytes_execution_access_8279"] = out[
        "bal_runtime_bytes_8279"
    ].where(~out["state_bundle"], 0)
    return out


def runtime_bundle_parameter_card(classified: pd.DataFrame) -> pd.DataFrame:
    """Return the priced-byte anchor and state/execution bundle weights."""

    total = int(classified["bal_runtime_bytes_8279"].sum())
    state = int(classified["bal_runtime_bytes_state_bundle_8279"].sum())
    execution = int(classified["bal_runtime_bytes_execution_access_8279"].sum())
    if total <= 0:
        raise ValueError("Cannot estimate bundle weights with zero runtime BAL bytes")
    if state + execution != total:
        raise ValueError("State and execution/access runtime bytes do not reconcile")
    blocks = int(classified["block_number"].nunique())
    return pd.DataFrame(
        [
            {
                "sample_blocks": blocks,
                "sample_transactions_with_runtime_bytes": int(
                    (classified["bal_runtime_bytes_8279"] > 0).sum()
                ),
                "bal_runtime_bytes_8279": total,
                "bal_runtime_bytes_per_block_8279": total / blocks,
                "state_bundle_runtime_bytes_8279": state,
                "execution_access_runtime_bytes_8279": execution,
                "state_bundle_weight_8279": state / total,
                "execution_access_weight_8279": execution / total,
                "state_bundle_definition": (
                    "transaction has positive historical state-creation gas"
                ),
                "meter_reconstruction_status": (
                    "xatu_observed_path; excludes storage-value bytes from reverted frames"
                ),
            }
        ]
    )


def attribute_direct_state_runtime_bytes(classified: pd.DataFrame) -> pd.DataFrame:
    """Match direct state-creation bytes within the EIP-8279 runtime counter.

    The direct-state attribution is performed in runtime-meter units and at
    transaction level.  Exact matches are available for final new storage
    values and deployed code.  Cold key/address and balance bytes lack target
    addresses in Xatu's aggregate structlogs, so they are conservatively
    matched within each transaction and capped by both the state-creation count
    and the corresponding runtime event count.

    EIP-7702 delegation bytes are static under EIP-8279 and are therefore not
    part of ``bal_data_bytes`` or this runtime partition.
    """

    required = {
        "bal_runtime_bytes_8279",
        "bal_runtime_bytes_state_bundle_8279",
        "bal_runtime_bytes_execution_access_8279",
        "state_bundle",
        "new_storage_slots",
        "new_accounts",
        "code_bytes",
        "cold_storage_accesses",
        "storage_value_entries_observed",
        "cold_account_accesses",
        "positive_value_calls",
        "positive_value_selfdestructs",
        "internal_creates",
        "internal_create_endowments",
        "deployed_code_bytes_8279",
    }
    missing = sorted(required.difference(classified.columns))
    if missing:
        raise ValueError(f"Missing direct-state attribution columns: {missing}")

    out = classified.copy()
    numeric = sorted(required.difference({"state_bundle"}))
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise").fillna(0)
    if (out[numeric] < 0).any().any():
        raise ValueError("Direct-state attribution inputs cannot be negative")

    matched_storage_keys = out[["new_storage_slots", "cold_storage_accesses"]].min(
        axis=1
    )
    matched_storage_values = out[
        ["new_storage_slots", "storage_value_entries_observed"]
    ].min(axis=1)
    matched_create_accounts = out[["new_accounts", "internal_creates"]].min(axis=1)
    matched_create_endowments = pd.concat(
        [matched_create_accounts, out["internal_create_endowments"]], axis=1
    ).min(axis=1)
    remaining_new_accounts = (out["new_accounts"] - matched_create_accounts).clip(
        lower=0
    )
    matched_account_accesses = pd.concat(
        [remaining_new_accounts, out["cold_account_accesses"]], axis=1
    ).min(axis=1)
    matched_new_account_balances = pd.concat(
        [
            remaining_new_accounts,
            out["positive_value_calls"] + out["positive_value_selfdestructs"],
        ],
        axis=1,
    ).min(axis=1)

    out["direct_new_storage_key_bytes_8279"] = (
        BAL_BYTES_PER_STORAGE_KEY * matched_storage_keys
    )
    out["direct_new_storage_value_bytes_8279"] = (
        BAL_BYTES_PER_STORAGE_VALUE * matched_storage_values
    )
    out["direct_new_account_access_bytes_8279"] = (
        BAL_BYTES_PER_ADDRESS * matched_account_accesses
    )
    out["direct_new_account_balance_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * matched_new_account_balances
    )
    out["direct_create_address_bytes_8279"] = (
        BAL_BYTES_PER_ADDRESS * matched_create_accounts
    )
    out["direct_create_nonce_bytes_8279"] = (
        BAL_BYTES_PER_NONCE * matched_create_accounts
    )
    out["direct_create_endowment_bytes_8279"] = (
        BAL_BYTES_PER_BALANCE * matched_create_endowments
    )
    out["direct_deployed_code_bytes_8279"] = out[
        ["code_bytes", "deployed_code_bytes_8279"]
    ].min(axis=1)

    out[DIRECT_STATE_BYTE_COLUMNS] = out[DIRECT_STATE_BYTE_COLUMNS].astype("int64")
    out["bal_runtime_bytes_direct_state_8279"] = out[DIRECT_STATE_BYTE_COLUMNS].sum(
        axis=1
    )
    out["bal_runtime_bytes_coproduced_state_txs_8279"] = (
        out["bal_runtime_bytes_state_bundle_8279"]
        - out["bal_runtime_bytes_direct_state_8279"]
    )
    out["bal_runtime_bytes_nonstate_txs_8279"] = out[
        "bal_runtime_bytes_execution_access_8279"
    ]
    out["bal_runtime_bytes_access_related_8279"] = (
        out["bal_runtime_bytes_8279"]
        - out["bal_runtime_bytes_direct_state_8279"]
    )

    if (out["bal_runtime_bytes_coproduced_state_txs_8279"] < 0).any():
        raise ValueError("Direct-state bytes exceed state-bundle runtime bytes")
    reconciled = (
        out["bal_runtime_bytes_direct_state_8279"]
        + out["bal_runtime_bytes_coproduced_state_txs_8279"]
        + out["bal_runtime_bytes_nonstate_txs_8279"]
    )
    if not reconciled.equals(out["bal_runtime_bytes_8279"].astype("int64")):
        raise ValueError("Three-way runtime-byte attribution does not reconcile")
    if not (
        out["bal_runtime_bytes_direct_state_8279"]
        + out["bal_runtime_bytes_access_related_8279"]
    ).equals(out["bal_runtime_bytes_8279"].astype("int64")):
        raise ValueError("Two-way runtime-byte attribution does not reconcile")

    out["direct_state_attribution_status"] = (
        "transaction-level matched proxy; cold key/account targets unavailable"
    )
    return out


def aggregate_state_execution_runtime_blocks(
    attributed: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate transaction-level attribution into two- and three-way splits.

    ``state`` is the runtime-meter component matched directly to persistent
    state creation. ``execution`` is the remaining runtime BAL component. The
    latter is interpreted as access-related activity and is represented by an
    execution-activity proxy in the aggregate demand model; the name does not
    imply that every remaining byte is caused by execution gas itself.

    The three-way fields retain the subset of access-related bytes produced by
    state-creating transactions.  This lets the compact block cache support the
    co-produced-access sensitivity without retaining millions of transaction
    rows.
    """

    required = {
        "block_number",
        "state_bundle",
        "bal_runtime_bytes_8279",
        "bal_runtime_bytes_direct_state_8279",
        "bal_runtime_bytes_access_related_8279",
        *RUNTIME_COUNT_COLUMNS,
        *RUNTIME_BYTE_COLUMNS,
        *DIRECT_STATE_BYTE_COLUMNS,
    }
    missing = sorted(required.difference(attributed.columns))
    if missing:
        raise ValueError(f"Missing block-attribution columns: {missing}")

    out = attributed.copy()
    numeric = sorted(required.difference({"state_bundle"}))
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise").fillna(0)
    if (out[numeric] < 0).any().any():
        raise ValueError("Block-attribution inputs cannot be negative")

    out["transaction"] = 1
    out["runtime_transaction"] = out["bal_runtime_bytes_8279"] > 0
    out["state_runtime_transaction"] = out["state_bundle"] & out[
        "runtime_transaction"
    ]
    out["state_transaction"] = out["state_bundle"]
    out["direct_state_transaction"] = (
        out["bal_runtime_bytes_direct_state_8279"] > 0
    )
    component_three_way_columns = []
    for component, total_columns, direct_columns in RUNTIME_COMPONENT_SPECS:
        component_total = out[total_columns].sum(axis=1)
        component_direct = out[direct_columns].sum(axis=1)
        component_state_bundle = component_total.where(out["state_bundle"], 0)
        direct_column = f"{component}_bytes_direct_state_8279"
        coproduced_column = f"{component}_bytes_coproduced_state_txs_8279"
        nonstate_column = f"{component}_bytes_nonstate_txs_8279"
        out[direct_column] = component_direct
        out[coproduced_column] = component_state_bundle - component_direct
        out[nonstate_column] = component_total.where(~out["state_bundle"], 0)
        if (out[coproduced_column] < 0).any():
            raise ValueError(
                f"Direct-state bytes exceed state-bundle bytes for {component}"
            )
        if not (
            out[direct_column]
            + out[coproduced_column]
            + out[nonstate_column]
        ).equals(component_total):
            raise ValueError(f"Three-way component attribution failed for {component}")
        component_three_way_columns.extend(
            [direct_column, coproduced_column, nonstate_column]
        )
    sum_columns = [
        *RUNTIME_COUNT_COLUMNS,
        *RUNTIME_BYTE_COLUMNS,
        *DIRECT_STATE_BYTE_COLUMNS,
        "bal_runtime_bytes_8279",
        "bal_runtime_bytes_direct_state_8279",
        "bal_runtime_bytes_state_bundle_8279",
        "bal_runtime_bytes_coproduced_state_txs_8279",
        "bal_runtime_bytes_nonstate_txs_8279",
        "bal_runtime_bytes_access_related_8279",
        "transaction",
        "runtime_transaction",
        "state_runtime_transaction",
        "state_transaction",
        "direct_state_transaction",
        *component_three_way_columns,
    ]
    block = out.groupby("block_number", as_index=False)[sum_columns].sum()
    block = block.rename(
        columns={
            "bal_runtime_bytes_direct_state_8279": (
                "bal_runtime_bytes_state_8279"
            ),
            "bal_runtime_bytes_access_related_8279": (
                "bal_runtime_bytes_execution_8279"
            ),
            "transaction": "attributed_transactions",
            "runtime_transaction": "runtime_transactions",
            "state_runtime_transaction": "state_runtime_transactions",
            "state_transaction": "state_bundle_transactions_in_attribution",
            "direct_state_transaction": "direct_state_transactions",
        }
    )
    if not (
        block["bal_runtime_bytes_state_8279"]
        + block["bal_runtime_bytes_execution_8279"]
    ).equals(block["bal_runtime_bytes_8279"]):
        raise ValueError("State/execution block attribution does not reconcile")
    if not (
        block["bal_runtime_bytes_state_8279"]
        + block["bal_runtime_bytes_coproduced_state_txs_8279"]
        + block["bal_runtime_bytes_nonstate_txs_8279"]
    ).equals(block["bal_runtime_bytes_8279"]):
        raise ValueError("Three-way block attribution does not reconcile")

    int_columns = [column for column in block.columns if column != "block_number"]
    block[["block_number", *int_columns]] = block[
        ["block_number", *int_columns]
    ].astype("int64")
    return block.sort_values("block_number").reset_index(drop=True)


def attach_normalized_composite_costs(
    attributed: pd.DataFrame,
    gas_inputs: pd.DataFrame,
    *,
    cpsb: int = 1530,
    execution_multiplier: float = 1.537898,
    data_multiplier: float = 1.798834,
    state_multiplier: float = 5.656315,
    data_gas_per_byte: int = 16,
) -> pd.DataFrame:
    """Attach a transparent per-transaction composite-cost proxy.

    Counterfactual metered gas is evaluated at normalized anchor fees
    ``p_i = 1 / multiplier_i``.  This removes arbitrary gas-unit repricing and
    expresses each cost in historical-gas-equivalent units.  The data proxy
    includes calldata and runtime BAL bytes; sampled access lists,
    authorizations, and blob hashes are unavailable at transaction level here.

    Historical state gas can exceed the residual receipt gas for a small set of
    transactions because it is a proxy.  It is capped at receipt gas after
    standard calldata so that the execution/data/state decomposition remains
    non-negative and reconciles exactly.
    """

    if cpsb <= 0 or data_gas_per_byte <= 0:
        raise ValueError("cpsb and data_gas_per_byte must be positive")
    multipliers = {
        "execution": float(execution_multiplier),
        "data": float(data_multiplier),
        "state": float(state_multiplier),
    }
    if any(value <= 0 for value in multipliers.values()):
        raise ValueError("All metering multipliers must be positive")

    required_attributed = {
        "block_number",
        "tx_index",
        "tx_hash",
        "bal_runtime_bytes_8279",
        "new_storage_slots",
        "new_accounts",
        "code_bytes",
        "new_delegation_indicators",
        "historical_state_creation_gas",
    }
    required_gas = {
        "block_number",
        "tx_index",
        "tx_hash",
        "receipt_gas_used",
        "standard_calldata_gas",
        "calldata_bytes",
    }
    missing_attributed = sorted(required_attributed.difference(attributed.columns))
    missing_gas = sorted(required_gas.difference(gas_inputs.columns))
    if missing_attributed:
        raise ValueError(f"Missing attributed runtime columns: {missing_attributed}")
    if missing_gas:
        raise ValueError(f"Missing transaction gas columns: {missing_gas}")

    left = attributed.copy()
    right = gas_inputs.copy()
    for frame in [left, right]:
        frame["tx_hash"] = frame["tx_hash"].map(_normalize_hash)
    out = left.merge(
        right,
        on=["block_number", "tx_index", "tx_hash"],
        how="inner",
        validate="one_to_one",
    )
    if len(out) != len(left) or len(out) != len(right):
        raise ValueError("Runtime and transaction-gas panels do not fully reconcile")

    receipt = pd.to_numeric(out["receipt_gas_used"], errors="raise").astype("int64")
    calldata_current = pd.to_numeric(
        out["standard_calldata_gas"], errors="raise"
    ).astype("int64")
    state_historical = pd.to_numeric(
        out["historical_state_creation_gas"], errors="raise"
    ).astype("int64")
    residual_after_calldata = (receipt - calldata_current).clip(lower=0)
    out["state_reference_gas_capped"] = (
        pd.concat([state_historical, residual_after_calldata], axis=1)
        .min(axis=1)
        .astype("int64")
    )
    out["execution_reference_gas"] = (
        (receipt - calldata_current - out["state_reference_gas_capped"])
        .clip(lower=0)
        .astype("int64")
    )

    out["execution_metered_gas_7999_proxy"] = (
        multipliers["execution"] * out["execution_reference_gas"]
    )
    out["data_metered_gas_7999_proxy"] = data_gas_per_byte * (
        pd.to_numeric(out["calldata_bytes"], errors="raise")
        + out["bal_runtime_bytes_8279"]
    )
    state_bytes = (
        STATE_BYTES_PER_STORAGE_SET * out["new_storage_slots"]
        + STATE_BYTES_PER_NEW_ACCOUNT * out["new_accounts"]
        + out["code_bytes"]
        + STATE_BYTES_PER_DELEGATION_INDICATOR * out["new_delegation_indicators"]
    )
    out["state_metered_gas_7999_proxy"] = int(cpsb) * state_bytes

    for resource in ["execution", "data", "state"]:
        out[f"{resource}_normalized_cost"] = (
            out[f"{resource}_metered_gas_7999_proxy"] / multipliers[resource]
        )
    cost_columns = [
        f"{resource}_normalized_cost" for resource in ["execution", "data", "state"]
    ]
    out["normalized_composite_cost"] = out[cost_columns].sum(axis=1)
    if (out["normalized_composite_cost"] <= 0).any():
        raise ValueError("Composite transaction cost must be positive")
    for resource in ["execution", "data", "state"]:
        out[f"{resource}_composite_cost_share"] = (
            out[f"{resource}_normalized_cost"] / out["normalized_composite_cost"]
        )
    out["composite_cost_proxy_status"] = (
        "normalized anchor fees; calldata plus runtime BAL data; "
        "access-list/auth/blob transaction data omitted"
    )
    return out
