import unittest

from basefee import (
    ResourceFeeConfig,
    ResourceFeeState,
    apply_resource_block,
    update_eip1559_base_fee,
)
from mechanisms import (
    MechanismConfig,
    PassiveBlockUsage,
    make_mechanism_A_config,
    replay_bandwidth_7999_state_8037,
)


def block(
    *,
    block_number: int = 1,
    execution_gas_used: int = 0,
    state_gas_used: int = 0,
    bandwidth_gas: int = 0,
    bandwidth_bytes: int = 0,
) -> PassiveBlockUsage:
    return PassiveBlockUsage(
        block_number=block_number,
        timestamp=None,
        execution_gas_used=execution_gas_used,
        state_gas_used=state_gas_used,
        bandwidth_gas=bandwidth_gas,
        bandwidth_bytes=bandwidth_bytes,
    )


class MechanismATest(unittest.TestCase):
    def test_mechanism_A_uses_same_max_plus_bandwidth(self):
        config = make_mechanism_A_config(
            execution_state_gas_limit=100_000_000,
            bandwidth_gas_limit=40_000_000,
        )

        result = replay_bandwidth_7999_state_8037(
            [
                block(
                    execution_gas_used=40_000_000,
                    state_gas_used=75_000_000,
                    bandwidth_gas=12_000_000,
                    bandwidth_bytes=750_000,
                )
            ],
            config,
        )[0]

        self.assertEqual(
            result.gas_used_by_resource["execution_state"],
            75_000_000,
        )
        self.assertEqual(result.gas_used_by_resource["bandwidth"], 12_000_000)
        self.assertEqual(set(result.gas_used_by_resource), {"execution_state", "bandwidth"})
        self.assertTrue(result.valid)

    def test_mechanism_A_invalid_on_bandwidth(self):
        config = make_mechanism_A_config(
            execution_state_gas_limit=100_000_000,
            bandwidth_gas_limit=40_000_000,
        )

        result = replay_bandwidth_7999_state_8037(
            [
                block(
                    execution_gas_used=40_000_000,
                    state_gas_used=10_000_000,
                    bandwidth_gas=41_000_000,
                )
            ],
            config,
        )[0]

        self.assertFalse(result.valid)
        self.assertIn("bandwidth_limit_exceeded", result.invalid_reasons)

    def test_mechanism_A_invalid_on_execution_state(self):
        config = make_mechanism_A_config(
            execution_state_gas_limit=60_000_000,
            bandwidth_gas_limit=40_000_000,
        )

        result = replay_bandwidth_7999_state_8037(
            [
                block(
                    execution_gas_used=40_000_000,
                    state_gas_used=75_000_000,
                    bandwidth_gas=12_000_000,
                )
            ],
            config,
        )[0]

        self.assertFalse(result.valid)
        self.assertIn("execution_state_limit_exceeded", result.invalid_reasons)

    def test_over_limit_resources_update_next_fee_with_capped_inputs(self):
        execution_state = ResourceFeeConfig(
            name="execution_state",
            gas_limit=100,
            gas_target=50,
            min_base_fee=100,
        )
        bandwidth = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=40,
            gas_target=10,
            min_base_fee=1,
        )
        config = MechanismConfig(
            name="bandwidth_7999_state_8037",
            resources={
                "execution_state": execution_state,
                "bandwidth": bandwidth,
            },
            initial_base_fee_by_resource={
                "execution_state": 100,
                "bandwidth": 1,
            },
        )

        results = replay_bandwidth_7999_state_8037(
            [
                block(
                    block_number=1,
                    execution_gas_used=300,
                    state_gas_used=0,
                    bandwidth_gas=100,
                ),
                block(
                    block_number=2,
                    execution_gas_used=50,
                    state_gas_used=0,
                    bandwidth_gas=10,
                ),
            ],
            config,
        )

        self.assertFalse(results[0].valid)
        self.assertIn("execution_state_limit_exceeded", results[0].invalid_reasons)
        self.assertIn("bandwidth_limit_exceeded", results[0].invalid_reasons)
        self.assertEqual(
            results[0].gas_used_by_resource["execution_state"],
            300,
        )
        self.assertEqual(results[0].gas_used_by_resource["bandwidth"], 100)
        self.assertEqual(results[0].base_fee_by_resource["execution_state"], 100)
        self.assertEqual(results[0].base_fee_by_resource["bandwidth"], 1)

        expected_execution_base_fee = update_eip1559_base_fee(
            parent_base_fee=100,
            gas_used=execution_state.gas_limit,
            gas_target=execution_state.gas_target,
            min_base_fee=execution_state.min_base_fee,
        )
        expected_bandwidth_base_fee = apply_resource_block(
            parent=ResourceFeeState(name="bandwidth", base_fee=1),
            gas_used=bandwidth.gas_limit,
            config=bandwidth,
        ).base_fee

        self.assertEqual(
            results[1].base_fee_by_resource["execution_state"],
            expected_execution_base_fee,
        )
        self.assertEqual(
            results[1].base_fee_by_resource["bandwidth"],
            expected_bandwidth_base_fee,
        )
        self.assertEqual(results[1].excess_gas_by_resource["execution_state"], 0)


if __name__ == "__main__":
    unittest.main()
