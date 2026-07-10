import pandas as pd

from sim.xatu_state_growth import query_xatu_state_growth_by_block


class FakeCbtClient:
    def query_df(self, query, parameters=None):
        query_lower = query.lower()
        if "int_execution_block_by_date" in query_lower:
            return pd.DataFrame(
                [
                    {
                        "block_number": 100,
                        "timestamp": pd.Timestamp("2026-01-01T00:00:00"),
                    }
                ]
            )
        if "int_block_canonical" in query_lower:
            return pd.DataFrame(
                [
                    {
                        "block_number": 100,
                        "timestamp": pd.Timestamp("2026-01-01T00:00:00"),
                        "gas_used": 1_000_000,
                        "gas_limit": 60_000_000,
                        "base_fee_per_gas": 10,
                    }
                ]
            )
        if "int_block_resource_gas" in query_lower:
            return pd.DataFrame(
                [
                    {
                        "block_number": 100,
                        "gas_compute": 1,
                        "gas_memory": 2,
                        "gas_address_access": 3,
                        "gas_state_growth": 999,
                        "gas_history": 4,
                        "gas_bloom_topics": 5,
                        "gas_block_size": 6,
                        "gas_refund": 7,
                    }
                ]
            )
        if "int_transaction_resource_gas" in query_lower:
            return pd.DataFrame(
                [{"block_number": 100, "transaction_state_gas": 999}]
            )
        if "int_transaction_call_frame_opcode_resource_gas" in query_lower:
            return pd.DataFrame([{"block_number": 100, "opcode_state_gas": 600}])
        if "int_execution_state_size_by_block" in query_lower:
            return pd.DataFrame(
                [
                    {
                        "block_number": 99,
                        "accounts": 10,
                        "storages": 20,
                        "contract_codes": 1,
                        "account_bytes": 100,
                        "account_trienode_bytes": 200,
                        "contract_code_bytes": 300,
                        "storage_bytes": 400,
                        "storage_trienode_bytes": 500,
                    },
                    {
                        "block_number": 100,
                        "accounts": 12,
                        "storages": 22,
                        "contract_codes": 2,
                        "account_bytes": 120,
                        "account_trienode_bytes": 210,
                        "contract_code_bytes": 310,
                        "storage_bytes": 430,
                        "storage_trienode_bytes": 540,
                    },
                ]
            )
        raise AssertionError(f"Unexpected CBT query: {query}")


class FakeRawClient:
    def query_df(self, query, parameters=None):
        query_lower = query.lower()
        if "canonical_execution_storage_diffs" in query_lower:
            return pd.DataFrame(
                [
                    {
                        "block_number": 100,
                        "eip8037_new_storage_slots": 2,
                        "eip8037_zero_to_nonzero_storage_writes": 3,
                    }
                ]
            )
        if (
            "canonical_execution_contracts" in query_lower
            and "canonical_execution_balance_diffs" not in query_lower
        ):
            return pd.DataFrame(
                [
                    {
                        "block_number": 100,
                        "eip8037_new_contract_accounts": 1,
                        "eip8037_code_bytes": 10,
                    }
                ]
            )
        if "canonical_execution_address_appearances" in query_lower:
            assert "union all" in query_lower
            assert "group by address" in query_lower
            assert "min(candidate_block)" in query_lower
            return pd.DataFrame(
                [{"block_number": 100, "eip8037_new_accounts": 2}]
            )
        if "canonical_execution_balance_diffs" in query_lower:
            return pd.DataFrame(
                [{"block_number": 100, "eip8037_new_account_candidates": 3}]
            )
        if "execution_transaction" in query_lower:
            return pd.DataFrame(
                [{"block_number": 100, "eip8037_type4_tx_count": 1}]
            )
        raise AssertionError(f"Unexpected raw query: {query}")


def test_eip8037_state_gas_is_recomputed_from_raw_diffs():
    df = query_xatu_state_growth_by_block(
        FakeCbtClient(),
        [100],
        raw_client=FakeRawClient(),
        cpsb=1530,
    )

    row = df.iloc[0]
    expected_state_bytes = 2 * 64 + 2 * 120 + 10
    expected_state_gas = expected_state_bytes * 1530

    assert row["gas_state_growth"] == 999
    assert row["eip8037_new_account_candidates"] == 3
    assert row["eip8037_new_accounts"] == 2
    assert row["eip8037_storage_slot_state_bytes"] == 2 * 64
    assert row["eip8037_storage_slot_state_gas"] == 2 * 64 * 1530
    assert row["eip8037_new_account_state_bytes"] == 2 * 120
    assert row["eip8037_new_account_state_gas"] == 2 * 120 * 1530
    assert row["eip8037_code_deposit_state_bytes"] == 10
    assert row["eip8037_code_deposit_state_gas"] == 10 * 1530
    assert row["eip8037_delegation_indicator_state_bytes"] == 0
    assert row["eip8037_delegation_indicator_state_gas"] == 0
    assert row["eip8037_state_bytes_equivalent"] == expected_state_bytes
    assert row["eip8037_state_gas_used"] == expected_state_gas
    assert row["state_gas_used"] == expected_state_gas
    assert row["state_gas_source"] == "xatu_raw_diffs_counterfactual_eip8037"
    assert row["transaction_state_gas_matches_block"]
