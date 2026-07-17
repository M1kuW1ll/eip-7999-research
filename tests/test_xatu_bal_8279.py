import pandas as pd
import pytest

from sim.xatu_bal_8279 import (
    aggregate_state_execution_runtime_blocks,
    attribute_direct_state_runtime_bytes,
    attach_normalized_composite_costs,
    attach_state_bundle,
    compute_eip8279_runtime_block_bytes,
    compute_eip8279_runtime_bytes,
    query_xatu_eip8279_runtime_blocks,
    runtime_bundle_parameter_card,
)
from sim.xatu_glamsterdam import query_xatu_tx_state_creation


def test_compute_eip8279_runtime_bytes_uses_protocol_component_weights():
    source = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 2,
                "tx_hash": "0xabc",
                "cold_account_accesses": 2,
                "cold_storage_accesses": 3,
                "storage_value_entries_observed": 1,
                "positive_value_calls": 1,
                "positive_value_selfdestructs": 1,
                "internal_creates": 2,
                "internal_create_endowments": 1,
                "internal_deployed_code_bytes": 10,
            }
        ]
    )

    result = compute_eip8279_runtime_bytes(source).iloc[0]

    assert result["account_access_bytes_8279"] == 40
    assert result["storage_key_bytes_8279"] == 96
    assert result["storage_value_bytes_8279_observed"] == 32
    assert result["balance_call_bytes_8279"] == 32
    assert result["balance_selfdestruct_bytes_8279"] == 32
    assert result["create_address_bytes_8279"] == 40
    assert result["create_nonce_bytes_8279"] == 16
    assert result["create_endowment_bytes_8279"] == 32
    assert result["deployed_code_bytes_8279"] == 10
    assert result["bal_runtime_bytes_8279"] == 330


def test_compute_eip8279_runtime_bytes_rejects_negative_counts():
    source = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xabc",
                "cold_account_accesses": -1,
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

    with pytest.raises(ValueError, match="cannot be negative"):
        compute_eip8279_runtime_bytes(source)


def test_compute_block_runtime_bytes_matches_transaction_weights():
    source = pd.DataFrame(
        [
            {
                "block_number": 1,
                "cold_account_accesses": 2,
                "cold_storage_accesses": 3,
                "storage_value_entries_observed": 1,
                "positive_value_calls": 1,
                "positive_value_selfdestructs": 1,
                "internal_creates": 2,
                "internal_create_endowments": 1,
                "internal_deployed_code_bytes": 10,
            }
        ]
    )

    result = compute_eip8279_runtime_block_bytes(source).iloc[0]

    assert result["bal_runtime_bytes_8279"] == 330


def test_block_query_fills_missing_components_and_requested_blocks():
    class RecordingClient:
        def __init__(self):
            self.calls = 0

        def query_df(self, query, parameters):
            self.calls += 1
            if "structlog" in query:
                return pd.DataFrame(
                    [{"block_number": 1, "cold_account_accesses": 2, "cold_storage_accesses": 3}]
                )
            if "storage_diffs" in query:
                return pd.DataFrame(
                    [{"block_number": 1, "storage_value_entries_observed": 1}]
                )
            return pd.DataFrame(
                [
                    {
                        "block_number": 1,
                        "positive_value_calls": 1,
                        "positive_value_selfdestructs": 1,
                        "internal_creates": 2,
                        "internal_create_endowments": 1,
                        "internal_deployed_code_bytes": 10,
                    }
                ]
            )

    client = RecordingClient()
    result = query_xatu_eip8279_runtime_blocks(client, [2, 1])

    assert client.calls == 3
    assert result["block_number"].tolist() == [1, 2]
    assert result.loc[result["block_number"].eq(1), "bal_runtime_bytes_8279"].item() == 330
    assert result.loc[result["block_number"].eq(2), "bal_runtime_bytes_8279"].item() == 0


def test_attach_state_bundle_partitions_runtime_bytes():
    counts = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": tx_index,
                "tx_hash": tx_hash,
                "cold_account_accesses": accesses,
                "cold_storage_accesses": 0,
                "storage_value_entries_observed": 0,
                "positive_value_calls": 0,
                "positive_value_selfdestructs": 0,
                "internal_creates": 0,
                "internal_create_endowments": 0,
                "internal_deployed_code_bytes": 0,
            }
            for tx_index, tx_hash, accesses in [(0, "0xa", 1), (1, "0xb", 4)]
        ]
    )
    meter = compute_eip8279_runtime_bytes(counts)
    state = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 1,
                "tx_hash": "0xb",
                "new_storage_slots": 1,
                "new_accounts": 0,
                "code_bytes": 0,
                "new_delegation_indicators": 0,
                "historical_state_creation_gas": 20_000,
            }
        ]
    )

    classified = attach_state_bundle(meter, state)
    card = runtime_bundle_parameter_card(classified).iloc[0]

    assert classified["state_bundle"].tolist() == [False, True]
    assert card["state_bundle_weight_8279"] == pytest.approx(0.8)
    assert card["execution_access_weight_8279"] == pytest.approx(0.2)
    assert card["bal_runtime_bytes_per_block_8279"] == 100


def test_tx_state_creation_requires_first_appearance_in_candidate_block():
    class RecordingClient:
        def __init__(self):
            self.queries = []

        def query_df(self, query, parameters):
            self.queries.append(query)
            return pd.DataFrame()

    client = RecordingClient()
    query_xatu_tx_state_creation(client, [10])

    account_query = client.queries[2]
    assert "first_appearances.first_block = candidate_block" in account_query
    assert "first_appearances.first_block BETWEEN" not in account_query


def test_direct_state_runtime_attribution_reconciles_two_components():
    counts = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "cold_account_accesses": 2,
                "cold_storage_accesses": 3,
                "storage_value_entries_observed": 2,
                "positive_value_calls": 1,
                "positive_value_selfdestructs": 0,
                "internal_creates": 1,
                "internal_create_endowments": 0,
                "internal_deployed_code_bytes": 10,
            },
            {
                "block_number": 1,
                "tx_index": 1,
                "tx_hash": "0xb",
                "cold_account_accesses": 1,
                "cold_storage_accesses": 1,
                "storage_value_entries_observed": 0,
                "positive_value_calls": 0,
                "positive_value_selfdestructs": 0,
                "internal_creates": 0,
                "internal_create_endowments": 0,
                "internal_deployed_code_bytes": 0,
            },
        ]
    )
    meter = compute_eip8279_runtime_bytes(counts)
    state = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "new_storage_slots": 1,
                "new_accounts": 2,
                "code_bytes": 10,
                "new_delegation_indicators": 0,
                "historical_state_creation_gas": 47_000,
            }
        ]
    )

    result = attribute_direct_state_runtime_bytes(attach_state_bundle(meter, state))
    state_tx = result.iloc[0]
    nonstate_tx = result.iloc[1]

    assert state_tx["direct_new_storage_key_bytes_8279"] == 32
    assert state_tx["direct_new_storage_value_bytes_8279"] == 32
    assert state_tx["direct_create_address_bytes_8279"] == 20
    assert state_tx["direct_create_nonce_bytes_8279"] == 8
    assert state_tx["direct_new_account_access_bytes_8279"] == 20
    assert state_tx["direct_new_account_balance_bytes_8279"] == 32
    assert state_tx["direct_deployed_code_bytes_8279"] == 10
    assert state_tx["bal_runtime_bytes_direct_state_8279"] == 154
    assert nonstate_tx["bal_runtime_bytes_direct_state_8279"] == 0
    assert nonstate_tx["bal_runtime_bytes_nonstate_txs_8279"] == 52
    assert (
        result["bal_runtime_bytes_direct_state_8279"]
        + result["bal_runtime_bytes_access_related_8279"]
        == result["bal_runtime_bytes_8279"]
    ).all()

    block = aggregate_state_execution_runtime_blocks(result).iloc[0]
    assert block["bal_runtime_bytes_state_8279"] == 154
    assert block["bal_runtime_bytes_execution_8279"] == 168
    assert block["bal_runtime_bytes_8279"] == 322
    assert block["runtime_transactions"] == 2
    assert block["state_runtime_transactions"] == 1


def test_normalized_composite_costs_reconcile_and_sum_to_one():
    counts = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "cold_account_accesses": 1,
                "cold_storage_accesses": 1,
                "storage_value_entries_observed": 1,
                "positive_value_calls": 0,
                "positive_value_selfdestructs": 0,
                "internal_creates": 0,
                "internal_create_endowments": 0,
                "internal_deployed_code_bytes": 0,
            }
        ]
    )
    state = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "new_storage_slots": 1,
                "new_accounts": 0,
                "code_bytes": 0,
                "new_delegation_indicators": 0,
                "historical_state_creation_gas": 20_000,
            }
        ]
    )
    attributed = attribute_direct_state_runtime_bytes(
        attach_state_bundle(compute_eip8279_runtime_bytes(counts), state)
    )
    gas_inputs = pd.DataFrame(
        [
            {
                "block_number": 1,
                "tx_index": 0,
                "tx_hash": "0xa",
                "receipt_gas_used": 50_000,
                "standard_calldata_gas": 1_000,
                "calldata_bytes": 100,
            }
        ]
    )

    result = attach_normalized_composite_costs(attributed, gas_inputs).iloc[0]

    assert result["execution_reference_gas"] == 29_000
    assert result["state_reference_gas_capped"] == 20_000
    assert result["data_metered_gas_7999_proxy"] == 16 * (100 + 84)
    assert result["state_metered_gas_7999_proxy"] == 1530 * 64
    assert (
        result["execution_composite_cost_share"]
        + result["data_composite_cost_share"]
        + result["state_composite_cost_share"]
    ) == pytest.approx(1.0)
