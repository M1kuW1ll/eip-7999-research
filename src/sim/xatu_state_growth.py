"""Helpers for block-level counterfactual EIP-8037 state-gas inputs from Xatu."""

from __future__ import annotations

from collections.abc import Sequence
import re

import pandas as pd

from resources.accounting import (
    STATE_BYTES_PER_DELEGATION_INDICATOR,
    STATE_BYTES_PER_NEW_ACCOUNT,
    STATE_BYTES_PER_STORAGE_SET,
)

_CLICKHOUSE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ZERO_WORD = "0x" + "00" * 32


def _clickhouse_identifier(name: str) -> str:
    """Validate a ClickHouse identifier before using it in a table path."""

    if not _CLICKHOUSE_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe ClickHouse identifier: {name!r}")
    return name


def _empty_state_growth_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "block_number",
            "timestamp",
            "gas_used",
            "gas_limit",
            "base_fee_per_gas",
            "gas_compute",
            "gas_memory",
            "gas_address_access",
            "gas_state_growth",
            "gas_history",
            "gas_bloom_topics",
            "gas_block_size",
            "gas_refund",
            "transaction_state_gas",
            "opcode_state_gas",
            "transaction_minus_block_state_gas",
            "opcode_minus_block_state_gas",
            "transaction_level_state_gas_remainder",
            "transaction_state_gas_matches_block",
            "opcode_state_gas_matches_block",
            "eip8037_new_storage_slots",
            "eip8037_zero_to_nonzero_storage_writes",
            "eip8037_new_contract_accounts",
            "eip8037_new_account_candidates",
            "eip8037_new_accounts",
            "eip8037_code_bytes",
            "eip8037_new_delegation_indicators",
            "eip8037_type4_tx_count",
            "eip8037_state_bytes_equivalent",
            "eip8037_state_gas_used",
            "eip8037_state_gas_source",
            "accounts",
            "storages",
            "contract_codes",
            "account_bytes",
            "account_trienode_bytes",
            "contract_code_bytes",
            "storage_bytes",
            "storage_trienode_bytes",
            "total_state_bytes",
            "accounts_net_delta",
            "storages_net_delta",
            "contract_codes_net_delta",
            "contract_code_bytes_net_delta",
            "storage_bytes_net_delta",
            "total_state_bytes_net_delta",
            "state_size_source",
            "state_gas_used",
            "state_gas_source",
        ]
    )


def _cast_inventory_columns(state_size: pd.DataFrame) -> pd.DataFrame:
    inventory_columns = [
        "accounts",
        "storages",
        "contract_codes",
        "account_bytes",
        "account_trienode_bytes",
        "contract_code_bytes",
        "storage_bytes",
        "storage_trienode_bytes",
    ]
    for column in inventory_columns:
        state_size[column] = pd.to_numeric(
            state_size[column],
            errors="coerce",
        ).astype("int64")
    return state_size


def query_xatu_state_growth_by_block(
    client,
    block_numbers: Sequence[int],
    *,
    network: str = "mainnet",
    cpsb: int = 1530,
    raw_client=None,
) -> pd.DataFrame:
    """Return block-level counterfactual EIP-8037 state-growth data.

    CBT tables are network-scoped databases, so mainnet data is queried from
    ``mainnet.*`` and does not use ``meta_network_name`` filters. Raw Xatu
    diff tables still use ``default.*`` and ``meta_network_name``.

    The replay state gas input is recomputed for the hypothetical EIP-8037 gas
    schedule:

    ``new_storage_slots * 64 * cpsb + new_accounts * 120 * cpsb
    + code_bytes * cpsb + new_delegation_indicators * 23 * cpsb``

    Gross state-creation counters come from raw Xatu diff tables when
    ``raw_client`` is provided. CBT ``gas_state_growth`` columns are retained as
    diagnostics only; they are not used as the EIP-8037 counterfactual gas.

    This is a block-level estimator, not a full client implementation of the
    EIP-8037 reservoir model. In particular, Xatu raw tables currently do not
    expose EIP-7702 authorization-list entries, so this Xatu-only helper leaves
    delegation indicators at zero. Use the RPC authorization-list pull for the
    delegation-indicator sensitivity. New-account candidates are deduplicated by
    address and filtered through ``canonical_execution_address_appearances`` so
    only addresses first seen inside the requested window are counted at their
    earliest state-creation candidate block in that window.
    """

    if cpsb <= 0:
        raise ValueError("cpsb must be positive")

    blocks = sorted({int(block) for block in block_numbers})
    if not blocks:
        return _empty_state_growth_frame()

    database = _clickhouse_identifier(network)
    params = {
        "blocks": blocks,
        "start_block": min(blocks),
        "state_start_block": max(0, min(blocks) - 1),
        "end_block": max(blocks),
    }

    timestamps = client.query_df(
        f"""
        SELECT
            block_number,
            block_date_time AS timestamp
        FROM {database}.int_execution_block_by_date
        WHERE block_number IN {{blocks:Array(UInt64)}}
        ORDER BY block_number
        """,
        parameters=params,
    )

    if timestamps.empty:
        headers = timestamps.assign(
            gas_used=pd.NA,
            gas_limit=pd.NA,
            base_fee_per_gas=pd.NA,
        )
    else:
        start_time = str(timestamps["timestamp"].min())
        end_time = str(timestamps["timestamp"].max())
        header_params = params | {
            "start_time": start_time,
            "end_time": end_time,
        }
        headers = client.query_df(
            f"""
            SELECT
                execution_payload_block_number AS block_number,
                slot_start_date_time AS timestamp,
                execution_payload_gas_used AS gas_used,
                execution_payload_gas_limit AS gas_limit,
                execution_payload_base_fee_per_gas AS base_fee_per_gas
            FROM {database}.int_block_canonical
            WHERE slot_start_date_time
                BETWEEN parseDateTime64BestEffort({{start_time:String}})
                AND parseDateTime64BestEffort({{end_time:String}})
              AND execution_payload_block_number IN {{blocks:Array(UInt64)}}
            ORDER BY block_number
            """,
            parameters=header_params,
        )
        if headers.empty:
            headers = timestamps.assign(
                gas_used=pd.NA,
                gas_limit=pd.NA,
                base_fee_per_gas=pd.NA,
            )

    resource_gas = client.query_df(
        f"""
        SELECT
            block_number,
            gas_compute,
            gas_memory,
            gas_address_access,
            gas_state_growth,
            gas_history,
            gas_bloom_topics,
            gas_block_size,
            gas_refund
        FROM {database}.int_block_resource_gas
        WHERE block_number IN {{blocks:Array(UInt64)}}
        ORDER BY block_number
        """,
        parameters=params,
    )

    transaction_state_gas = client.query_df(
        f"""
        SELECT
            block_number,
            toInt64(sum(gas_state_growth)) AS transaction_state_gas
        FROM {database}.int_transaction_resource_gas
        WHERE block_number IN {{blocks:Array(UInt64)}}
        GROUP BY block_number
        ORDER BY block_number
        """,
        parameters=params,
    )

    opcode_state_gas = client.query_df(
        f"""
        SELECT
            block_number,
            toInt64(sum(gas_state_growth)) AS opcode_state_gas
        FROM {database}.int_transaction_call_frame_opcode_resource_gas
        WHERE block_number IN {{blocks:Array(UInt64)}}
        GROUP BY block_number
        ORDER BY block_number
        """,
        parameters=params,
    )

    if raw_client is not None:
        raw_params = params | {
            "network": network,
            "zero_word": ZERO_WORD,
        }
        storage_creations = raw_client.query_df(
            """
            SELECT
                block_number,
                uniqExact(tuple(lower(address), lower(slot))) AS eip8037_new_storage_slots,
                count() AS eip8037_zero_to_nonzero_storage_writes
            FROM default.canonical_execution_storage_diffs FINAL
            WHERE meta_network_name = {network:String}
              AND block_number IN {blocks:Array(UInt64)}
              AND lower(from_value) = {zero_word:String}
              AND lower(to_value) != {zero_word:String}
            GROUP BY block_number
            ORDER BY block_number
            """,
            parameters=raw_params,
        )

        code_creations = raw_client.query_df(
            """
            SELECT
                block_number,
                uniqExact(lower(contract_address)) AS eip8037_new_contract_accounts,
                sum(n_code_bytes) AS eip8037_code_bytes
            FROM default.canonical_execution_contracts FINAL
            WHERE meta_network_name = {network:String}
              AND block_number IN {blocks:Array(UInt64)}
            GROUP BY block_number
            ORDER BY block_number
            """,
            parameters=raw_params,
        )

        account_creations = raw_client.query_df(
            """
            WITH
                candidates AS
                (
                    SELECT
                        address,
                        min(candidate_block) AS candidate_block
                    FROM
                    (
                        SELECT
                            lower(contract_address) AS address,
                            min(block_number) AS candidate_block
                        FROM default.canonical_execution_contracts FINAL
                        WHERE meta_network_name = {network:String}
                          AND block_number IN {blocks:Array(UInt64)}
                        GROUP BY address

                        UNION ALL

                        SELECT
                            lower(address) AS address,
                            min(block_number) AS candidate_block
                        FROM default.canonical_execution_balance_diffs FINAL
                        WHERE meta_network_name = {network:String}
                          AND block_number IN {blocks:Array(UInt64)}
                          AND from_value = 0
                          AND to_value > 0
                        GROUP BY address

                        UNION ALL

                        SELECT
                            lower(address) AS address,
                            min(block_number) AS candidate_block
                        FROM default.canonical_execution_nonce_diffs FINAL
                        WHERE meta_network_name = {network:String}
                          AND block_number IN {blocks:Array(UInt64)}
                          AND from_value = 0
                          AND to_value > 0
                        GROUP BY address
                    ) AS raw_candidates
                    GROUP BY address
                ),
                first_appearances AS
                (
                    SELECT
                        lower(address) AS address,
                        min(block_number) AS first_block
                    FROM default.canonical_execution_address_appearances FINAL
                    WHERE meta_network_name = {network:String}
                      AND lower(address) GLOBAL IN (
                          SELECT address FROM candidates
                      )
                    GROUP BY address
                )
            SELECT
                candidate_block AS block_number,
                count() AS eip8037_new_accounts
            FROM candidates
            INNER JOIN first_appearances USING address
            WHERE first_appearances.first_block BETWEEN {start_block:UInt64}
                AND {end_block:UInt64}
            GROUP BY candidate_block
            ORDER BY candidate_block
            """,
            parameters=raw_params,
        )

        account_creation_candidates = raw_client.query_df(
            """
            SELECT
                block_number,
                uniqExact(address) AS eip8037_new_account_candidates
            FROM
            (
                SELECT
                    block_number,
                    lower(contract_address) AS address
                FROM default.canonical_execution_contracts FINAL
                WHERE meta_network_name = {network:String}
                  AND block_number IN {blocks:Array(UInt64)}

                UNION DISTINCT

                SELECT
                    block_number,
                    lower(address) AS address
                FROM default.canonical_execution_balance_diffs FINAL
                WHERE meta_network_name = {network:String}
                  AND block_number IN {blocks:Array(UInt64)}
                  AND from_value = 0
                  AND to_value > 0

                UNION DISTINCT

                SELECT
                    block_number,
                    lower(address) AS address
                FROM default.canonical_execution_nonce_diffs FINAL
                WHERE meta_network_name = {network:String}
                  AND block_number IN {blocks:Array(UInt64)}
                  AND from_value = 0
                  AND to_value > 0
            )
            GROUP BY block_number
            ORDER BY block_number
            """,
            parameters=raw_params,
        )

        type4_transactions = raw_client.query_df(
            """
            SELECT
                block_number,
                count() AS eip8037_type4_tx_count
            FROM default.execution_transaction FINAL
            WHERE meta_network_name = {network:String}
              AND block_number IN {blocks:Array(UInt64)}
              AND type = 4
            GROUP BY block_number
            ORDER BY block_number
            """,
            parameters=raw_params,
        )
    else:
        storage_creations = pd.DataFrame()
        code_creations = pd.DataFrame()
        account_creations = pd.DataFrame()
        account_creation_candidates = pd.DataFrame()
        type4_transactions = pd.DataFrame()

    state_size = client.query_df(
        f"""
        SELECT
            block_number,
            accounts,
            storages,
            contract_codes,
            account_bytes,
            account_trienode_bytes,
            contract_code_bytes,
            storage_bytes,
            storage_trienode_bytes
        FROM {database}.int_execution_state_size_by_block
        WHERE block_number BETWEEN {{state_start_block:UInt64}} AND {{end_block:UInt64}}
        ORDER BY block_number
        """,
        parameters=params,
    )

    if not state_size.empty:
        state_size = _cast_inventory_columns(state_size)
        state_size["total_state_bytes"] = (
            state_size[
                [
                    "account_bytes",
                    "account_trienode_bytes",
                    "contract_code_bytes",
                    "storage_bytes",
                    "storage_trienode_bytes",
                ]
            ]
            .fillna(0)
            .sum(axis=1)
            .astype("int64")
        )
        for column in [
            "accounts",
            "storages",
            "contract_codes",
            "contract_code_bytes",
            "storage_bytes",
            "total_state_bytes",
        ]:
            state_size[f"{column}_net_delta"] = state_size[column].diff()
        state_size = state_size[state_size["block_number"].isin(blocks)].copy()
        state_size["state_size_source"] = (
            f"{database}.int_execution_state_size_by_block"
        )

    out = pd.DataFrame({"block_number": blocks})
    for frame in [
        headers,
        resource_gas,
        transaction_state_gas,
        opcode_state_gas,
        storage_creations,
        code_creations,
        account_creation_candidates,
        account_creations,
        type4_transactions,
        state_size,
    ]:
        if not frame.empty and "block_number" in frame.columns:
            out = out.merge(frame, on="block_number", how="left")

    nullable_columns = [
        "timestamp",
        "gas_used",
        "gas_limit",
        "base_fee_per_gas",
        "gas_compute",
        "gas_memory",
        "gas_address_access",
        "gas_state_growth",
        "gas_history",
        "gas_bloom_topics",
        "gas_block_size",
        "gas_refund",
        "transaction_state_gas",
        "opcode_state_gas",
        "eip8037_new_storage_slots",
        "eip8037_zero_to_nonzero_storage_writes",
        "eip8037_new_contract_accounts",
        "eip8037_new_account_candidates",
        "eip8037_new_accounts",
        "eip8037_code_bytes",
        "eip8037_type4_tx_count",
        "accounts",
        "storages",
        "contract_codes",
        "account_bytes",
        "account_trienode_bytes",
        "contract_code_bytes",
        "storage_bytes",
        "storage_trienode_bytes",
        "total_state_bytes",
        "accounts_net_delta",
        "storages_net_delta",
        "contract_codes_net_delta",
        "contract_code_bytes_net_delta",
        "storage_bytes_net_delta",
        "total_state_bytes_net_delta",
        "state_size_source",
    ]
    for column in nullable_columns:
        if column not in out.columns:
            out[column] = pd.NA

    eip8037_counter_columns = [
        "eip8037_new_storage_slots",
        "eip8037_zero_to_nonzero_storage_writes",
        "eip8037_new_contract_accounts",
        "eip8037_new_account_candidates",
        "eip8037_new_accounts",
        "eip8037_code_bytes",
        "eip8037_type4_tx_count",
    ]
    for column in eip8037_counter_columns:
        out[column] = (
            pd.to_numeric(out[column], errors="coerce")
            .fillna(0)
            .astype("int64")
        )

    # Raw Xatu currently exposes type-4 transactions but not authorization-list
    # entries. The RPC authorization-list notebook adds an upper-bound
    # delegation-indicator sensitivity separately.
    out["eip8037_new_delegation_indicators"] = 0
    out["eip8037_state_bytes_equivalent"] = (
        out["eip8037_new_storage_slots"].astype("int64")
        * STATE_BYTES_PER_STORAGE_SET
        + out["eip8037_new_accounts"].astype("int64")
        * STATE_BYTES_PER_NEW_ACCOUNT
        + out["eip8037_code_bytes"].astype("int64")
        + out["eip8037_new_delegation_indicators"].astype("int64")
        * STATE_BYTES_PER_DELEGATION_INDICATOR
    )
    out["eip8037_state_gas_used"] = (
        out["eip8037_state_bytes_equivalent"].astype("int64") * int(cpsb)
    )
    out["eip8037_state_gas_source"] = (
        "xatu_raw_diffs_counterfactual_eip8037"
        if raw_client is not None
        else "unavailable_without_raw_xatu_diffs"
    )

    out["state_gas_used"] = out["eip8037_state_gas_used"]
    out["state_gas_source"] = out["eip8037_state_gas_source"]

    state_gas_columns = [
        "gas_state_growth",
        "state_gas_used",
        "eip8037_state_gas_used",
        "transaction_state_gas",
        "opcode_state_gas",
    ]
    for column in state_gas_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")

    out["transaction_minus_block_state_gas"] = (
        out["transaction_state_gas"] - out["gas_state_growth"]
    ).astype("Int64")
    out["opcode_minus_block_state_gas"] = (
        out["opcode_state_gas"] - out["gas_state_growth"]
    ).astype("Int64")
    out["transaction_level_state_gas_remainder"] = (
        out["transaction_state_gas"] - out["opcode_state_gas"]
    ).astype("Int64")
    out["transaction_state_gas_matches_block"] = (
        out["transaction_state_gas"].notna()
        & out["gas_state_growth"].notna()
        & (out["transaction_state_gas"] == out["gas_state_growth"])
    )
    out["opcode_state_gas_matches_block"] = (
        out["opcode_state_gas"].notna()
        & out["gas_state_growth"].notna()
        & (out["opcode_state_gas"] == out["gas_state_growth"])
    )

    return out.sort_values("block_number").reset_index(drop=True)
