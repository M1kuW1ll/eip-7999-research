"""Xatu pulls for transaction-level Glamsterdam regular-gas recalculation."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from glamsterdam.calldata_floor import historical_state_creation_gas

ZERO_WORD = "0x" + "00" * 32


def _blocks(block_numbers: Sequence[int]) -> list[int]:
    return sorted({int(block) for block in block_numbers})


def _normalize_fixed_string(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _empty_tx_inputs_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "block_number",
            "tx_index",
            "tx_hash",
            "transaction_type",
            "to_address",
            "receipt_gas_used",
            "tx_gas_limit",
            "calldata_zero_bytes",
            "calldata_nonzero_bytes",
            "calldata_bytes",
            "standard_calldata_gas",
        ]
    )


def query_xatu_transaction_gas_inputs(
    client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Pull transaction receipt gas and calldata byte counts.

    Raw ``execution_transaction`` is the source of transaction membership and
    calldata because it has the canonical block hash and complete transaction
    positions. ``canonical_execution_transaction`` is joined only for receipt
    ``gas_used``. Some historical ranges have sparse canonical transaction rows,
    so missing receipt coverage raises instead of silently producing a partial
    replay.
    """

    blocks = _blocks(block_numbers)
    if not blocks:
        return _empty_tx_inputs_frame()

    block_hashes = client.query_df(
        """
        SELECT
            block_number,
            block_hash
        FROM default.canonical_execution_block FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        ORDER BY block_number
        """,
        parameters={"network": network, "blocks": blocks},
    )
    if block_hashes.empty:
        return _empty_tx_inputs_frame()
    hashes = [_normalize_fixed_string(value) for value in block_hashes["block_hash"]]

    expected_counts = client.query_df(
        """
        SELECT
            execution_payload_block_number AS block_number,
            execution_payload_transactions_count AS expected_tx_count
        FROM default.canonical_beacon_block FINAL
        WHERE meta_network_name = {network:String}
          AND execution_payload_block_number IN {blocks:Array(UInt64)}
        ORDER BY block_number
        """,
        parameters={"network": network, "blocks": blocks},
    )

    raw = client.query_df(
        """
        SELECT
            block_number,
            position AS tx_index,
            hash AS tx_hash,
            type AS transaction_type,
            ifNull(to, '') AS to_address,
            gas AS tx_gas_limit,
            n_input_zero_bytes AS calldata_zero_bytes,
            n_input_nonzero_bytes AS calldata_nonzero_bytes,
            n_input_bytes AS calldata_bytes,
            4 * n_input_zero_bytes + 16 * n_input_nonzero_bytes AS standard_calldata_gas
        FROM default.execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_hash IN {hashes:Array(FixedString(66))}
        ORDER BY block_number, position
        """,
        parameters={"network": network, "hashes": hashes},
    )
    if raw.empty:
        raw_count = pd.DataFrame(columns=["block_number", "raw_tx_count"])
    else:
        raw_count = (
            raw.groupby("block_number", as_index=False)
            .size()
            .rename(columns={"size": "raw_tx_count"})
        )
    if not expected_counts.empty:
        coverage = expected_counts.merge(raw_count, on="block_number", how="left")
        coverage["raw_tx_count"] = pd.to_numeric(
            coverage["raw_tx_count"],
            errors="coerce",
        ).fillna(0).astype("int64")
        coverage["expected_tx_count"] = pd.to_numeric(
            coverage["expected_tx_count"],
            errors="coerce",
        ).astype("int64")
        missing_raw = coverage[
            coverage["raw_tx_count"] != coverage["expected_tx_count"]
        ]
        if not missing_raw.empty:
            first_missing = {
                int(row.block_number): {
                    "expected_tx_count": int(row.expected_tx_count),
                    "raw_tx_count": int(row.raw_tx_count),
                }
                for row in missing_raw.head(10).itertuples(index=False)
            }
            raise RuntimeError(
                "execution_transaction does not contain all beacon payload "
                "transactions for this range. Use RPC full blocks/receipts for "
                f"these blocks. First mismatches: {first_missing}"
            )
    elif raw.empty:
        return _empty_tx_inputs_frame()

    raw["to_address"] = raw["to_address"].map(
        lambda value: _normalize_fixed_string(value).lower() if value else ""
    )
    receipts = client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            gas_used AS receipt_gas_used
        FROM default.canonical_execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        ORDER BY block_number, transaction_index
        """,
        parameters={"network": network, "blocks": blocks},
    )

    raw["tx_hash"] = raw["tx_hash"].map(_normalize_fixed_string)
    if not receipts.empty:
        receipts["tx_hash"] = receipts["tx_hash"].map(_normalize_fixed_string)

    out = raw.merge(
        receipts,
        on=["block_number", "tx_index", "tx_hash"],
        how="left",
        validate="one_to_one",
    )
    missing_receipts = out["receipt_gas_used"].isna()
    if missing_receipts.any():
        missing_by_block = (
            out.loc[missing_receipts]
            .groupby("block_number")
            .size()
            .sort_index()
            .head(10)
            .to_dict()
        )
        raise RuntimeError(
            "canonical_execution_transaction is missing receipt gas for "
            f"{int(missing_receipts.sum())} raw transactions. "
            "Use RPC receipts for these blocks or choose a range with complete "
            f"canonical coverage. First missing blocks: {missing_by_block}"
        )

    int_columns = [
        "block_number",
        "tx_index",
        "transaction_type",
        "receipt_gas_used",
        "tx_gas_limit",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "calldata_bytes",
        "standard_calldata_gas",
    ]
    out[int_columns] = out[int_columns].astype("int64")
    return out[_empty_tx_inputs_frame().columns].reset_index(drop=True)


def _empty_tx_state_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "block_number",
            "tx_index",
            "tx_hash",
            "new_storage_slots",
            "new_accounts",
            "code_bytes",
            "new_delegation_indicators",
            "historical_state_creation_gas",
        ]
    )


def query_xatu_tx_state_creation(
    raw_client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Estimate EIP-8037-repriced historical state creation by transaction.

    This mirrors the block-level Xatu estimator but keeps transaction identity.
    EIP-7702 delegation indicators are not observable in Xatu raw transaction
    rows and should be merged from the RPC authorization/prestate calibration
    path when available.
    """

    blocks = _blocks(block_numbers)
    if not blocks:
        return _empty_tx_state_frame()

    params = {
        "network": network,
        "blocks": blocks,
        "start_block": min(blocks),
        "end_block": max(blocks),
        "zero_word": ZERO_WORD,
    }

    storage = raw_client.query_df(
        """
        SELECT
            block_number,
            transaction_index AS tx_index,
            transaction_hash AS tx_hash,
            uniqExact(tuple(lower(address), lower(slot))) AS new_storage_slots
        FROM default.canonical_execution_storage_diffs FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
          AND lower(from_value) = {zero_word:String}
          AND lower(to_value) != {zero_word:String}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    code = raw_client.query_df(
        """
        SELECT
            c.block_number AS block_number,
            t.transaction_index AS tx_index,
            c.transaction_hash AS tx_hash,
            uniqExact(lower(c.contract_address)) AS new_contract_accounts,
            sum(c.n_code_bytes) AS code_bytes
        FROM default.canonical_execution_contracts AS c FINAL
        GLOBAL INNER JOIN
        (
            SELECT
                block_number,
                transaction_index,
                transaction_hash
            FROM default.canonical_execution_transaction FINAL
            WHERE meta_network_name = {network:String}
              AND block_number IN {blocks:Array(UInt64)}
        ) AS t
            ON c.block_number = t.block_number
           AND c.transaction_hash = t.transaction_hash
        WHERE c.meta_network_name = {network:String}
          AND c.block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    accounts = raw_client.query_df(
        """
        WITH
            raw_candidates AS
            (
                SELECT
                    lower(c.contract_address) AS address,
                    c.block_number AS candidate_block,
                    t.transaction_index AS candidate_tx_index,
                    c.transaction_hash AS candidate_tx_hash,
                    c.internal_index AS candidate_internal_index
                FROM default.canonical_execution_contracts AS c FINAL
                GLOBAL INNER JOIN
                (
                    SELECT
                        block_number,
                        transaction_index,
                        transaction_hash
                    FROM default.canonical_execution_transaction FINAL
                    WHERE meta_network_name = {network:String}
                      AND block_number IN {blocks:Array(UInt64)}
                ) AS t
                    ON c.block_number = t.block_number
                   AND c.transaction_hash = t.transaction_hash
                WHERE c.meta_network_name = {network:String}
                  AND c.block_number IN {blocks:Array(UInt64)}

                UNION ALL

                SELECT
                    lower(address) AS address,
                    block_number AS candidate_block,
                    transaction_index AS candidate_tx_index,
                    transaction_hash AS candidate_tx_hash,
                    internal_index AS candidate_internal_index
                FROM default.canonical_execution_balance_diffs FINAL
                WHERE meta_network_name = {network:String}
                  AND block_number IN {blocks:Array(UInt64)}
                  AND from_value = 0
                  AND to_value > 0

                UNION ALL

                SELECT
                    lower(address) AS address,
                    block_number AS candidate_block,
                    transaction_index AS candidate_tx_index,
                    transaction_hash AS candidate_tx_hash,
                    internal_index AS candidate_internal_index
                FROM default.canonical_execution_nonce_diffs FINAL
                WHERE meta_network_name = {network:String}
                  AND block_number IN {blocks:Array(UInt64)}
                  AND from_value = 0
                  AND to_value > 0
            ),
            candidates AS
            (
                SELECT
                    address,
                    candidate_block,
                    candidate_tx_index,
                    candidate_tx_hash
                FROM raw_candidates
                ORDER BY
                    address,
                    candidate_block,
                    candidate_tx_index,
                    candidate_internal_index
                LIMIT 1 BY address
            ),
            first_appearances AS
            (
                SELECT
                    lower(address) AS address,
                    min(block_number) AS first_block
                FROM default.canonical_execution_address_appearances FINAL
                WHERE meta_network_name = {network:String}
                  AND lower(address) GLOBAL IN (SELECT address FROM candidates)
                GROUP BY address
            )
        SELECT
            candidate_block AS block_number,
            candidate_tx_index AS tx_index,
            candidate_tx_hash AS tx_hash,
            count() AS new_accounts
        FROM candidates
        INNER JOIN first_appearances USING address
        WHERE first_appearances.first_block BETWEEN {start_block:UInt64}
            AND {end_block:UInt64}
        GROUP BY block_number, tx_index, tx_hash
        """,
        parameters=params,
    )

    frames = []
    for frame in [storage, code, accounts]:
        if frame.empty:
            continue
        frame = frame.copy()
        frame["tx_hash"] = frame["tx_hash"].map(
            lambda value: value.decode() if isinstance(value, bytes) else str(value)
        )
        frames.append(frame)

    if not frames:
        return _empty_tx_state_frame()

    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(
            frame,
            on=["block_number", "tx_index", "tx_hash"],
            how="outer",
        )

    for column in [
        "new_storage_slots",
        "new_contract_accounts",
        "new_accounts",
        "code_bytes",
    ]:
        if column not in out:
            out[column] = 0
        out[column] = out[column].fillna(0).astype("int64")

    out["new_delegation_indicators"] = 0
    out["historical_state_creation_gas"] = out.apply(
        lambda row: historical_state_creation_gas(
            new_storage_slots=int(row["new_storage_slots"]),
            new_accounts=int(row["new_accounts"]),
            code_bytes=int(row["code_bytes"]),
            new_delegation_indicators=0,
        ),
        axis=1,
    ).astype("int64")

    out[["block_number", "tx_index"]] = out[["block_number", "tx_index"]].astype(
        "int64"
    )
    return (
        out[
            [
                "block_number",
                "tx_index",
                "tx_hash",
                "new_storage_slots",
                "new_accounts",
                "code_bytes",
                "new_delegation_indicators",
                "historical_state_creation_gas",
            ]
        ]
        .sort_values(["block_number", "tx_index"])
        .reset_index(drop=True)
    )
