import unittest
from dataclasses import replace

from state_limits import (
    BRIEF_100GIB_CPSB1174,
    CURRENT_EIP8037_120GIB_CPSB1530,
    derive_state_limit,
)


class StateLimitTest(unittest.TestCase):
    def test_current_eip8037_profile_limit(self):
        result = derive_state_limit(CURRENT_EIP8037_120GIB_CPSB1530)

        self.assertAlmostEqual(result.target_bytes_per_block, 49_029, delta=1)
        self.assertAlmostEqual(result.state_gas_target, 75_014_840, delta=1)
        self.assertAlmostEqual(result.state_gas_limit, 150_029_680, delta=2)

    def test_brief_profile_limit(self):
        result = derive_state_limit(BRIEF_100GIB_CPSB1174)

        self.assertAlmostEqual(result.target_bytes_per_block, 40_858, delta=1)
        self.assertEqual(result.state_gas_target, 47_967_005)
        self.assertEqual(result.state_gas_limit, 95_934_010)

    def test_limit_target_ratio_changes_only_limit(self):
        profile_2x = BRIEF_100GIB_CPSB1174
        profile_3x = replace(profile_2x, limit_target_ratio=3)

        result_2x = derive_state_limit(profile_2x)
        result_3x = derive_state_limit(profile_3x)

        self.assertEqual(result_2x.target_bytes_per_block, result_3x.target_bytes_per_block)
        self.assertEqual(result_2x.state_gas_target, result_3x.state_gas_target)
        self.assertEqual(result_3x.state_gas_limit, result_2x.state_gas_target * 3)


if __name__ == "__main__":
    unittest.main()
