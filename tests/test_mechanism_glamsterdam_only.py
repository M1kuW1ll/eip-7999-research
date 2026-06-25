import unittest

from basefee import ResourceFeeConfig, update_eip1559_base_fee
from mechanisms import (
    MechanismConfig,
    PassiveBlockUsage,
    make_glamsterdam_only_config,
    replay_glamsterdam_only,
)


def block(
    *,
    block_number: int = 1,
    execution_gas_used: int = 0,
    state_gas_used: int = 0,
    bandwidth_gas: int = 0,
) -> PassiveBlockUsage:
    return PassiveBlockUsage(
        block_number=block_number,
        timestamp=None,
        execution_gas_used=execution_gas_used,
        state_gas_used=state_gas_used,
        bandwidth_gas=bandwidth_gas,
        bandwidth_bytes=0,
    )


class GlamsterdamOnlyMechanismTest(unittest.TestCase):
    def test_glamsterdam_only_uses_max_execution_state(self):
        config = make_glamsterdam_only_config(
            execution_state_gas_limit=100_000_000,
        )

        results = replay_glamsterdam_only(
            [
                block(
                    execution_gas_used=40_000_000,
                    state_gas_used=75_000_000,
                )
            ],
            config,
        )

        self.assertEqual(
            results[0].gas_used_by_resource["execution_state"],
            75_000_000,
        )
        self.assertTrue(results[0].valid)

    def test_glamsterdam_only_invalid_on_execution_state_limit(self):
        config = make_glamsterdam_only_config(
            execution_state_gas_limit=60_000_000,
        )

        result = replay_glamsterdam_only(
            [
                block(
                    execution_gas_used=40_000_000,
                    state_gas_used=75_000_000,
                )
            ],
            config,
        )[0]

        self.assertFalse(result.valid)
        self.assertIn("execution_state_limit_exceeded", result.invalid_reasons)

    def test_over_limit_block_updates_next_fee_as_full_block(self):
        resource = ResourceFeeConfig(
            name="execution_state",
            gas_limit=100,
            gas_target=50,
            min_base_fee=1,
        )
        config = MechanismConfig(
            name="glamsterdam_only",
            resources={"execution_state": resource},
            initial_base_fee_by_resource={"execution_state": 100},
        )

        results = replay_glamsterdam_only(
            [
                block(block_number=1, execution_gas_used=300, state_gas_used=0),
                block(block_number=2, execution_gas_used=50, state_gas_used=0),
            ],
            config,
        )

        expected_second_base_fee = update_eip1559_base_fee(
            parent_base_fee=100,
            gas_used=resource.gas_limit,
            gas_target=resource.gas_target,
            min_base_fee=resource.min_base_fee,
        )

        self.assertFalse(results[0].valid)
        self.assertEqual(
            results[0].gas_used_by_resource["execution_state"],
            300,
        )
        self.assertEqual(
            results[1].base_fee_by_resource["execution_state"],
            expected_second_base_fee,
        )

    def test_current_block_reports_parent_base_fee(self):
        resource = ResourceFeeConfig(
            name="execution_state",
            gas_limit=100,
            gas_target=10,
            min_base_fee=10,
        )
        config = MechanismConfig(
            name="glamsterdam_only",
            resources={"execution_state": resource},
            initial_base_fee_by_resource={"execution_state": 10},
        )

        results = replay_glamsterdam_only(
            [
                block(block_number=1, execution_gas_used=30, state_gas_used=0),
                block(block_number=2, execution_gas_used=10, state_gas_used=0),
            ],
            config,
        )

        expected_second_base_fee = update_eip1559_base_fee(
            parent_base_fee=10,
            gas_used=30,
            gas_target=10,
            min_base_fee=resource.min_base_fee,
        )

        self.assertEqual(results[0].base_fee_by_resource["execution_state"], 10)
        self.assertEqual(
            results[1].base_fee_by_resource["execution_state"],
            expected_second_base_fee,
        )
        self.assertEqual(
            results[1].excess_gas_by_resource["execution_state"],
            0,
        )

    def test_eip1559_base_fee_can_decay_below_initial_seed(self):
        resource = ResourceFeeConfig(
            name="execution_state",
            gas_limit=100,
            gas_target=50,
            min_base_fee=1,
        )
        config = MechanismConfig(
            name="glamsterdam_only",
            resources={"execution_state": resource},
            initial_base_fee_by_resource={"execution_state": 100},
        )

        results = replay_glamsterdam_only(
            [
                block(block_number=1, execution_gas_used=0, state_gas_used=0),
                block(block_number=2, execution_gas_used=0, state_gas_used=0),
            ],
            config,
        )

        self.assertEqual(results[0].base_fee_by_resource["execution_state"], 100)
        self.assertLess(results[1].base_fee_by_resource["execution_state"], 100)
        self.assertEqual(results[1].excess_gas_by_resource["execution_state"], 0)


if __name__ == "__main__":
    unittest.main()
