"""Base-fee update helpers for the simulator."""

from __future__ import annotations


def fake_exponential(factor: int, numerator: int, denominator: int) -> int:
    """Approximate ``factor * exp(numerator / denominator)`` with integers.

    This follows the integer Taylor-series helper shape used by recent Ethereum
    fee-market EIPs. The exact resource constants are intentionally supplied by
    config so this can be validated against the EIP-7999 helper later.
    """

    if factor < 0:
        raise ValueError("factor must be non-negative")
    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    if denominator <= 0:
        raise ValueError("denominator must be positive")

    i = 1
    output = 0
    numerator_accumulator = factor * denominator

    while numerator_accumulator > 0:
        output += numerator_accumulator
        numerator_accumulator = (
            numerator_accumulator * numerator // (denominator * i)
        )
        i += 1

    return output // denominator


def resource_base_fee_from_excess(
    min_base_fee: int,
    excess: int,
    target: int,
    update_fraction: float,
) -> int:
    """Compute a fake-exponential resource fee from target-normalized excess."""

    denominator = max(1, int(round(target * update_fraction)))
    return fake_exponential(min_base_fee, max(0, excess), denominator)


def update_excess(parent_excess: int, used: int, target: int) -> int:
    """Update resource excess for the next block."""

    return max(0, int(parent_excess) + int(used) - int(target))


def update_eip1559_base_fee(
    parent_base_fee: int,
    used: int,
    target: int,
    update_denominator: int = 8,
    min_base_fee: int = 1,
) -> int:
    """EIP-1559-style one-dimensional base-fee update."""

    if target <= 0:
        raise ValueError("target must be positive")
    if update_denominator <= 0:
        raise ValueError("update_denominator must be positive")

    parent_base_fee = max(int(parent_base_fee), int(min_base_fee))
    used = int(used)
    target = int(target)

    if used == target:
        return parent_base_fee

    gas_delta = abs(used - target)
    base_fee_delta = parent_base_fee * gas_delta // target // update_denominator

    if used > target:
        return parent_base_fee + max(base_fee_delta, 1)

    return max(parent_base_fee - base_fee_delta, int(min_base_fee))
