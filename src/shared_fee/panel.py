"""Transaction and block accounting for the EIP-8131/EIP-8279 benchmark."""

from __future__ import annotations

import numpy as np
import pandas as pd

from shared_fee.floor_accounting import (
    ACCESS_LIST_ADDRESS_COST_8038,
    ACCESS_LIST_STORAGE_KEY_COST_8038,
    ACCOUNT_WRITE_8038,
    AUTH_BAL_STATIC_BYTES_8279,
    COLD_STORAGE_ACCESS_8038,
    CREATE_ACCESS_8038,
    FLOOR_GAS_PER_BYTE,
    STORAGE_WRITE_8038,
    eip2780_floor_base,
)


KEYS = ["block_number", "tx_index", "tx_hash"]
CURRENT_TX_BASE = 21_000
CURRENT_FLOOR_PER_TOKEN = 10


def build_transaction_floor_panel(
    *,
    transaction_inputs: pd.DataFrame,
    static_content: pd.DataFrame,
    carrier_runtime: pd.DataFrame,
    execution_components: pd.DataFrame,
    sampled_blocks: pd.DataFrame,
    daily_execution: pd.DataFrame,
) -> pd.DataFrame:
    """Build the exact-content, sampled transaction floor panel.

    The EIP-8038/EIP-2780 execution path is represented by the exact daily
    execution multiplier applied to each transaction's historical execution
    activity. This reconciles the sample to the project's full-range execution
    calibration while retaining transaction-level floor heterogeneity.
    """

    tx = transaction_inputs.copy()
    static = static_content.copy()
    runtime_columns = [
        *KEYS,
        "bal_runtime_bytes_8279",
        "bal_runtime_bytes_direct_state_8279",
        "bal_runtime_bytes_coproduced_state_txs_8279",
        "bal_runtime_bytes_nonstate_txs_8279",
        "state_reference_gas_capped",
    ]
    runtime = carrier_runtime[runtime_columns].copy()
    repricing = execution_components.copy()
    blocks = sampled_blocks[["date", "block_number"]].copy()
    daily = daily_execution[
        ["date", "m_execution_8038_2780_refund_corrected_daily"]
    ].copy()

    for frame in (tx, static, runtime, repricing):
        frame["tx_hash"] = frame["tx_hash"].astype(str)
        if frame.duplicated(KEYS).any():
            raise ValueError("Transaction input contains duplicate keys")

    if set(map(tuple, tx[KEYS].to_numpy())) != set(
        map(tuple, static[KEYS].to_numpy())
    ):
        raise ValueError("Transaction inputs and static content do not reconcile")

    out = tx.merge(static, on=KEYS, how="inner", validate="one_to_one")
    out = out.merge(runtime, on=KEYS, how="left", validate="one_to_one")
    runtime_value_columns = [column for column in runtime_columns if column not in KEYS]
    out[runtime_value_columns] = out[runtime_value_columns].fillna(0)
    repricing_value_columns = [column for column in repricing if column not in KEYS]
    out = out.merge(repricing, on=KEYS, how="left", validate="one_to_one")
    out[repricing_value_columns] = out[repricing_value_columns].fillna(0)
    out = out.merge(blocks, on="block_number", how="left", validate="many_to_one")
    out["date"] = pd.to_datetime(out["date"])
    daily["date"] = pd.to_datetime(daily["date"])
    out = out.merge(daily, on="date", how="left", validate="many_to_one")
    if out["m_execution_8038_2780_refund_corrected_daily"].isna().any():
        raise ValueError("Daily execution calibration does not cover sampled blocks")

    integer_columns = [
        "receipt_gas_used",
        "calldata_zero_bytes",
        "calldata_nonzero_bytes",
        "standard_calldata_gas",
        "static_data_8131_bytes",
        "tx_access_list_bytes",
        "authorization_tuple_8131_bytes",
        "blob_versioned_hash_8131_bytes",
        "authorization_tuple_count",
        "bal_runtime_bytes_8279",
        "state_reference_gas_capped",
    ]
    out[integer_columns] = out[integer_columns].apply(
        pd.to_numeric, errors="raise"
    ).astype("int64")

    out["calldata_tokens"] = (
        out["calldata_zero_bytes"] + 4 * out["calldata_nonzero_bytes"]
    ).astype("int64")
    out["current_7623_floor_body"] = (
        CURRENT_FLOOR_PER_TOKEN * out["calldata_tokens"]
    ).astype("int64")
    out["current_floor_bound_proxy"] = (
        out["calldata_tokens"].gt(0)
        & (out["receipt_gas_used"] - CURRENT_TX_BASE).le(
            out["current_7623_floor_body"]
        )
    )
    out["current_data_gas_proxy"] = np.where(
        out["current_floor_bound_proxy"],
        out["current_7623_floor_body"],
        out["standard_calldata_gas"],
    ).astype("int64")

    receipt_after_data = out["receipt_gas_used"] - out["current_data_gas_proxy"]
    out["state_reference_gas_capped"] = np.minimum(
        out["state_reference_gas_capped"], receipt_after_data
    ).astype("int64")
    out["execution_reference_gas"] = (
        receipt_after_data - out["state_reference_gas_capped"]
    ).astype("int64")
    if (out["execution_reference_gas"] < 0).any():
        raise ValueError("Historical transaction decomposition became negative")

    out["intrinsic_execution_base_2780"] = [
        eip2780_floor_base(
            has_recipient=bool(has_recipient),
            self_transfer=bool(self_transfer),
            transfers_value=bool(transfers_value),
            authorization_count=int(auths),
        )
        for has_recipient, self_transfer, transfers_value, auths in zip(
            out["has_recipient"],
            out["self_transfer"],
            out["transfers_value"],
            out["authorization_tuple_count"],
            strict=True,
        )
    ]
    out["static_data_7976_7981_bytes"] = (
        out["calldata_zero_bytes"]
        + out["calldata_nonzero_bytes"]
        + out["tx_access_list_bytes"]
    ).astype("int64")
    out["additional_static_data_8131_bytes"] = (
        out["authorization_tuple_8131_bytes"]
        + out["blob_versioned_hash_8131_bytes"]
    ).astype("int64")
    out["floor_gas_7976_7981"] = (
        out["intrinsic_execution_base_2780"]
        + FLOOR_GAS_PER_BYTE * out["static_data_7976_7981_bytes"]
    ).astype("int64")
    out["floor_gas_8131"] = (
        out["intrinsic_execution_base_2780"]
        + FLOOR_GAS_PER_BYTE * out["static_data_8131_bytes"]
    ).astype("int64")
    out["bal_floor_bytes_8279"] = (
        out["bal_runtime_bytes_8279"]
        + AUTH_BAL_STATIC_BYTES_8279 * out["authorization_tuple_count"]
    ).astype("int64")
    out["floor_gas_8279"] = (
        out["floor_gas_8131"]
        + FLOOR_GAS_PER_BYTE * out["bal_floor_bytes_8279"]
    ).astype("int64")

    # The standard calldata charge is part of execution_gas_used for the floor
    # comparison, but remains the data-demand component in the resource model.
    # Apply the observed-path EIP-8038 changes transaction by transaction.
    first_changes = (
        out["sstore_gas_current"]
        - 100 * out["sstore_count"]
        - 2_100 * out["sstore_cold_count"]
        - 17_100 * out["zero_to_nonzero_slots"]
    ) / 2_800
    out["sstore_first_changes_est"] = first_changes.clip(
        lower=out["zero_to_nonzero_slots"], upper=out["sstore_count"]
    )
    current_sstore_regular = (
        out["sstore_gas_current"] - 20_000 * out["zero_to_nonzero_slots"]
    )
    future_sstore_regular = (
        100 * (out["sstore_count"] - out["sstore_cold_count"])
        + COLD_STORAGE_ACCESS_8038 * out["sstore_cold_count"]
        + STORAGE_WRITE_8038 * out["sstore_first_changes_est"]
    )
    out["delta_execution_observed_path"] = (
        future_sstore_regular
        - current_sstore_regular
        + 400 * out["account_cold_count"]
        + 100 * out["ext_second_read_count"]
        + (ACCOUNT_WRITE_8038 - 6_700) * out["positive_value_internal_calls"]
        + (ACCESS_LIST_ADDRESS_COST_8038 - 2_400)
        * out["tx_access_list_address_count"]
        + (ACCESS_LIST_STORAGE_KEY_COST_8038 - 1_900)
        * out["tx_access_list_storage_key_count"]
        + ACCOUNT_WRITE_8038 * out["authorization_tuple_count"]
        + (CREATE_ACCESS_8038 - 32_000) * out["internal_create_opcode_count"]
        + 25_000 * out["successful_internal_creates"]
    )
    current_regular_base = np.where(
        out["has_recipient"],
        CURRENT_TX_BASE,
        np.where(out["state_reference_gas_capped"].gt(0), 28_000, 53_000),
    ) + 12_500 * out["authorization_tuple_count"]
    out["delta_intrinsic_2780"] = (
        out["intrinsic_execution_base_2780"] - current_regular_base
    )
    out["execution_repriced_raw"] = (
        out["execution_reference_gas"]
        + out["delta_execution_observed_path"]
        + out["delta_intrinsic_2780"]
    )

    # Refund reconstruction and unmeasured paths are already identified in the
    # calibrated daily multiplier. Allocate only the daily residual in proportion
    # to historical execution, preserving exact sampled daily totals.
    out["execution_repriced_target"] = (
        out["m_execution_8038_2780_refund_corrected_daily"]
        * out["execution_reference_gas"]
    )
    daily_sums = out.groupby("date").agg(
        q_execution=("execution_reference_gas", "sum"),
        raw=("execution_repriced_raw", "sum"),
        target=("execution_repriced_target", "sum"),
    )
    daily_sums["residual_rate"] = (
        daily_sums["target"] - daily_sums["raw"]
    ) / daily_sums["q_execution"].clip(lower=1)
    out = out.merge(
        daily_sums[["residual_rate"]],
        left_on="date",
        right_index=True,
        how="left",
        validate="many_to_one",
    )
    out["execution_repriced_excluding_data"] = (
        out["execution_repriced_raw"]
        + out["residual_rate"] * out["execution_reference_gas"]
    ).clip(lower=0)
    out["execution_gas_for_floor_daily_proxy"] = (
        out["execution_repriced_excluding_data"]
        + out["standard_calldata_gas"]
    )
    # EIP-7981's access-list data charge remains on the execution side of the
    # max comparison. EIP-8131 then extends the retained 7976/7981 floor only
    # with authorization tuples and blob-versioned hashes.
    out["access_list_data_gas_7981"] = (
        FLOOR_GAS_PER_BYTE * out["tx_access_list_bytes"]
    )
    out["execution_gas_for_floor"] = (
        out["execution_gas_for_floor_daily_proxy"]
        + out["access_list_data_gas_7981"]
    )
    out["charged_regular_gas_7976_7981"] = np.maximum(
        out["execution_gas_for_floor"], out["floor_gas_7976_7981"]
    )
    out["charged_regular_gas_8131"] = np.maximum(
        out["execution_gas_for_floor"], out["floor_gas_8131"]
    )
    out["charged_regular_gas_8279"] = np.maximum(
        out["execution_gas_for_floor"], out["floor_gas_8279"]
    )
    out["incremental_data_gas_8131"] = (
        out["charged_regular_gas_8131"]
        - out["charged_regular_gas_7976_7981"]
    )
    out["incremental_data_gas_8279"] = (
        out["charged_regular_gas_8279"] - out["charged_regular_gas_8131"]
    )
    out["incremental_data_gas_8131_8279"] = (
        out["incremental_data_gas_8131"]
        + out["incremental_data_gas_8279"]
    )
    if (
        out[["incremental_data_gas_8131", "incremental_data_gas_8279"]]
        < -1e-8
    ).any().any():
        raise ValueError("Counterfactual data accounting became negative")

    out["floor_bound_7976_7981"] = out["floor_gas_7976_7981"].ge(
        out["execution_gas_for_floor"]
    )
    out["floor_bound_8131"] = out["floor_gas_8131"].ge(
        out["execution_gas_for_floor"]
    )
    out["floor_bound_8279"] = out["floor_gas_8279"].ge(
        out["execution_gas_for_floor"]
    )
    out["newly_floor_bound_8279"] = (
        ~out["floor_bound_8131"] & out["floor_bound_8279"]
    )
    out["headroom_ratio_8131"] = (
        (out["execution_gas_for_floor"] - out["floor_gas_8131"])
        / out["execution_gas_for_floor"].clip(lower=1)
    )
    return out


def aggregate_sample_blocks(panel: pd.DataFrame, sampled_blocks: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transaction accounting while preserving sampled empty blocks."""

    sums = [
        "current_data_gas_proxy",
        "incremental_data_gas_8131",
        "incremental_data_gas_8279",
        "incremental_data_gas_8131_8279",
        "bal_runtime_bytes_8279",
        "bal_floor_bytes_8279",
        "execution_reference_gas",
        "state_reference_gas_capped",
    ]
    block = panel.groupby("block_number", as_index=False).agg(
        date=("date", "first"),
        transactions=("tx_hash", "size"),
        floor_bound_7976_7981_transactions=("floor_bound_7976_7981", "sum"),
        floor_bound_8131_transactions=("floor_bound_8131", "sum"),
        floor_bound_8279_transactions=("floor_bound_8279", "sum"),
        newly_floor_bound_8279_transactions=("newly_floor_bound_8279", "sum"),
        **{column: (column, "sum") for column in sums},
    )
    blocks = sampled_blocks[["date", "block_number"]].copy()
    blocks["date"] = pd.to_datetime(blocks["date"])
    out = blocks.merge(
        block.drop(columns="date"), on="block_number", how="left", validate="one_to_one"
    )
    numeric = [column for column in out if column not in {"date", "block_number"}]
    out[numeric] = out[numeric].fillna(0)
    return out
