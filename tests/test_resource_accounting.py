import unittest

from resources import (
    BandwidthCounts,
    BlockResourceCounts,
    ResourceLimit,
    ResourceUsage,
    StateCreationCounts,
    account_execution_state_shared,
    account_resource,
    account_resources,
    compute_bandwidth_usage,
    compute_block_resource_usage,
    compute_calldata_gas,
    compute_state_bytes_equivalent,
    compute_state_gas,
    shared_resource_used,
)


class ResourceAccountingTest(unittest.TestCase):
    def test_shared_resource_uses_max_by_default(self):
        self.assertEqual(shared_resource_used(30, 50), 50)

    def test_shared_resource_can_sum(self):
        self.assertEqual(shared_resource_used(30, 50, mode="sum"), 80)

    def test_account_execution_state_shared(self):
        result = account_execution_state_shared(
            regular_gas_used=30,
            state_gas_used=50,
            target_gas=40,
            limit_gas=100,
        )

        self.assertEqual(result.name, "execution_state")
        self.assertEqual(result.used, 50)
        self.assertEqual(result.excess, 10)
        self.assertFalse(result.limit_hit)
        self.assertEqual(result.target_ratio, 1.25)

    def test_account_resource_limit_hit(self):
        result = account_resource(
            ResourceUsage(name="bandwidth", used=120),
            ResourceLimit(name="bandwidth", target=50, limit=100),
        )

        self.assertEqual(result.excess, 70)
        self.assertTrue(result.limit_hit)
        self.assertEqual(result.limit_ratio, 1.2)

    def test_account_resources_requires_matching_limits(self):
        results = account_resources(
            usages=[
                ResourceUsage(name="execution", used=10),
                ResourceUsage(name="state", used=20),
            ],
            limits={
                "execution": ResourceLimit(name="execution", target=10, limit=20),
                "state": ResourceLimit(name="state", target=10, limit=20),
            },
        )

        self.assertEqual(set(results), {"execution", "state"})
        self.assertEqual(results["state"].used, 20)
        self.assertTrue(results["state"].limit_hit)


class BlockResourceUsageTest(unittest.TestCase):
    def test_storage_slot_state_gas(self):
        counts = StateCreationCounts(new_storage_slots=1)

        self.assertEqual(compute_state_gas(counts, cpsb=1530), 64 * 1530)
        self.assertEqual(compute_state_bytes_equivalent(counts), 64)

    def test_new_account_state_gas(self):
        counts = StateCreationCounts(new_accounts=1)

        self.assertEqual(compute_state_gas(counts, cpsb=1530), 120 * 1530)
        self.assertEqual(compute_state_bytes_equivalent(counts), 120)

    def test_code_bytes_state_gas(self):
        counts = StateCreationCounts(code_bytes=10)

        self.assertEqual(compute_state_gas(counts, cpsb=1530), 15_300)
        self.assertEqual(compute_state_bytes_equivalent(counts), 10)

    def test_new_delegation_indicator_state_gas(self):
        counts = StateCreationCounts(new_delegation_indicators=1)

        self.assertEqual(compute_state_gas(counts, cpsb=1530), 23 * 1530)
        self.assertEqual(compute_state_bytes_equivalent(counts), 23)

    def test_calldata_gas(self):
        self.assertEqual(
            compute_calldata_gas(
                calldata_zero_bytes=10,
                calldata_nonzero_bytes=20,
            ),
            10 * 4 + 20 * 16,
        )

    def test_bandwidth_usage(self):
        result = compute_bandwidth_usage(
            BandwidthCounts(
                calldata_zero_bytes=10,
                calldata_nonzero_bytes=20,
                bal_rlp_bytes=30,
                authorization_tuple_bytes=108,
                blob_versioned_hash_bytes=32,
            )
        )

        self.assertEqual(result["calldata_gas"], 360)
        self.assertEqual(result["bal_gas"], 480)
        self.assertEqual(result["authorization_tuple_gas"], 108 * 64)
        self.assertEqual(result["blob_versioned_hash_gas"], 32 * 64)
        self.assertEqual(result["bandwidth_gas"], 360 + 480 + 108 * 64 + 32 * 64)
        self.assertEqual(result["bandwidth_bytes"], 200)

    def test_block_resource_usage_wrapper(self):
        result = compute_block_resource_usage(
            BlockResourceCounts(
                block_number=123,
                execution_gas_used=1_000_000,
                state=StateCreationCounts(
                    new_storage_slots=1,
                    new_accounts=1,
                    code_bytes=10,
                    new_delegation_indicators=1,
                ),
                bandwidth=BandwidthCounts(
                    calldata_zero_bytes=10,
                    calldata_nonzero_bytes=20,
                    bal_rlp_bytes=30,
                    authorization_tuple_bytes=108,
                    blob_versioned_hash_bytes=32,
                ),
            ),
            cpsb=1530,
        )

        self.assertEqual(result.block_number, 123)
        self.assertEqual(result.execution_gas_used, 1_000_000)
        self.assertEqual(result.state_bytes_created_equivalent, 64 + 120 + 10 + 23)
        self.assertEqual(result.state_gas_used, (64 + 120 + 10 + 23) * 1530)
        self.assertEqual(result.calldata_bytes, 30)
        self.assertEqual(result.calldata_gas, 360)
        self.assertEqual(result.bal_gas, 480)
        self.assertEqual(result.authorization_tuple_gas, 108 * 64)
        self.assertEqual(result.blob_versioned_hash_gas, 32 * 64)
        self.assertEqual(result.bandwidth_bytes, 200)
        self.assertEqual(result.bandwidth_gas, 360 + 480 + 108 * 64 + 32 * 64)


if __name__ == "__main__":
    unittest.main()
