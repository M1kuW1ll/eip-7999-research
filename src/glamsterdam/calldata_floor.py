"""Transaction-level calldata/access-list gas accounting for Glamsterdam."""

from __future__ import annotations

from dataclasses import dataclass

TX_BASE_GAS = 21_000
STANDARD_TOKEN_COST = 4
CURRENT_TOTAL_COST_FLOOR_PER_TOKEN_7623 = 10
GLAMSTERDAM_TOTAL_COST_FLOOR_PER_TOKEN_7976 = 16

ACCESS_LIST_ADDRESS_BYTES = 20
ACCESS_LIST_STORAGE_KEY_BYTES = 32
ACCESS_LIST_ADDRESS_COST_2930 = 2_400
ACCESS_LIST_STORAGE_KEY_COST_2930 = 1_900
ACCESS_LIST_DATA_GAS_PER_BYTE_7981 = 64

HISTORICAL_STORAGE_SET_GAS = 20_000
HISTORICAL_NEW_ACCOUNT_GAS = 25_000
HISTORICAL_CODE_DEPOSIT_GAS_PER_BYTE = 200
HISTORICAL_AUTH_BASE_GAS = 12_500


@dataclass(frozen=True)
class GlamsterdamTxGasResult:
    receipt_gas_used: int
    receipt_body_gas: int
    calldata_zero_bytes: int
    calldata_nonzero_bytes: int
    calldata_bytes: int
    calldata_tokens: int
    standard_calldata_gas: int
    current_7623_floor_gas: int
    glamsterdam_7976_floor_gas: int
    access_list_address_count: int
    access_list_storage_key_count: int
    access_list_bytes: int
    access_list_cost_2930: int
    access_list_data_cost_7981: int
    historical_state_creation_gas: int
    standard_branch_after_state: int
    floor_branch: int
    floor_binds: bool
    floor_uplift: int
    current_floor_binds_observed: bool
    regular_gas_glamsterdam: int


def _require_non_negative(**values: int) -> None:
    for name, value in values.items():
        if int(value) < 0:
            raise ValueError(f"{name} must be non-negative")


def calldata_tokens(zero_bytes: int, nonzero_bytes: int) -> int:
    _require_non_negative(zero_bytes=zero_bytes, nonzero_bytes=nonzero_bytes)
    return int(zero_bytes) + 4 * int(nonzero_bytes)


def calldata_bytes(zero_bytes: int, nonzero_bytes: int) -> int:
    _require_non_negative(zero_bytes=zero_bytes, nonzero_bytes=nonzero_bytes)
    return int(zero_bytes) + int(nonzero_bytes)


def standard_calldata_gas(zero_bytes: int, nonzero_bytes: int) -> int:
    return STANDARD_TOKEN_COST * calldata_tokens(zero_bytes, nonzero_bytes)


def current_7623_floor_gas(zero_bytes: int, nonzero_bytes: int) -> int:
    return CURRENT_TOTAL_COST_FLOOR_PER_TOKEN_7623 * calldata_tokens(
        zero_bytes,
        nonzero_bytes,
    )


def glamsterdam_7976_floor_gas(zero_bytes: int, nonzero_bytes: int) -> int:
    floor_tokens = 4 * calldata_bytes(zero_bytes, nonzero_bytes)
    return GLAMSTERDAM_TOTAL_COST_FLOOR_PER_TOKEN_7976 * floor_tokens


def access_list_bytes(address_count: int, storage_key_count: int) -> int:
    _require_non_negative(
        address_count=address_count,
        storage_key_count=storage_key_count,
    )
    return (
        int(address_count) * ACCESS_LIST_ADDRESS_BYTES
        + int(storage_key_count) * ACCESS_LIST_STORAGE_KEY_BYTES
    )


def access_list_cost_2930(address_count: int, storage_key_count: int) -> int:
    _require_non_negative(
        address_count=address_count,
        storage_key_count=storage_key_count,
    )
    return (
        int(address_count) * ACCESS_LIST_ADDRESS_COST_2930
        + int(storage_key_count) * ACCESS_LIST_STORAGE_KEY_COST_2930
    )


def access_list_data_cost_7981(address_count: int, storage_key_count: int) -> int:
    return ACCESS_LIST_DATA_GAS_PER_BYTE_7981 * access_list_bytes(
        address_count,
        storage_key_count,
    )


def historical_state_creation_gas(
    *,
    new_storage_slots: int = 0,
    new_accounts: int = 0,
    code_bytes: int = 0,
    new_delegation_indicators: int = 0,
) -> int:
    _require_non_negative(
        new_storage_slots=new_storage_slots,
        new_accounts=new_accounts,
        code_bytes=code_bytes,
        new_delegation_indicators=new_delegation_indicators,
    )
    return (
        int(new_storage_slots) * HISTORICAL_STORAGE_SET_GAS
        + int(new_accounts) * HISTORICAL_NEW_ACCOUNT_GAS
        + int(code_bytes) * HISTORICAL_CODE_DEPOSIT_GAS_PER_BYTE
        + int(new_delegation_indicators) * HISTORICAL_AUTH_BASE_GAS
    )


def glamsterdam_regular_gas_tx(
    *,
    execution_gas_used_adjusted: int,
    calldata_zero_bytes: int,
    calldata_nonzero_bytes: int,
    access_list_address_count: int = 0,
    access_list_storage_key_count: int = 0,
    create_cost: int = 0,
    tx_base_gas: int = TX_BASE_GAS,
) -> dict[str, int | bool]:
    """Compute the EIP-7976/EIP-7981 transaction regular-gas formula.

    ``execution_gas_used_adjusted`` is the regular execution branch after any
    EIP-8037 state-creation de-accounting the caller wants to apply.
    """

    _require_non_negative(
        execution_gas_used_adjusted=execution_gas_used_adjusted,
        calldata_zero_bytes=calldata_zero_bytes,
        calldata_nonzero_bytes=calldata_nonzero_bytes,
        access_list_address_count=access_list_address_count,
        access_list_storage_key_count=access_list_storage_key_count,
        create_cost=create_cost,
        tx_base_gas=tx_base_gas,
    )
    standard_branch = (
        standard_calldata_gas(calldata_zero_bytes, calldata_nonzero_bytes)
        + int(execution_gas_used_adjusted)
        + int(create_cost)
        + access_list_cost_2930(
            access_list_address_count,
            access_list_storage_key_count,
        )
    )
    floor_branch = glamsterdam_7976_floor_gas(
        calldata_zero_bytes,
        calldata_nonzero_bytes,
    )
    access_data_cost = access_list_data_cost_7981(
        access_list_address_count,
        access_list_storage_key_count,
    )
    floor_uplift = max(0, floor_branch - standard_branch)
    return {
        "standard_branch": standard_branch,
        "floor_branch": floor_branch,
        "floor_binds": floor_branch > standard_branch,
        "floor_uplift": floor_uplift,
        "access_list_data_cost_7981": access_data_cost,
        "regular_gas_glamsterdam": (
            int(tx_base_gas) + access_data_cost + max(standard_branch, floor_branch)
        ),
    }


def glamsterdam_regular_gas_from_receipt(
    *,
    receipt_gas_used: int,
    calldata_zero_bytes: int,
    calldata_nonzero_bytes: int,
    access_list_address_count: int = 0,
    access_list_storage_key_count: int = 0,
    historical_state_creation_gas_used: int = 0,
    tx_base_gas: int = TX_BASE_GAS,
) -> GlamsterdamTxGasResult:
    """Reprice a historical transaction into Glamsterdam regular gas.

    The observed receipt body gas is treated as the current post-7623
    ``max(standard_branch, current_floor_branch)``. Then any supplied
    historical state-creation gas is removed before applying the Glamsterdam
    EIP-7976 floor and EIP-7981 access-list data surcharge.
    """

    _require_non_negative(
        receipt_gas_used=receipt_gas_used,
        calldata_zero_bytes=calldata_zero_bytes,
        calldata_nonzero_bytes=calldata_nonzero_bytes,
        access_list_address_count=access_list_address_count,
        access_list_storage_key_count=access_list_storage_key_count,
        historical_state_creation_gas_used=historical_state_creation_gas_used,
        tx_base_gas=tx_base_gas,
    )
    if int(receipt_gas_used) < int(tx_base_gas):
        raise ValueError("receipt_gas_used must be at least tx_base_gas")

    body_gas = int(receipt_gas_used) - int(tx_base_gas)
    current_floor = current_7623_floor_gas(
        calldata_zero_bytes,
        calldata_nonzero_bytes,
    )
    glam_floor = glamsterdam_7976_floor_gas(
        calldata_zero_bytes,
        calldata_nonzero_bytes,
    )
    address_count = int(access_list_address_count)
    storage_key_count = int(access_list_storage_key_count)
    access_bytes = access_list_bytes(address_count, storage_key_count)
    access_cost = access_list_cost_2930(address_count, storage_key_count)
    access_data_cost = access_list_data_cost_7981(address_count, storage_key_count)
    standard_after_state = max(
        0,
        body_gas - int(historical_state_creation_gas_used),
    )
    floor_uplift = max(0, glam_floor - standard_after_state)
    return GlamsterdamTxGasResult(
        receipt_gas_used=int(receipt_gas_used),
        receipt_body_gas=body_gas,
        calldata_zero_bytes=int(calldata_zero_bytes),
        calldata_nonzero_bytes=int(calldata_nonzero_bytes),
        calldata_bytes=calldata_bytes(calldata_zero_bytes, calldata_nonzero_bytes),
        calldata_tokens=calldata_tokens(calldata_zero_bytes, calldata_nonzero_bytes),
        standard_calldata_gas=standard_calldata_gas(
            calldata_zero_bytes,
            calldata_nonzero_bytes,
        ),
        current_7623_floor_gas=current_floor,
        glamsterdam_7976_floor_gas=glam_floor,
        access_list_address_count=address_count,
        access_list_storage_key_count=storage_key_count,
        access_list_bytes=access_bytes,
        access_list_cost_2930=access_cost,
        access_list_data_cost_7981=access_data_cost,
        historical_state_creation_gas=int(historical_state_creation_gas_used),
        standard_branch_after_state=standard_after_state,
        floor_branch=glam_floor,
        floor_binds=glam_floor > standard_after_state,
        floor_uplift=floor_uplift,
        current_floor_binds_observed=body_gas == current_floor and current_floor > 0,
        regular_gas_glamsterdam=int(tx_base_gas)
        + access_data_cost
        + max(standard_after_state, glam_floor),
    )
