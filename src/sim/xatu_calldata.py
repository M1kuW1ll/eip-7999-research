"""Helpers for block-level calldata bytes from Xatu."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def query_xatu_calldata_by_block(
    client,
    block_numbers: Sequence[int],
    network: str = "mainnet",
) -> pd.DataFrame:
    """Return Xatu calldata bytes plus zero/nonzero validation columns.

    `calldata_bytes` is sourced from the canonical beacon payload transaction
    table. `calldata_zero_bytes`, `calldata_nonzero_bytes`, and
    `calldata_gas_7999` are sourced from `execution_transaction` only after
    checking that its raw byte total and transaction count match the beacon
    payload.

    `canonical_execution_transaction` is included only as a row-count diagnostic
    because it can be sparse for some historical blocks.
    """

    blocks = sorted({int(block) for block in block_numbers})
    if not blocks:
        return pd.DataFrame(
            columns=[
                "block_number",
                "slot",
                "n_txs_from_payload",
                "n_txs",
                "calldata_bytes",
                "execution_tx_rows",
                "execution_calldata_bytes",
                "calldata_zero_bytes",
                "calldata_nonzero_bytes",
                "calldata_gas_7999",
                "calldata_gas_source",
                "execution_rows_n_input_positive",
                "execution_matches_beacon",
                "canonical_execution_tx_rows",
                "canonical_execution_matches_beacon",
            ]
        )

    beacon = client.query_df(
        """
        SELECT
            slot,
            execution_payload_block_number AS block_number,
            execution_payload_transactions_count AS n_txs_from_payload
        FROM default.canonical_beacon_block FINAL
        WHERE meta_network_name = {network:String}
          AND execution_payload_block_number IN {blocks:Array(UInt64)}
        ORDER BY block_number
        """,
        parameters={"network": network, "blocks": blocks},
    )
    if beacon.empty:
        raise RuntimeError("No canonical beacon block rows found for requested blocks")

    slots = beacon["slot"].astype(int).tolist()
    calldata = client.query_df(
        """
        SELECT
            slot,
            count() AS n_txs,
            sum(call_data_size) AS calldata_bytes
        FROM default.canonical_beacon_block_execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND slot IN {slots:Array(UInt64)}
        GROUP BY slot
        ORDER BY slot
        """,
        parameters={"network": network, "slots": slots},
    )

    out = beacon.merge(calldata, on="slot", how="left")
    fill_cols = ["n_txs", "calldata_bytes"]
    out[fill_cols] = out[fill_cols].fillna(0).astype("int64")
    out["n_txs_from_payload"] = out["n_txs_from_payload"].astype("int64")

    mismatch = out[out["n_txs"] != out["n_txs_from_payload"]]
    if not mismatch.empty:
        raise RuntimeError(
            "Xatu calldata tx count mismatch for blocks: "
            + ", ".join(str(int(block)) for block in mismatch["block_number"])
        )

    canonical_blocks = client.query_df(
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
    if canonical_blocks.empty:
        raise RuntimeError("No canonical execution block rows found for requested blocks")

    block_hashes = [
        value.decode() if isinstance(value, bytes) else str(value)
        for value in canonical_blocks["block_hash"]
    ]

    execution = client.query_df(
        """
        SELECT
            block_number,
            count() AS execution_tx_rows,
            countIf(n_input_bytes > 0) AS execution_rows_n_input_positive,
            sum(n_input_bytes) AS execution_calldata_bytes,
            sum(n_input_zero_bytes) AS execution_zero_bytes,
            sum(n_input_nonzero_bytes) AS execution_nonzero_bytes,
            sum(4 * n_input_zero_bytes + 16 * n_input_nonzero_bytes) AS execution_calldata_gas_7999
        FROM default.execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_hash IN {block_hashes:Array(FixedString(66))}
        GROUP BY block_number
        ORDER BY block_number
        """,
        parameters={"network": network, "block_hashes": block_hashes},
    )

    canonical_execution = client.query_df(
        """
        SELECT
            block_number,
            count() AS canonical_execution_tx_rows
        FROM default.canonical_execution_transaction FINAL
        WHERE meta_network_name = {network:String}
          AND block_number IN {blocks:Array(UInt64)}
        GROUP BY block_number
        ORDER BY block_number
        """,
        parameters={"network": network, "blocks": blocks},
    )

    out = (
        out.rename(columns={"calldata_bytes": "beacon_calldata_bytes"})
        .merge(execution, on="block_number", how="left")
        .merge(canonical_execution, on="block_number", how="left")
    )

    numeric_cols = [
        "execution_tx_rows",
        "execution_rows_n_input_positive",
        "execution_calldata_bytes",
        "execution_zero_bytes",
        "execution_nonzero_bytes",
        "execution_calldata_gas_7999",
        "canonical_execution_tx_rows",
    ]
    out[numeric_cols] = out[numeric_cols].fillna(0).astype("int64")
    out["calldata_bytes"] = out["beacon_calldata_bytes"]
    out["execution_matches_beacon"] = (
        (out["execution_tx_rows"] == out["n_txs_from_payload"])
        & (out["execution_calldata_bytes"] == out["beacon_calldata_bytes"])
    )
    out["canonical_execution_matches_beacon"] = (
        out["canonical_execution_tx_rows"] == out["n_txs_from_payload"]
    )

    out["calldata_zero_bytes"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["calldata_nonzero_bytes"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["calldata_gas_7999"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out["calldata_gas_source"] = "unavailable"

    execution_mask = out["execution_matches_beacon"]
    out.loc[execution_mask, "calldata_zero_bytes"] = out.loc[
        execution_mask, "execution_zero_bytes"
    ]
    out.loc[execution_mask, "calldata_nonzero_bytes"] = out.loc[
        execution_mask, "execution_nonzero_bytes"
    ]
    out.loc[execution_mask, "calldata_gas_7999"] = out.loc[
        execution_mask, "execution_calldata_gas_7999"
    ]
    out.loc[execution_mask, "calldata_gas_source"] = "execution_transaction"

    return out[
        [
            "block_number",
            "slot",
            "n_txs_from_payload",
            "n_txs",
            "calldata_bytes",
            "execution_tx_rows",
            "execution_calldata_bytes",
            "calldata_zero_bytes",
            "calldata_nonzero_bytes",
            "calldata_gas_7999",
            "calldata_gas_source",
            "execution_rows_n_input_positive",
            "execution_matches_beacon",
            "canonical_execution_tx_rows",
            "canonical_execution_matches_beacon",
        ]
    ].sort_values("block_number").reset_index(drop=True)
