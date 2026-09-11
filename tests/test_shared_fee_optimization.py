import numpy as np

from shared_fee.optimization import (
    CPSB_REFERENCE,
    TRANSFER_GAS_PER_BYTE,
    minimum_sufficient_floor_rate,
    cpsb_for_limit,
    physical_capacities,
)


def test_minimum_sufficient_floor_rate_uses_the_calibrated_grid():
    assert minimum_sufficient_floor_rate(300_000_000, 5_000_000) == 64
    assert minimum_sufficient_floor_rate(200_000_000, 5_000_000) == 40
    assert minimum_sufficient_floor_rate(250_000_000, 5_000_000) == 50
    assert minimum_sufficient_floor_rate(400_000_000, 5_619_286) == 72
    assert minimum_sufficient_floor_rate(500_000_000, 5_619_286) == 89


def test_longer_propagation_budgets_support_sub_64_floor_rates():
    for propagation, expected_rate in [(4.5, 50), (5.0, 40)]:
        capacity = physical_capacities(propagation)
        limit = capacity["maximum_candidate_limit"]
        payload = capacity["safe_payload_bytes"]
        rate = minimum_sufficient_floor_rate(limit, payload)
        assert rate == expected_rate
        assert rate * payload >= limit
        assert (rate - 1) * payload < limit


def test_state_growth_matched_cpsb_scales_with_shared_limit():
    assert cpsb_for_limit(150_000_000, True) == CPSB_REFERENCE
    assert cpsb_for_limit(400_000_000, True) == 4_080
    assert cpsb_for_limit(500_000_000, True) == 5_100
    assert cpsb_for_limit(500_000_000, False) == CPSB_REFERENCE


def test_candidate_physical_limit_respects_execution_and_transfer_payload():
    three_seconds = physical_capacities(3.0)
    assert three_seconds["physical_binding_constraint"] == "transfer payload"
    assert np.isclose(
        three_seconds["maximum_candidate_limit"],
        TRANSFER_GAS_PER_BYTE * three_seconds["safe_payload_bytes"],
    )
    assert TRANSFER_GAS_PER_BYTE == 21_000 / 221
    assert minimum_sufficient_floor_rate(
        three_seconds["maximum_candidate_limit"],
        three_seconds["safe_payload_bytes"],
    ) == 96
    assert (
        three_seconds["maximum_candidate_limit"]
        < 96 * three_seconds["safe_payload_bytes"]
    )
    four_seconds = physical_capacities(4.0)
    assert four_seconds["physical_binding_constraint"] == "execution"
    assert four_seconds["maximum_candidate_limit"] == 500_000_000
