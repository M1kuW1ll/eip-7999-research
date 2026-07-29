"""Build compact transaction panels for EIP-8279 BAL surcharge analysis.

The helpers in this module keep three accounting objects separate:

* historical receipt gas, decomposed using the observed EIP-7623 floor;
* counterfactual execution and EIP-8037 state gas; and
* EIP-7999 static-data bytes.

Xatu supplies exact calldata and blob-versioned-hash counts. Access-list and
authorization counts require a transaction-body supplement; until one is
provided, the complete static-data field is deliberately left missing rather
than treating unavailable content as zero.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from glamsterdam.calldata_floor import TX_BASE_GAS
from sim.xatu_bal_8279 import (
    RUNTIME_COUNT_COLUMNS,
    compute_eip8279_runtime_bytes,
)


DATA_GAS_PER_BYTE = 16
EIP7623_TOTAL_COST_FLOOR_PER_TOKEN = 10
STATE_BYTES_PER_STORAGE_SLOT = 64
STATE_BYTES_PER_ACCOUNT = 120
STATE_BYTES_PER_DELEGATION = 23
ACCESS_LIST_ADDRESS_BYTES = 20
ACCESS_LIST_STORAGE_KEY_BYTES = 32
AUTHORIZATION_TUPLE_BYTES = 108
AUTHORIZATION_BAL_STATIC_BYTES = 51
EIP8037_CPSB = 1530

KEY_COLUMNS = ["block_number", "tx_index", "tx_hash"]
BAL_COMPONENT_COLUMNS = [
    "bal_runtime_bytes_direct_state_8279",
    "bal_runtime_bytes_coproduced_state_txs_8279",
    "bal_runtime_bytes_nonstate_txs_8279",
]


def _normalize_hash(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _require_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise ValueError(f"Missing {label} columns: {missing}")


def align_runtime_meter_to_transactions(
    runtime_meter: pd.DataFrame,
    gas_inputs: pd.DataFrame,
) -> pd.DataFrame:
    """Align runtime events to canonical transaction membership.

    Transactions with no observed EIP-8279 event—including plain transfers—
    receive zero runtime counts. Runtime rows that cannot be matched to the
    canonical transaction table are rejected.
    """

    _require_columns(
        runtime_meter,
        {*KEY_COLUMNS, *RUNTIME_COUNT_COLUMNS},
        "runtime-meter",
    )
    _require_columns(gas_inputs, set(KEY_COLUMNS), "transaction-gas")
    runtime = runtime_meter[[*KEY_COLUMNS, *RUNTIME_COUNT_COLUMNS]].copy()
    membership = gas_inputs[KEY_COLUMNS].copy()
    for table in [runtime, membership]:
        table["tx_hash"] = table["tx_hash"].map(_normalize_hash)
        if table.duplicated(KEY_COLUMNS).any():
            raise ValueError("Transaction inputs contain duplicate join keys")
    unmatched = runtime.merge(
        membership,
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not unmatched["_merge"].eq("both").all():
        count = int((~unmatched["_merge"].eq("both")).sum())
        raise ValueError(f"Runtime meter has {count} transactions absent from gas inputs")
    aligned = membership.merge(
        runtime,
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    aligned[RUNTIME_COUNT_COLUMNS] = aligned[RUNTIME_COUNT_COLUMNS].fillna(0)
    return compute_eip8279_runtime_bytes(aligned)


def attach_eip7623_receipt_decomposition(frame: pd.DataFrame) -> pd.DataFrame:
    """Decompose historical receipt gas into data, state, and execution.

    The post-Pectra data proxy follows the project's daily accounting panel.
    A transaction is treated as observed EIP-7623-floor-bound when it has
    calldata and its receipt body is at or below the 10-gas-per-token floor.
    Otherwise its data component is the standard 4/16 calldata charge.

    The state-creation proxy is capped by the receipt remainder. This preserves
    an exact, non-negative decomposition even when the proxy exceeds the gas
    that can be assigned to state in an individual transaction.
    """

    required = {
        "receipt_gas_used",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "standard_calldata_gas",
        "historical_state_creation_gas",
    }
    _require_columns(frame, required, "receipt-decomposition")
    out = frame.copy()
    numeric = sorted(required)
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise").fillna(0)
    if (out[numeric] < 0).any().any():
        raise ValueError("Receipt-decomposition inputs cannot be negative")
    if out["receipt_gas_used"].lt(TX_BASE_GAS).any():
        raise ValueError("Historical receipt gas cannot be below transaction base gas")

    out["calldata_tokens"] = (
        out["calldata_zero_bytes"] + 4 * out["calldata_nonzero_bytes"]
    ).astype("int64")
    out["receipt_body_gas"] = (
        out["receipt_gas_used"] - TX_BASE_GAS
    ).astype("int64")
    out["current_7623_floor_gas"] = (
        EIP7623_TOTAL_COST_FLOOR_PER_TOKEN * out["calldata_tokens"]
    ).astype("int64")
    out["current_7623_floor_bound_proxy"] = (
        out["calldata_tokens"].gt(0)
        & out["receipt_body_gas"].le(out["current_7623_floor_gas"])
    )
    out["current_data_gas_7623_proxy"] = np.where(
        out["current_7623_floor_bound_proxy"],
        out["current_7623_floor_gas"],
        out["standard_calldata_gas"],
    ).astype("int64")

    receipt_remainder = (
        out["receipt_gas_used"] - out["current_data_gas_7623_proxy"]
    )
    if (receipt_remainder < 0).any():
        raise ValueError("Current data-gas proxy exceeds historical receipt gas")
    out["state_reference_gas_capped"] = pd.concat(
        [out["historical_state_creation_gas"], receipt_remainder], axis=1
    ).min(axis=1).astype("int64")
    out["execution_reference_gas"] = (
        receipt_remainder - out["state_reference_gas_capped"]
    ).astype("int64")

    reconstructed = (
        out["current_data_gas_7623_proxy"]
        + out["state_reference_gas_capped"]
        + out["execution_reference_gas"]
    )
    if not reconstructed.equals(out["receipt_gas_used"].astype("int64")):
        raise ValueError("Historical transaction gas does not reconcile")
    return out


def attach_eip8037_state_metering(
    frame: pd.DataFrame,
    *,
    cpsb: int = EIP8037_CPSB,
) -> pd.DataFrame:
    """Attach EIP-8037 state bytes and state gas to transactions."""

    if int(cpsb) <= 0:
        raise ValueError("cpsb must be positive")
    required = {
        "new_storage_slots",
        "new_accounts",
        "code_bytes",
        "new_delegation_indicators",
    }
    _require_columns(frame, required, "EIP-8037 state-metering")
    out = frame.copy()
    numeric = sorted(required)
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise").fillna(0)
    if (out[numeric] < 0).any().any():
        raise ValueError("EIP-8037 state-metering inputs cannot be negative")
    out["state_bytes_8037"] = (
        STATE_BYTES_PER_STORAGE_SLOT * out["new_storage_slots"]
        + STATE_BYTES_PER_ACCOUNT * out["new_accounts"]
        + out["code_bytes"]
        + STATE_BYTES_PER_DELEGATION * out["new_delegation_indicators"]
    ).astype("int64")
    out["state_metered_gas_8037"] = (
        int(cpsb) * out["state_bytes_8037"]
    ).astype("int64")
    return out


def attach_static_data_content(
    frame: pd.DataFrame,
    transaction_body_content: pd.DataFrame | None = None,
    *,
    data_gas_per_byte: int = DATA_GAS_PER_BYTE,
) -> pd.DataFrame:
    """Attach known and complete EIP-7999 static-data content.

    ``transaction_body_content`` must contain one row per transaction and the
    access-list/address, access-list/storage-key, and authorization-tuple
    counts. When it is absent, exact Xatu calldata and blob-hash content are
    retained in ``static_data_bytes_xatu_known`` and the complete field remains
    nullable.
    """

    if int(data_gas_per_byte) <= 0:
        raise ValueError("data_gas_per_byte must be positive")
    required = {
        *KEY_COLUMNS,
        "calldata_bytes",
        "blob_versioned_hash_count",
    }
    _require_columns(frame, required, "static-data")
    out = frame.copy()
    out["blob_versioned_hash_bytes"] = (
        32
        * pd.to_numeric(out["blob_versioned_hash_count"], errors="raise").fillna(0)
    ).astype("int64")
    out["static_data_bytes_xatu_known"] = (
        pd.to_numeric(out["calldata_bytes"], errors="raise").fillna(0)
        + out["blob_versioned_hash_bytes"]
    ).astype("int64")
    out["static_data_gas_xatu_known"] = (
        int(data_gas_per_byte) * out["static_data_bytes_xatu_known"]
    ).astype("int64")

    detail_columns = [
        "access_list_address_count",
        "access_list_storage_key_count",
        "authorization_tuple_count",
    ]
    if transaction_body_content is None:
        for column in detail_columns:
            out[column] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        out["access_list_bytes_8131"] = pd.Series(
            pd.NA, index=out.index, dtype="Int64"
        )
        out["authorization_tuple_bytes_8131"] = pd.Series(
            pd.NA, index=out.index, dtype="Int64"
        )
        out["authorization_bal_static_bytes_8279"] = pd.Series(
            pd.NA, index=out.index, dtype="Int64"
        )
        out["static_data_bytes_7999"] = pd.Series(
            pd.NA, index=out.index, dtype="Int64"
        )
        out["static_data_gas_7999"] = pd.Series(
            pd.NA, index=out.index, dtype="Int64"
        )
        out["static_data_detail_complete"] = False
        return out

    detail = transaction_body_content.copy()
    aliases = {
        "tx_access_list_address_count": "access_list_address_count",
        "tx_access_list_storage_key_count": "access_list_storage_key_count",
    }
    for source, target in aliases.items():
        if target not in detail and source in detail:
            detail = detail.rename(columns={source: target})
    detail_required = {*KEY_COLUMNS, *detail_columns}
    _require_columns(detail, detail_required, "transaction-body")

    validation_columns = []
    if "calldata_bytes_rpc" in detail:
        validation_columns.append("calldata_bytes_rpc")
    elif "calldata_bytes" in detail:
        detail = detail.rename(columns={"calldata_bytes": "calldata_bytes_rpc"})
        validation_columns.append("calldata_bytes_rpc")
    if "blob_versioned_hash_count_rpc" in detail:
        validation_columns.append("blob_versioned_hash_count_rpc")
    elif "blob_versioned_hash_count" in detail:
        detail = detail.rename(
            columns={"blob_versioned_hash_count": "blob_versioned_hash_count_rpc"}
        )
        validation_columns.append("blob_versioned_hash_count_rpc")
    detail = detail[[*KEY_COLUMNS, *detail_columns, *validation_columns]].copy()
    for table in [out, detail]:
        table["tx_hash"] = table["tx_hash"].map(_normalize_hash)
    if detail.duplicated(KEY_COLUMNS).any():
        raise ValueError("Transaction-body content contains duplicate transactions")
    out = out.merge(
        detail,
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    if out[detail_columns].isna().any().any():
        missing = int(out[detail_columns].isna().any(axis=1).sum())
        raise ValueError(
            f"Transaction-body content is missing for {missing} transactions"
        )
    if "calldata_bytes_rpc" in out:
        mismatch = pd.to_numeric(out["calldata_bytes_rpc"], errors="raise").ne(
            pd.to_numeric(out["calldata_bytes"], errors="raise")
        )
        if mismatch.any():
            raise ValueError(
                f"RPC calldata bytes differ from Xatu for {int(mismatch.sum())} transactions"
            )
    if "blob_versioned_hash_count_rpc" in out:
        mismatch = pd.to_numeric(
            out["blob_versioned_hash_count_rpc"], errors="raise"
        ).ne(pd.to_numeric(out["blob_versioned_hash_count"], errors="raise"))
        if mismatch.any():
            raise ValueError(
                "RPC blob-versioned-hash counts differ from Xatu for "
                f"{int(mismatch.sum())} transactions"
            )
    out[detail_columns] = out[detail_columns].apply(
        pd.to_numeric, errors="raise"
    ).astype("int64")
    if (out[detail_columns] < 0).any().any():
        raise ValueError("Transaction-body content counts cannot be negative")
    out["access_list_bytes_8131"] = (
        ACCESS_LIST_ADDRESS_BYTES * out["access_list_address_count"]
        + ACCESS_LIST_STORAGE_KEY_BYTES * out["access_list_storage_key_count"]
    ).astype("int64")
    out["authorization_tuple_bytes_8131"] = (
        AUTHORIZATION_TUPLE_BYTES * out["authorization_tuple_count"]
    ).astype("int64")
    # EIP-8279 statically reserves the authority address (20 bytes),
    # delegation code (23), and nonce (8) created by each authorization. This
    # is separate from both EIP-8131's 108-byte tuple and runtime bal_data_bytes.
    out["authorization_bal_static_bytes_8279"] = (
        AUTHORIZATION_BAL_STATIC_BYTES * out["authorization_tuple_count"]
    ).astype("int64")
    out["static_data_bytes_7999"] = (
        out["static_data_bytes_xatu_known"]
        + out["access_list_bytes_8131"]
        + out["authorization_tuple_bytes_8131"]
        + out["authorization_bal_static_bytes_8279"]
    ).astype("int64")
    out["static_data_gas_7999"] = (
        int(data_gas_per_byte) * out["static_data_bytes_7999"]
    ).astype("int64")
    out["static_data_detail_complete"] = True
    return out


def normalize_compact_carrier_static_accounting(
    carriers: pd.DataFrame,
    *,
    data_gas_per_byte: int = DATA_GAS_PER_BYTE,
) -> pd.DataFrame:
    """Upgrade cached compact rows to complete EIP-8131/EIP-8279 static data.

    The derivation is deterministic from fields already present in every
    checkpoint. Recomputing it during finalization keeps old and new chunks
    compatible without repeating any Xatu or RPC query.
    """

    if int(data_gas_per_byte) <= 0:
        raise ValueError("data_gas_per_byte must be positive")
    required = {
        "authorization_tuple_count",
        "authorization_tuple_bytes_8131",
        "access_list_bytes_8131",
        "static_data_bytes_xatu_known",
    }
    _require_columns(carriers, required, "compact-carrier static accounting")
    out = carriers.copy()
    numeric = sorted(required)
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="raise")
    if out[numeric].isna().any().any():
        raise ValueError("Compact carrier static accounting is incomplete")
    if (out[numeric] < 0).any().any():
        raise ValueError("Compact carrier static accounting cannot be negative")
    expected_tuple_bytes = (
        AUTHORIZATION_TUPLE_BYTES * out["authorization_tuple_count"]
    )
    if not np.array_equal(
        expected_tuple_bytes.to_numpy(),
        out["authorization_tuple_bytes_8131"].to_numpy(),
    ):
        raise ValueError("Authorization tuple bytes do not match tuple counts")
    out["authorization_bal_static_bytes_8279"] = (
        AUTHORIZATION_BAL_STATIC_BYTES * out["authorization_tuple_count"]
    ).astype("int64")
    out["static_data_bytes_7999"] = (
        out["static_data_bytes_xatu_known"]
        + out["access_list_bytes_8131"]
        + out["authorization_tuple_bytes_8131"]
        + out["authorization_bal_static_bytes_8279"]
    ).astype("int64")
    out["static_data_gas_7999"] = (
        int(data_gas_per_byte) * out["static_data_bytes_7999"]
    ).astype("int64")
    return out


def build_bal_carrier_transaction_panel(
    attributed_runtime: pd.DataFrame,
    gas_inputs: pd.DataFrame,
    transaction_body_content: pd.DataFrame | None = None,
    *,
    execution_multiplier: float = 1.537898,
    cpsb: int = EIP8037_CPSB,
    data_gas_per_byte: int = DATA_GAS_PER_BYTE,
) -> pd.DataFrame:
    """Join transaction accounting and return a reconciled all-transaction panel."""

    if float(execution_multiplier) <= 0:
        raise ValueError("execution_multiplier must be positive")
    required_runtime = {
        *KEY_COLUMNS,
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
        "historical_state_creation_gas",
        "new_storage_slots",
        "new_accounts",
        "code_bytes",
        "new_delegation_indicators",
        "state_bundle",
    }
    required_gas = {
        *KEY_COLUMNS,
        "receipt_gas_used",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "calldata_bytes",
        "standard_calldata_gas",
        "blob_versioned_hash_count",
    }
    _require_columns(attributed_runtime, required_runtime, "attributed-runtime")
    _require_columns(gas_inputs, required_gas, "transaction-gas")

    left = attributed_runtime.copy()
    right = gas_inputs.copy()
    for table in [left, right]:
        table["tx_hash"] = table["tx_hash"].map(_normalize_hash)
    if left.duplicated(KEY_COLUMNS).any() or right.duplicated(KEY_COLUMNS).any():
        raise ValueError("Transaction inputs contain duplicate join keys")
    out = left.merge(right, on=KEY_COLUMNS, how="inner", validate="one_to_one")
    if len(out) != len(left) or len(out) != len(right):
        raise ValueError("Runtime and transaction-gas panels do not fully reconcile")

    component_total = out[BAL_COMPONENT_COLUMNS].sum(axis=1)
    if not component_total.equals(out["bal_runtime_bytes_8279"].astype("int64")):
        raise ValueError("Transaction BAL components do not reconcile")

    out = attach_eip7623_receipt_decomposition(out)
    out = attach_eip8037_state_metering(out, cpsb=cpsb)
    out["execution_metered_gas_7999"] = (
        float(execution_multiplier) * out["execution_reference_gas"]
    )
    out = attach_static_data_content(
        out,
        transaction_body_content,
        data_gas_per_byte=data_gas_per_byte,
    )
    out["bal_metered_gas_7999"] = (
        int(data_gas_per_byte) * out["bal_runtime_bytes_8279"]
    ).astype("int64")
    out["is_bal_carrier"] = out["bal_runtime_bytes_8279"].gt(0)
    return out.sort_values(["block_number", "tx_index"]).reset_index(drop=True)


def aggregate_bal_carrier_blocks(panel: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a transaction panel for cache and accounting reconciliation."""

    required = {
        "block_number",
        "state_bundle",
        "is_bal_carrier",
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
        "receipt_gas_used",
        "current_data_gas_7623_proxy",
        "state_reference_gas_capped",
        "execution_reference_gas",
        "execution_metered_gas_7999",
        "state_metered_gas_8037",
        "static_data_bytes_xatu_known",
    }
    _require_columns(panel, required, "carrier block-aggregation")
    work = panel.copy()
    work["transaction_count"] = 1
    work["carrier_transaction_count"] = work["is_bal_carrier"].astype("int64")
    work["state_transaction_count"] = work["state_bundle"].astype("int64")
    work["direct_state_transaction_count"] = work[
        "bal_runtime_bytes_direct_state_8279"
    ].gt(0).astype("int64")
    sum_columns = [
        "transaction_count",
        "carrier_transaction_count",
        "state_transaction_count",
        "direct_state_transaction_count",
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
        "receipt_gas_used",
        "current_data_gas_7623_proxy",
        "state_reference_gas_capped",
        "execution_reference_gas",
        "execution_metered_gas_7999",
        "state_metered_gas_8037",
        "static_data_bytes_xatu_known",
    ]
    block = work.groupby("block_number", as_index=False)[sum_columns].sum()
    reference_sum = (
        block["current_data_gas_7623_proxy"]
        + block["state_reference_gas_capped"]
        + block["execution_reference_gas"]
    )
    if not np.array_equal(reference_sum.to_numpy(), block["receipt_gas_used"]):
        raise ValueError("Block historical gas decomposition does not reconcile")
    return block.sort_values("block_number").reset_index(drop=True)


def validate_bal_carrier_block_reconciliation(
    block_panel: pd.DataFrame,
    reference: pd.DataFrame,
) -> None:
    """Validate transaction sums against the established 6,000-block cache."""

    column_map: Mapping[str, str] = {
        "transaction_count": "transactions",
        "state_transaction_count": "state_transactions",
        "direct_state_transaction_count": "direct_state_transactions",
        "bal_runtime_bytes_8279": "bal_runtime_bytes_8279",
        "bal_runtime_bytes_direct_state_8279": "bal_runtime_bytes_state_8279",
        "bal_runtime_bytes_coproduced_state_txs_8279": (
            "bal_runtime_bytes_coproduced_state_txs_8279"
        ),
        "bal_runtime_bytes_nonstate_txs_8279": (
            "bal_runtime_bytes_nonstate_txs_8279"
        ),
    }
    _require_columns(block_panel, {"block_number", *column_map}, "block-panel")
    _require_columns(
        reference,
        {"block_number", *column_map.values()},
        "block-reference",
    )
    if block_panel["block_number"].duplicated().any():
        raise ValueError("Block panel contains duplicate blocks")
    if reference["block_number"].duplicated().any():
        raise ValueError("Block reference contains duplicate blocks")
    merged = block_panel[["block_number", *column_map]].merge(
        reference[["block_number", *column_map.values()]],
        on="block_number",
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_panel", "_reference"),
    )
    if not merged["_merge"].eq("both").all():
        missing = merged.loc[~merged["_merge"].eq("both"), "block_number"].tolist()
        raise ValueError(f"Block panel/reference membership differs: {missing[:10]}")
    for panel_column, reference_column in column_map.items():
        left_name = (
            f"{panel_column}_panel"
            if panel_column == reference_column
            else panel_column
        )
        right_name = (
            f"{reference_column}_reference"
            if panel_column == reference_column
            else reference_column
        )
        left = pd.to_numeric(merged[left_name], errors="raise").to_numpy()
        right = pd.to_numeric(merged[right_name], errors="raise").to_numpy()
        mismatch = left != right
        if mismatch.any():
            rows = merged.loc[mismatch, "block_number"].head(10).tolist()
            max_difference = float(np.max(np.abs(left[mismatch] - right[mismatch])))
            raise ValueError(
                f"Carrier reconciliation failed for {panel_column}: "
                f"blocks {rows}, max difference {max_difference:g}"
            )


def validate_compact_carriers_against_blocks(
    carriers: pd.DataFrame,
    block_panel: pd.DataFrame,
) -> None:
    """Require the assembled compact carrier rows to reproduce block totals.

    Chunk-level validation protects the source query, while this independent
    final check protects against a missing, truncated, or mismatched compact
    carrier Parquet part during assembly.
    """

    carrier_columns = {
        *KEY_COLUMNS,
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
    }
    block_columns = {
        "block_number",
        "carrier_transaction_count",
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
    }
    _require_columns(carriers, carrier_columns, "compact-carrier")
    _require_columns(block_panel, block_columns, "block-panel")
    if carriers.duplicated(KEY_COLUMNS).any():
        raise ValueError("Compact carrier panel contains duplicate transactions")
    if block_panel["block_number"].duplicated().any():
        raise ValueError("Block panel contains duplicate blocks")

    requested_blocks = set(block_panel["block_number"].astype("int64"))
    carrier_blocks = set(carriers["block_number"].astype("int64"))
    outside = sorted(carrier_blocks.difference(requested_blocks))
    if outside:
        raise ValueError(
            f"Compact carrier panel contains blocks outside the block panel: {outside[:10]}"
        )

    compact = carriers.copy()
    compact["carrier_transaction_count"] = 1
    sum_columns = [
        "carrier_transaction_count",
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
    ]
    actual = compact.groupby("block_number", as_index=False)[sum_columns].sum()
    actual = block_panel[["block_number"]].merge(
        actual,
        on="block_number",
        how="left",
        validate="one_to_one",
    )
    actual[sum_columns] = actual[sum_columns].fillna(0)

    expected = block_panel[["block_number", *sum_columns]].copy()
    for column in sum_columns:
        left = pd.to_numeric(actual[column], errors="raise").to_numpy()
        right = pd.to_numeric(expected[column], errors="raise").to_numpy()
        mismatch = left != right
        if mismatch.any():
            rows = expected.loc[mismatch, "block_number"].head(10).tolist()
            max_difference = float(np.max(np.abs(left[mismatch] - right[mismatch])))
            raise ValueError(
                f"Compact carrier/block reconciliation failed for {column}: "
                f"blocks {rows}, max difference {max_difference:g}"
            )


def compact_carrier_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Return only BAL-carrying transactions and analysis-facing columns."""

    columns = [
        *KEY_COLUMNS,
        "transaction_type",
        "bal_runtime_bytes_8279",
        *BAL_COMPONENT_COLUMNS,
        "receipt_gas_used",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "calldata_bytes",
        "calldata_tokens",
        "standard_calldata_gas",
        "current_7623_floor_gas",
        "current_7623_floor_bound_proxy",
        "current_data_gas_7623_proxy",
        "historical_state_creation_gas",
        "state_reference_gas_capped",
        "execution_reference_gas",
        "execution_metered_gas_7999",
        "state_bytes_8037",
        "state_metered_gas_8037",
        "blob_versioned_hash_count",
        "blob_versioned_hash_bytes",
        "access_list_address_count",
        "access_list_storage_key_count",
        "access_list_bytes_8131",
        "authorization_tuple_count",
        "authorization_tuple_bytes_8131",
        "authorization_bal_static_bytes_8279",
        "static_data_bytes_xatu_known",
        "static_data_gas_xatu_known",
        "static_data_bytes_7999",
        "static_data_gas_7999",
        "static_data_detail_complete",
        "bal_metered_gas_7999",
    ]
    _require_columns(panel, set(columns), "compact-carrier")
    return panel.loc[panel["is_bal_carrier"], columns].reset_index(drop=True)
