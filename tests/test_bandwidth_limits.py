import unittest

from bandwidth_limits.eip7999_metering import (
    BandwidthMeteringConfig,
    compute_bandwidth_usage,
)
from bandwidth_limits.scenarios import (
    GLAMSTERDAM_NO_8279,
    GLAMSTERDAM_PLUS_8279,
)
from bandwidth_limits.worst_case import (
    all_calldata_nonzero,
    best_strategy,
    mixed_calldata_plus_cold_sloads,
    strategies_for,
)


class BandwidthWorstCaseTest(unittest.TestCase):
    def test_no_8279_mixed_beats_or_matches_all_calldata_at_60m(self):
        gas_limit = 60_000_000

        calldata = all_calldata_nonzero(gas_limit, GLAMSTERDAM_NO_8279)
        mixed = mixed_calldata_plus_cold_sloads(gas_limit, GLAMSTERDAM_NO_8279)

        self.assertGreaterEqual(mixed.total_payload_bytes, calldata.total_payload_bytes)

    def test_plus_8279_mixed_does_not_exceed_uniform_floor(self):
        gas_limit = 60_000_000

        calldata = all_calldata_nonzero(gas_limit, GLAMSTERDAM_PLUS_8279)
        mixed = mixed_calldata_plus_cold_sloads(
            gas_limit, GLAMSTERDAM_PLUS_8279
        )
        best = best_strategy(gas_limit, GLAMSTERDAM_PLUS_8279)

        self.assertLessEqual(mixed.total_payload_bytes, calldata.total_payload_bytes)
        self.assertLessEqual(
            abs(best.total_payload_bytes - calldata.total_payload_bytes),
            1,
        )

    def test_no_strategy_exceeds_gas_limit(self):
        for schedule in [GLAMSTERDAM_NO_8279, GLAMSTERDAM_PLUS_8279]:
            for gas_limit in [60_000_000, 100_000_000, 450_000_000]:
                for result in strategies_for(gas_limit, schedule):
                    self.assertLessEqual(result.gas_used, gas_limit)

    def test_total_payload_bytes_is_component_sum(self):
        for schedule in [GLAMSTERDAM_NO_8279, GLAMSTERDAM_PLUS_8279]:
            for result in strategies_for(60_000_000, schedule):
                self.assertEqual(
                    result.total_payload_bytes,
                    result.calldata_bytes
                    + result.bal_bytes
                    + result.tx_access_list_bytes,
                )


class BandwidthMeteringTest(unittest.TestCase):
    def test_eip7999_metering_components(self):
        result = compute_bandwidth_usage(
            calldata_zero_bytes=10,
            calldata_nonzero_bytes=20,
            bal_rlp_bytes=30,
            authorization_tuple_bytes=108,
            blob_versioned_hash_bytes=32,
            config=BandwidthMeteringConfig(safe_bandwidth_bytes=1_000),
        )

        self.assertEqual(result["bandwidth_bytes"], 200)
        self.assertEqual(result["calldata_gas"], 4 * 10 + 16 * 20)
        self.assertEqual(result["bal_gas"], 16 * 30)
        self.assertEqual(result["authorization_tuple_gas"], 64 * 108)
        self.assertEqual(result["blob_versioned_hash_gas"], 64 * 32)
        self.assertEqual(
            result["bandwidth_gas"],
            result["calldata_gas"]
            + result["bal_gas"]
            + result["authorization_tuple_gas"]
            + result["blob_versioned_hash_gas"],
        )
        self.assertEqual(result["bandwidth_gas_limit"], 16 * 1_000)


if __name__ == "__main__":
    unittest.main()
