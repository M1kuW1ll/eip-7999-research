"""EIP-1559 one-dimensional base-fee updater."""

from __future__ import annotations

BASE_FEE_MAX_CHANGE_DENOMINATOR = 8
MIN_BASE_FEE_PER_GAS = 1


def update_eip1559_base_fee(
    *,
    parent_base_fee: int,
    gas_used: int,
    gas_target: int,
    update_denominator: int = BASE_FEE_MAX_CHANGE_DENOMINATOR,
    min_base_fee: int = MIN_BASE_FEE_PER_GAS,
) -> int:
    """Return the next EIP-1559 base fee.

    This is the linear EIP-1559 update, not the EIP-4844/EIP-7999
    fake-exponential update. It is the rule used by the Glamsterdam-only
    EIP-8037 baseline: EIP-8037 changes the gas-used input to
    ``max(regular_gas, state_gas)``, but does not change the base-fee formula.
    """

    if gas_target <= 0:
        raise ValueError("gas_target must be positive")
    if update_denominator <= 0:
        raise ValueError("update_denominator must be positive")
    if min_base_fee < 0:
        raise ValueError("min_base_fee must be non-negative")
    if parent_base_fee < 0:
        raise ValueError("parent_base_fee must be non-negative")
    if gas_used < 0:
        raise ValueError("gas_used must be non-negative")

    parent_base_fee = max(int(parent_base_fee), int(min_base_fee))
    gas_used = int(gas_used)
    gas_target = int(gas_target)

    if gas_used == gas_target:
        return parent_base_fee

    gas_delta = abs(gas_used - gas_target)
    base_fee_delta = (
        parent_base_fee * gas_delta // gas_target // int(update_denominator)
    )

    if gas_used > gas_target:
        return parent_base_fee + max(base_fee_delta, 1)

    return max(parent_base_fee - base_fee_delta, int(min_base_fee))
