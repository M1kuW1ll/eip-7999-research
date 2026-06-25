import unittest

from basefee import update_eip1559_base_fee


class EIP1559BaseFeeTest(unittest.TestCase):
    def test_increases_linearly_when_above_target(self):
        self.assertEqual(
            update_eip1559_base_fee(
                parent_base_fee=100,
                gas_used=100,
                gas_target=50,
            ),
            112,
        )

    def test_decreases_linearly_when_below_target(self):
        self.assertEqual(
            update_eip1559_base_fee(
                parent_base_fee=100,
                gas_used=0,
                gas_target=50,
            ),
            88,
        )

    def test_increase_is_at_least_one_wei(self):
        self.assertEqual(
            update_eip1559_base_fee(
                parent_base_fee=1,
                gas_used=51,
                gas_target=50,
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
