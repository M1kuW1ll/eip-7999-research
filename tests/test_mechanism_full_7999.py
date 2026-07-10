import unittest

from basefee import ResourceFeeConfig, ResourceFeeState, apply_resource_block
from mechanisms import (
    MechanismConfig,
    MechanismStep,
    PassiveBlockUsage,
    initialize_mechanism_states,
    make_full_7999_config,
    replay_full_7999,
    step_full_7999,
)


def block(
    *,
    block_number: int = 1,
    execution_gas_used: int = 0,
    state_gas_used: int = 0,
    bandwidth_gas: int = 0,
    bandwidth_bytes: int = 0,
    blob_base_fee_per_gas: int | None = 12,
) -> PassiveBlockUsage:
    return PassiveBlockUsage(
        block_number=block_number,
        timestamp=None,
        execution_gas_used=execution_gas_used,
        state_gas_used=state_gas_used,
        bandwidth_gas=bandwidth_gas,
        bandwidth_bytes=bandwidth_bytes,
        blob_base_fee_per_gas=blob_base_fee_per_gas,
    )


class Full7999Test(unittest.TestCase):
    def test_initialize_mechanism_states_uses_configured_warm_start(self):
        config = make_full_7999_config(
            execution_gas_limit=100,
            bandwidth_gas_limit=40,
            state_gas_target=75,
            initial_execution_base_fee=101,
            initial_bandwidth_base_fee=202,
            initial_state_base_fee=303,
        )

        states = initialize_mechanism_states(config)

        self.assertEqual(
            {name: state.base_fee for name, state in states.items()},
            {"execution": 101, "bandwidth": 202, "state": 303},
        )
        self.assertTrue(all(state.excess_gas > 0 for state in states.values()))

    def test_one_block_steps_preserve_passive_replay_results_and_timing(self):
        execution = ResourceFeeConfig(
            name="execution",
            gas_limit=100,
            gas_target=50,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        bandwidth = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=40,
            gas_target=10,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        state = ResourceFeeConfig(
            name="state",
            gas_limit=None,
            gas_target=75,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        config = MechanismConfig(
            name="full_7999",
            resources={
                "execution": execution,
                "bandwidth": bandwidth,
                "state": state,
            },
            initial_base_fee_by_resource={
                "execution": 1,
                "bandwidth": 1,
                "state": 1,
            },
        )
        blocks = [
            block(
                block_number=1,
                execution_gas_used=100,
                bandwidth_gas=40,
                state_gas_used=150,
            ),
            block(
                block_number=2,
                execution_gas_used=50,
                bandwidth_gas=10,
                state_gas_used=75,
            ),
        ]

        replay_results = replay_full_7999(blocks, config)
        states = initialize_mechanism_states(config)
        stepped_results = []
        steps = []
        for usage in blocks:
            transition = step_full_7999(
                block=usage,
                config=config,
                parent_states=states,
            )
            self.assertIsInstance(transition, MechanismStep)
            steps.append(transition)
            stepped_results.append(transition.result)
            states = dict(transition.next_states)

        self.assertEqual(stepped_results, replay_results)
        self.assertEqual(
            steps[0].result.base_fee_by_resource,
            {"execution": 1, "bandwidth": 1, "state": 1},
        )
        self.assertEqual(
            steps[1].result.base_fee_by_resource,
            {
                name: fee_state.base_fee
                for name, fee_state in steps[0].next_states.items()
            },
        )
        self.assertTrue(
            all(
                steps[0].next_states[name].base_fee
                > steps[0].result.base_fee_by_resource[name]
                for name in config.resources
            )
        )

    def test_step_reports_reserve_status_from_parent_fee(self):
        config = make_full_7999_config(
            execution_gas_limit=100,
            bandwidth_gas_limit=40,
            state_gas_target=75,
            initial_bandwidth_base_fee=1,
        )
        states = initialize_mechanism_states(config)

        active = step_full_7999(
            block=block(
                execution_gas_used=1,
                bandwidth_gas=20,
                state_gas_used=1,
                blob_base_fee_per_gas=13,
            ),
            config=config,
            parent_states=states,
        )
        boundary = step_full_7999(
            block=block(
                execution_gas_used=1,
                bandwidth_gas=20,
                state_gas_used=1,
                blob_base_fee_per_gas=12,
            ),
            config=config,
            parent_states=states,
        )

        self.assertEqual(
            active.reserve_active_by_resource,
            {"execution": False, "bandwidth": True, "state": False},
        )
        self.assertFalse(boundary.reserve_active_by_resource["bandwidth"])
        self.assertEqual(active.result.base_fee_by_resource["bandwidth"], 1)
        self.assertGreater(active.next_states["bandwidth"].excess_gas, 0)

    def test_full_7999_uses_three_separate_resources(self):
        config = make_full_7999_config(
            execution_gas_limit=60_000_000,
            bandwidth_gas_limit=60_000_000,
            state_gas_target=75_000_000,
        )

        result = replay_full_7999(
            [
                block(
                    execution_gas_used=20_000_000,
                    state_gas_used=90_000_000,
                    bandwidth_gas=5_000_000,
                    bandwidth_bytes=312_500,
                )
            ],
            config,
        )[0]

        self.assertEqual(
            result.gas_used_by_resource,
            {
                "execution": 20_000_000,
                "bandwidth": 5_000_000,
                "state": 90_000_000,
            },
        )
        self.assertTrue(result.valid)
        self.assertIsNone(result.gas_limit_by_resource["state"])
        self.assertIsNone(result.pct_limit_by_resource["state"])

    def test_state_has_no_limit_but_execution_and_bandwidth_do(self):
        config = make_full_7999_config(
            execution_gas_limit=60_000_000,
            bandwidth_gas_limit=60_000_000,
            state_gas_target=75_000_000,
        )

        state_only = replay_full_7999(
            [block(execution_gas_used=10, state_gas_used=1_000_000_000, bandwidth_gas=10)],
            config,
        )[0]
        self.assertTrue(state_only.valid)

        limited = replay_full_7999(
            [
                block(
                    execution_gas_used=60_000_001,
                    state_gas_used=1_000_000_000,
                    bandwidth_gas=60_000_001,
                )
            ],
            config,
        )[0]
        self.assertFalse(limited.valid)
        self.assertIn("execution_limit_exceeded", limited.invalid_reasons)
        self.assertIn("bandwidth_limit_exceeded", limited.invalid_reasons)

    def test_limited_resources_update_capped_but_state_uncapped(self):
        execution = ResourceFeeConfig(
            name="execution",
            gas_limit=100,
            gas_target=50,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        bandwidth = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=40,
            gas_target=10,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        state = ResourceFeeConfig(
            name="state",
            gas_limit=None,
            gas_target=75,
            min_base_fee=1,
            gas_normalization_factor=1_000,
            update_fraction=100,
        )
        config = MechanismConfig(
            name="full_7999",
            resources={
                "execution": execution,
                "bandwidth": bandwidth,
                "state": state,
            },
            initial_base_fee_by_resource={
                "execution": 1,
                "bandwidth": 1,
                "state": 1,
            },
        )

        results = replay_full_7999(
            [
                block(
                    block_number=1,
                    execution_gas_used=300,
                    state_gas_used=225,
                    bandwidth_gas=100,
                ),
                block(
                    block_number=2,
                    execution_gas_used=50,
                    state_gas_used=75,
                    bandwidth_gas=10,
                ),
            ],
            config,
        )

        expected_execution = apply_resource_block(
            parent=ResourceFeeState(name="execution"),
            gas_used=execution.gas_limit,
            config=execution,
        )
        expected_bandwidth = apply_resource_block(
            parent=ResourceFeeState(name="bandwidth"),
            gas_used=bandwidth.gas_limit,
            config=bandwidth,
        )
        expected_state = apply_resource_block(
            parent=ResourceFeeState(name="state"),
            gas_used=225,
            config=state,
        )

        self.assertEqual(
            results[1].base_fee_by_resource["execution"],
            expected_execution.base_fee,
        )
        self.assertEqual(
            results[1].base_fee_by_resource["bandwidth"],
            expected_bandwidth.base_fee,
        )
        self.assertEqual(
            results[1].base_fee_by_resource["state"],
            expected_state.base_fee,
        )
        self.assertEqual(results[1].excess_gas_by_resource["state"], 2_000)

    def test_bandwidth_reserve_requires_blob_base_fee(self):
        config = make_full_7999_config(
            execution_gas_limit=60_000_000,
            bandwidth_gas_limit=60_000_000,
            state_gas_target=75_000_000,
        )

        with self.assertRaisesRegex(
            ValueError,
            "blob_base_fee_per_gas is required",
        ):
            replay_full_7999(
                [
                    block(
                        execution_gas_used=1,
                        state_gas_used=1,
                        bandwidth_gas=1,
                        blob_base_fee_per_gas=None,
                    )
                ],
                config,
            )

        with self.assertRaisesRegex(
            ValueError,
            "blob_base_fee_per_gas is required",
        ):
            step_full_7999(
                block=block(
                    execution_gas_used=1,
                    state_gas_used=1,
                    bandwidth_gas=1,
                    blob_base_fee_per_gas=None,
                ),
                config=config,
                parent_states=initialize_mechanism_states(config),
            )

    def test_bandwidth_reserve_path_does_not_hard_clamp_base_fee(self):
        config = make_full_7999_config(
            execution_gas_limit=60_000_000,
            bandwidth_gas_limit=60_000_000,
            state_gas_target=75_000_000,
            initial_bandwidth_base_fee=1,
        )

        results = replay_full_7999(
            [
                block(
                    block_number=1,
                    execution_gas_used=1,
                    state_gas_used=1,
                    bandwidth_gas=20_000_000,
                    bandwidth_bytes=1,
                    blob_base_fee_per_gas=25,
                ),
                block(
                    block_number=2,
                    execution_gas_used=1,
                    state_gas_used=1,
                    bandwidth_gas=1,
                    bandwidth_bytes=1,
                    blob_base_fee_per_gas=25,
                ),
            ],
            config,
        )

        self.assertGreater(results[1].excess_gas_by_resource["bandwidth"], 0)
        self.assertLess(results[1].base_fee_by_resource["bandwidth"], 3)

    def test_full_7999_warm_starts_all_resource_excesses(self):
        config = make_full_7999_config(
            execution_gas_limit=60_000_000,
            bandwidth_gas_limit=60_000_000,
            state_gas_target=75_000_000,
            initial_execution_base_fee=75_000_000,
            initial_bandwidth_base_fee=75_000_000,
            initial_state_base_fee=75_000_000,
        )

        result = replay_full_7999(
            [
                block(
                    execution_gas_used=1,
                    state_gas_used=1,
                    bandwidth_gas=1,
                    bandwidth_bytes=1,
                    blob_base_fee_per_gas=1,
                )
            ],
            config,
        )[0]

        for resource in ["execution", "bandwidth", "state"]:
            self.assertEqual(result.base_fee_by_resource[resource], 75_000_000)
            self.assertGreater(result.excess_gas_by_resource[resource], 0)


if __name__ == "__main__":
    unittest.main()
