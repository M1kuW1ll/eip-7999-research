import pandas as pd
import pytest

from sim.bal_carrier_panel import (
    aggregate_bal_carrier_blocks,
    align_runtime_meter_to_transactions,
    attach_eip7623_receipt_decomposition,
    attach_eip8037_state_metering,
    attach_static_data_content,
    build_bal_carrier_transaction_panel,
    compact_carrier_columns,
    normalize_compact_carrier_static_accounting,
    validate_bal_carrier_block_reconciliation,
    validate_compact_carriers_against_blocks,
)


def test_runtime_alignment_adds_plain_transfer_with_zero_bal():
    runtime = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "cold_account_accesses": 1,
                "cold_storage_accesses": 0,
                "storage_value_entries_observed": 0,
                "positive_value_calls": 0,
                "positive_value_selfdestructs": 0,
                "internal_creates": 0,
                "internal_create_endowments": 0,
                "internal_deployed_code_bytes": 0,
            }
        ]
    )
    gas = pd.DataFrame(
        [
            {"block_number": 1, "tx_index": 0, "tx_hash": "0xa"},
            {"block_number": 1, "tx_index": 1, "tx_hash": "0xb"},
        ]
    )

    result = align_runtime_meter_to_transactions(runtime, gas)

    assert len(result) == 2
    assert result.loc[result["tx_hash"].eq("0xa"), "bal_runtime_bytes_8279"].item() == 20
    assert result.loc[result["tx_hash"].eq("0xb"), "bal_runtime_bytes_8279"].item() == 0


def test_eip7623_receipt_decomposition_uses_observed_floor_and_reconciles():
    frame = pd.DataFrame(
        [
            {
                "receipt_gas_used": 61_000,
                "calldata_zero_bytes": 1_000,
                "calldata_nonzero_bytes": 750,
                "standard_calldata_gas": 13_000,
                "historical_state_creation_gas": 5_000,
            },
            {
                "receipt_gas_used": 80_000,
                "calldata_zero_bytes": 10,
                "calldata_nonzero_bytes": 20,
                "standard_calldata_gas": 360,
                "historical_state_creation_gas": 100_000,
            },
        ]
    )

    result = attach_eip7623_receipt_decomposition(frame)

    assert bool(result.loc[0, "current_7623_floor_bound_proxy"])
    assert result.loc[0, "current_7623_floor_gas"] == 40_000
    assert result.loc[0, "current_data_gas_7623_proxy"] == 40_000
    assert not bool(result.loc[1, "current_7623_floor_bound_proxy"])
    assert result.loc[1, "current_data_gas_7623_proxy"] == 360
    assert result.loc[1, "state_reference_gas_capped"] == 79_640
    assert result.loc[1, "execution_reference_gas"] == 0
    reconstructed = (
        result["current_data_gas_7623_proxy"]
        + result["state_reference_gas_capped"]
        + result["execution_reference_gas"]
    )
    assert reconstructed.equals(result["receipt_gas_used"].astype("int64"))


def test_eip7623_receipt_decomposition_rejects_sub_base_receipt():
    frame = pd.DataFrame(
        [{
            "receipt_gas_used": 20_999,
            "calldata_zero_bytes": 0,
            "calldata_nonzero_bytes": 0,
            "standard_calldata_gas": 0,
            "historical_state_creation_gas": 0,
        }]
    )

    with pytest.raises(ValueError, match="below transaction base gas"):
        attach_eip7623_receipt_decomposition(frame)


def test_eip8037_state_metering_uses_state_bytes_times_cpsb():
    frame = pd.DataFrame(
        [
            {
                "new_storage_slots": 2,
                "new_accounts": 1,
                "code_bytes": 10,
                "new_delegation_indicators": 1,
            }
        ]
    )

    result = attach_eip8037_state_metering(frame, cpsb=1530).iloc[0]

    assert result["state_bytes_8037"] == 2 * 64 + 120 + 10 + 23
    assert result["state_metered_gas_8037"] == 1530 * (2 * 64 + 120 + 10 + 23)


def test_static_data_keeps_known_xatu_content_and_marks_missing_detail():
    frame = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "calldata_bytes": 100,
                "blob_versioned_hash_count": 2,
            }
        ]
    )

    result = attach_static_data_content(frame).iloc[0]

    assert result["blob_versioned_hash_bytes"] == 64
    assert result["static_data_bytes_xatu_known"] == 164
    assert result["static_data_gas_xatu_known"] == 16 * 164
    assert pd.isna(result["static_data_bytes_7999"])
    assert not bool(result["static_data_detail_complete"])


def test_static_data_supplement_adds_access_lists_and_authorizations():
    frame = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "calldata_bytes": 100,
                "blob_versioned_hash_count": 2,
            }
        ]
    )
    detail = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "tx_access_list_address_count": 2,
                "tx_access_list_storage_key_count": 3,
                "authorization_tuple_count": 1,
                "calldata_bytes_rpc": 100,
                "blob_versioned_hash_count_rpc": 2,
            }
        ]
    )

    result = attach_static_data_content(frame, detail).iloc[0]

    assert result["access_list_bytes_8131"] == 2 * 20 + 3 * 32
    assert result["authorization_tuple_bytes_8131"] == 108
    assert result["authorization_bal_static_bytes_8279"] == 51
    assert result["static_data_bytes_7999"] == 100 + 64 + 136 + 108 + 51
    assert result["static_data_gas_7999"] == 16 * (100 + 64 + 136 + 108 + 51)
    assert bool(result["static_data_detail_complete"])


def _panel_inputs():
    attributed = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "bal_runtime_bytes_8279": 100,
                "bal_runtime_bytes_direct_state_8279": 20,
                "bal_runtime_bytes_coproduced_state_txs_8279": 30,
                "bal_runtime_bytes_nonstate_txs_8279": 50,
                "historical_state_creation_gas": 20_000,
                "new_storage_slots": 1,
                "new_accounts": 0,
                "code_bytes": 0,
                "new_delegation_indicators": 0,
                "state_bundle": True,
            },
            {
                "block_number": 1,
                "tx_index": 1,
                "tx_hash": "0xb",
                "bal_runtime_bytes_8279": 0,
                "bal_runtime_bytes_direct_state_8279": 0,
                "bal_runtime_bytes_coproduced_state_txs_8279": 0,
                "bal_runtime_bytes_nonstate_txs_8279": 0,
                "historical_state_creation_gas": 0,
                "new_storage_slots": 0,
                "new_accounts": 0,
                "code_bytes": 0,
                "new_delegation_indicators": 0,
                "state_bundle": False,
            },
        ]
    )
    gas = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "transaction_type": 2,
                "receipt_gas_used": 50_000,
                "calldata_zero_bytes": 10,
                "calldata_nonzero_bytes": 20,
                "calldata_bytes": 30,
                "standard_calldata_gas": 360,
                "blob_versioned_hash_count": 0,
            },
            {
                "block_number": 1,
                "tx_index": 1,
                "tx_hash": "0xb",
                "transaction_type": 3,
                "receipt_gas_used": 60_000,
                "calldata_zero_bytes": 0,
                "calldata_nonzero_bytes": 10,
                "calldata_bytes": 10,
                "standard_calldata_gas": 160,
                "blob_versioned_hash_count": 1,
            },
        ]
    )
    return attributed, gas


def test_compact_carrier_panel_and_block_reconciliation():
    attributed, gas = _panel_inputs()
    panel = build_bal_carrier_transaction_panel(
        attributed, gas, execution_multiplier=1.5
    )
    block = aggregate_bal_carrier_blocks(panel)
    reference = pd.DataFrame(
        [
            {
                "block_number": 1,
                "transactions": 2,
                "state_transactions": 1,
                "direct_state_transactions": 1,
                "bal_runtime_bytes_8279": 100,
                "bal_runtime_bytes_state_8279": 20,
                "bal_runtime_bytes_coproduced_state_txs_8279": 30,
                "bal_runtime_bytes_nonstate_txs_8279": 50,
            }
        ]
    )

    validate_bal_carrier_block_reconciliation(block, reference)
    carrier = compact_carrier_columns(panel)

    assert len(carrier) == 1
    assert carrier.loc[0, "tx_hash"] == "0xa"
    assert block.loc[0, "transaction_count"] == 2
    assert block.loc[0, "carrier_transaction_count"] == 1
    assert block.loc[0, "receipt_gas_used"] == 110_000
    assert block.loc[0, "execution_metered_gas_7999"] == pytest.approx(
        1.5 * block.loc[0, "execution_reference_gas"]
    )


def test_block_reconciliation_rejects_changed_bal_component():
    attributed, gas = _panel_inputs()
    block = aggregate_bal_carrier_blocks(
        build_bal_carrier_transaction_panel(attributed, gas)
    )
    reference = pd.DataFrame(
        [
            {
                "block_number": 1,
                "transactions": 2,
                "state_transactions": 1,
                "direct_state_transactions": 1,
                "bal_runtime_bytes_8279": 100,
                "bal_runtime_bytes_state_8279": 21,
                "bal_runtime_bytes_coproduced_state_txs_8279": 30,
                "bal_runtime_bytes_nonstate_txs_8279": 50,
            }
        ]
    )

    with pytest.raises(ValueError, match="direct_state"):
        validate_bal_carrier_block_reconciliation(block, reference)


def test_compact_carrier_reconciliation_detects_missing_transaction():
    attributed, gas = _panel_inputs()
    panel = build_bal_carrier_transaction_panel(attributed, gas)
    block = aggregate_bal_carrier_blocks(panel)
    carrier = compact_carrier_columns(panel)

    validate_compact_carriers_against_blocks(carrier, block)

    with pytest.raises(ValueError, match="carrier_transaction_count"):
        validate_compact_carriers_against_blocks(carrier.iloc[0:0], block)


def test_compact_static_normalizer_upgrades_old_checkpoint_schema():
    old = pd.DataFrame(
        [{
            "authorization_tuple_count": 2,
            "authorization_tuple_bytes_8131": 216,
            "access_list_bytes_8131": 84,
            "static_data_bytes_xatu_known": 1_000,
            "static_data_bytes_7999": 1_300,
            "static_data_gas_7999": 20_800,
        }]
    )

    upgraded = normalize_compact_carrier_static_accounting(old).iloc[0]

    assert upgraded["authorization_bal_static_bytes_8279"] == 102
    assert upgraded["static_data_bytes_7999"] == 1_402
    assert upgraded["static_data_gas_7999"] == 16 * 1_402
