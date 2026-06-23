import unittest

from basefee import (
    BASE_FEE_UPDATE_FRACTION,
    GAS_NORMALIZATION_FACTOR,
    ResourceFeeConfig,
    ResourceFeeState,
    apply_resource_block,
    apply_vector_block,
    compute_base_fee,
    fake_exponential,
    update_normalized_excess_gas,
)


class EIP7999NormalizedBaseFeeTest(unittest.TestCase):
    def test_default_update_fraction_matches_eip7999_constant(self):
        self.assertEqual(GAS_NORMALIZATION_FACTOR, 10**9)
        self.assertEqual(BASE_FEE_UPDATE_FRACTION, 4_245_093_508)

    def test_fake_exponential_returns_factor_at_zero_excess(self):
        self.assertEqual(fake_exponential(7, 0, 100), 7)

    def test_normalized_excess_adds_when_above_target(self):
        cfg = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=40_000_000,
            gas_target=10_000_000,
        )

        excess = update_normalized_excess_gas(
            parent_excess_gas=0,
            gas_used=20_000_000,
            config=cfg,
        )

        self.assertEqual(excess, 250_000_000)

    def test_normalized_excess_subtracts_when_below_target(self):
        cfg = ResourceFeeConfig(
            name="state",
            gas_limit=150_000_000,
            gas_target=75_000_000,
        )

        excess = update_normalized_excess_gas(
            parent_excess_gas=500_000_000,
            gas_used=0,
            config=cfg,
        )

        self.assertEqual(excess, 0)

    def test_same_fractional_overuse_same_normalized_delta(self):
        execution = ResourceFeeConfig(
            name="execution",
            gas_limit=60_000_000,
            gas_target=30_000_000,
        )
        bandwidth = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=40_000_000,
            gas_target=20_000_000,
        )

        execution_excess = update_normalized_excess_gas(
            parent_excess_gas=0,
            gas_used=45_000_000,
            config=execution,
        )
        bandwidth_excess = update_normalized_excess_gas(
            parent_excess_gas=0,
            gas_used=30_000_000,
            config=bandwidth,
        )

        self.assertEqual(execution_excess, bandwidth_excess)
        self.assertEqual(execution_excess, 250_000_000)

    def test_normalized_excess_floors_at_zero(self):
        cfg = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=100,
            gas_target=10,
            gas_normalization_factor=1_000,
        )

        self.assertEqual(
            update_normalized_excess_gas(
                parent_excess_gas=5,
                gas_used=0,
                config=cfg,
            ),
            0,
        )

    def test_base_fee_increases_with_excess(self):
        config = ResourceFeeConfig(
            name="bandwidth",
            gas_limit=20,
            gas_target=10,
            min_base_fee=1,
            update_fraction=100,
        )

        base = compute_base_fee(excess_gas=0, config=config)
        high = compute_base_fee(excess_gas=300, config=config)

        self.assertGreater(high, base)

    def test_apply_resource_block_returns_next_state(self):
        config = ResourceFeeConfig(
            name="execution_state",
            gas_limit=100,
            gas_target=10,
            min_base_fee=1,
            update_fraction=100,
            gas_normalization_factor=1_000,
        )
        result = apply_resource_block(
            parent=ResourceFeeState(name="execution_state", excess_gas=0, base_fee=1),
            gas_used=30,
            config=config,
        )

        self.assertEqual(result.name, "execution_state")
        self.assertEqual(result.excess_gas, 200)
        self.assertEqual(
            result.base_fee,
            compute_base_fee(excess_gas=200, config=config),
        )

    def test_apply_vector_block_updates_resources_independently(self):
        configs = {
            "execution_state": ResourceFeeConfig(
                name="execution_state",
                gas_limit=100,
                gas_target=10,
                min_base_fee=1,
                update_fraction=100,
                gas_normalization_factor=1_000,
            ),
            "bandwidth": ResourceFeeConfig(
                name="bandwidth",
                gas_limit=100,
                gas_target=20,
                min_base_fee=1,
                update_fraction=100,
                gas_normalization_factor=1_000,
            ),
        }
        parent_states = {
            "execution_state": ResourceFeeState(name="execution_state"),
            "bandwidth": ResourceFeeState(name="bandwidth"),
        }
        gas_used = {
            "execution_state": 30,
            "bandwidth": 10,
        }

        result = apply_vector_block(
            parent_states=parent_states,
            gas_used_by_resource=gas_used,
            configs=configs,
        )

        self.assertEqual(result["execution_state"].excess_gas, 200)
        self.assertEqual(result["bandwidth"].excess_gas, 0)
        self.assertEqual(set(result), {"execution_state", "bandwidth"})

    def test_vector_missing_parent_state_raises(self):
        with self.assertRaises(KeyError):
            apply_vector_block(
                parent_states={},
                gas_used_by_resource={"bandwidth": 1},
                configs={
                    "bandwidth": ResourceFeeConfig(
                        "bandwidth",
                        gas_target=10,
                        gas_limit=20,
                    )
                },
            )

    def test_invalid_target_raises(self):
        with self.assertRaises(ValueError):
            ResourceFeeConfig(
                name="bandwidth",
                gas_limit=10,
                gas_target=20,
            )

    def test_negative_gas_used_raises(self):
        with self.assertRaises(ValueError):
            update_normalized_excess_gas(
                parent_excess_gas=0,
                gas_used=-1,
                config=ResourceFeeConfig(
                    name="bandwidth",
                    gas_limit=10,
                    gas_target=5,
                ),
            )

    def test_gas_used_above_limit_raises(self):
        with self.assertRaisesRegex(ValueError, "gas_used must be <= gas_limit"):
            apply_resource_block(
                parent=ResourceFeeState(name="bandwidth"),
                gas_used=21,
                config=ResourceFeeConfig(
                    name="bandwidth",
                    gas_limit=20,
                    gas_target=10,
                ),
            )


if __name__ == "__main__":
    unittest.main()
