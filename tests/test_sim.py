from dataclasses import replace
import unittest

import pandas as pd

from sim import (
    BandwidthConfig,
    ExecutionStateConfig,
    SimulatorConfig,
    SyntheticConfig,
    generate_synthetic_blocks,
    replay,
)


class SyntheticGenerationTest(unittest.TestCase):
    def test_generates_requested_rows_and_columns(self):
        config = SimulatorConfig(synthetic=SyntheticConfig(num_blocks=200, seed=7999))

        blocks = generate_synthetic_blocks(config)

        self.assertEqual(len(blocks), 200)
        for column in [
            "block_number",
            "timestamp",
            "regular_gas_used",
            "state_gas_used",
            "calldata_bytes",
            "bal_bytes",
            "blob_base_fee",
        ]:
            self.assertIn(column, blocks.columns)


class ReplayTest(unittest.TestCase):
    def test_bandwidth_includes_bal_and_state_uses_max_bottleneck(self):
        config = SimulatorConfig(
            execution_state=ExecutionStateConfig(
                target_gas=10,
                limit_gas=30,
                initial_base_fee=1000,
                base_fee_update_denominator=8,
            ),
            bandwidth=BandwidthConfig(
                target_bytes=100,
                limit_bytes=200,
                min_base_fee=1,
                update_fraction=1,
            ),
        )
        blocks = pd.DataFrame(
            [
                {
                    "block_number": 1,
                    "timestamp": 0,
                    "regular_gas_used": 10,
                    "state_gas_used": 20,
                    "calldata_bytes": 100,
                    "bal_bytes": 50,
                    "blob_base_fee": 0,
                }
            ]
        )

        df = replay(blocks, config)

        self.assertEqual(int(df.loc[0, "execution_state_used"]), 20)
        self.assertEqual(int(df.loc[0, "bandwidth_used"]), 150)

    def test_fixed_reserve_floor_can_activate(self):
        config = SimulatorConfig(
            bandwidth=BandwidthConfig(
                target_bytes=100,
                limit_bytes=200,
                min_base_fee=1,
                update_fraction=1,
                reserve_mode="fixed_floor",
                fixed_floor_base_fee=5,
            )
        )
        blocks = pd.DataFrame(
            [
                {
                    "block_number": 1,
                    "timestamp": 0,
                    "regular_gas_used": 1,
                    "state_gas_used": 1,
                    "calldata_bytes": 1,
                    "bal_bytes": 1,
                    "blob_base_fee": 0,
                }
            ]
        )

        df = replay(blocks, config)

        self.assertEqual(int(df.loc[0, "bandwidth_base_fee"]), 5)
        self.assertTrue(bool(df.loc[0, "reserve_activated"]))

    def test_calldata_only_path_changes_bandwidth_usage(self):
        config = SimulatorConfig()
        blocks = generate_synthetic_blocks(
            replace(config, synthetic=SyntheticConfig(num_blocks=20, seed=1))
        )

        with_bal = replay(blocks, config)
        calldata_only = replay(blocks.assign(bal_bytes=0), config)

        self.assertGreater(
            int(with_bal["bandwidth_used"].sum()),
            int(calldata_only["bandwidth_used"].sum()),
        )


if __name__ == "__main__":
    unittest.main()
