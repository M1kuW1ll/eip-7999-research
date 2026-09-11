"""Physical-limit, transaction-floor, and state-growth design helpers."""

from __future__ import annotations

import math

import numpy as np

from bandwidth_limits import EMPIRICAL_P90, safe_payload_bytes


SLOT_BUDGET_S = 9.0
EXECUTION_SPEED_GAS_PER_S = 100e6
TRANSFER_GAS_PER_TRANSACTION = 21_000.0
TRANSFER_BYTES_PER_TRANSACTION = 221.0
TRANSFER_GAS_PER_BYTE = (
    TRANSFER_GAS_PER_TRANSACTION / TRANSFER_BYTES_PER_TRANSACTION
)
PROPOSAL_FLOOR_RATE = 64
MAXIMUM_FLOOR_RATE = 96
# Extend the existing 64--96 calibration only with the two newly required
# rates. Lower-limit candidates select the least sufficient tested rate.
CALIBRATED_FLOOR_RATES = (40, 50, *range(PROPOSAL_FLOOR_RATE, MAXIMUM_FLOOR_RATE + 1))
CPSB_REFERENCE = 1_530.0
REFERENCE_SHARED_LIMIT = 150e6
BLOCKS_PER_YEAR = 2_628_000
BYTES_PER_GIB = 1024**3


def physical_capacities(propagation_time_s: float) -> dict[str, float | str]:
    """Return the propagation-fit and execution-time capacity ceilings."""

    payload_bytes = float(
        safe_payload_bytes(propagation_time_s * 1000.0, EMPIRICAL_P90, 1.0)
    )
    execution_capacity = EXECUTION_SPEED_GAS_PER_S * (
        SLOT_BUDGET_S - propagation_time_s
    )
    transfer_capacity = TRANSFER_GAS_PER_BYTE * payload_bytes
    physical_limit = min(execution_capacity, transfer_capacity)
    if np.isclose(execution_capacity, transfer_capacity):
        binding = "balanced"
    elif execution_capacity < transfer_capacity:
        binding = "execution"
    else:
        binding = "transfer payload"
    return {
        "safe_payload_bytes": payload_bytes,
        "execution_capacity_gas": execution_capacity,
        "transfer_capacity_gas": transfer_capacity,
        "maximum_candidate_limit": physical_limit,
        "physical_binding_constraint": binding,
    }


def minimum_sufficient_floor_rate(limit: float, payload_bytes: float) -> int:
    """Return the smallest calibrated integer floor that covers the candidate."""

    required_rate = int(math.ceil(limit / payload_bytes))
    if required_rate > MAXIMUM_FLOOR_RATE:
        raise ValueError(
            f"candidate {limit:g} requires floor rate {required_rate}, above "
            f"the configured maximum of {MAXIMUM_FLOOR_RATE} gas/byte"
        )
    return next(rate for rate in CALIBRATED_FLOOR_RATES if rate >= required_rate)


def cpsb_for_limit(limit: float, matched: bool) -> float:
    """Return fixed or state-growth-matched CPSB for a half-full target."""

    if not matched:
        return CPSB_REFERENCE
    return CPSB_REFERENCE * limit / REFERENCE_SHARED_LIMIT
