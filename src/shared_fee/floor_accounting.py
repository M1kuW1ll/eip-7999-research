"""Exact transaction-floor accounting for the shared-fee benchmark.

The benchmark combines EIP-2780's decomposed execution-intrinsic base with the
EIP-8131 static content floor and EIP-8279's static authorization BAL bytes and
runtime BAL meter.  State gas is intentionally absent: EIP-8037 accounts for it
in the other branch of the block bottleneck.
"""

from __future__ import annotations

from dataclasses import dataclass


FLOOR_GAS_PER_BYTE = 64

TX_BASE_COST_2780 = 12_000
TX_VALUE_COST_2780 = 6_000
COLD_ACCOUNT_ACCESS_8038 = 3_000
COLD_STORAGE_ACCESS_8038 = 2_100
STORAGE_WRITE_8038 = 10_000
ACCOUNT_WRITE_8038 = 9_000
CREATE_ACCESS_8038 = 12_000
ACCESS_LIST_ADDRESS_COST_8038 = 2_900
ACCESS_LIST_STORAGE_KEY_COST_8038 = 2_000
STORAGE_CLEAR_REFUND_8038 = 11_616
EXECUTION_PER_AUTH_BASE_COST_8037 = 7_816

ACCESS_LIST_ADDRESS_BYTES_8131 = 20
ACCESS_LIST_STORAGE_KEY_BYTES_8131 = 32
AUTH_TUPLE_BYTES_8131 = 108
BLOB_VERSIONED_HASH_BYTES_8131 = 32
AUTH_BAL_STATIC_BYTES_8279 = 51


def _nonnegative_int(value: int, name: str) -> int:
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result


def eip2780_floor_base(
    *,
    has_recipient: bool,
    self_transfer: bool = False,
    transfers_value: bool = False,
    authorization_count: int = 0,
) -> int:
    """Return the state-independent execution base beneath the content floor.

    This is the EIP-2780 replacement for EIP-8131's fixed ``TX_BASE``.  It
    excludes calldata and access-list intrinsic charges because those content
    fields are represented by the 64-gas-per-byte floor term.
    """

    auths = _nonnegative_int(authorization_count, "authorization_count")
    if self_transfer and not has_recipient:
        raise ValueError("A contract-creation transaction cannot be a self-transfer")

    base = TX_BASE_COST_2780
    if not has_recipient:
        base += CREATE_ACCESS_8038
    elif not self_transfer:
        base += COLD_ACCOUNT_ACCESS_8038
        if transfers_value:
            base += TX_VALUE_COST_2780
    base += EXECUTION_PER_AUTH_BASE_COST_8037 * auths
    return base


def eip8131_content_bytes(
    *,
    calldata_bytes: int = 0,
    access_list_addresses: int = 0,
    access_list_storage_keys: int = 0,
    authorization_count: int = 0,
    blob_versioned_hash_count: int = 0,
) -> int:
    """Return transaction content bytes included by EIP-8131."""

    calldata = _nonnegative_int(calldata_bytes, "calldata_bytes")
    addresses = _nonnegative_int(access_list_addresses, "access_list_addresses")
    keys = _nonnegative_int(access_list_storage_keys, "access_list_storage_keys")
    auths = _nonnegative_int(authorization_count, "authorization_count")
    blob_hashes = _nonnegative_int(
        blob_versioned_hash_count, "blob_versioned_hash_count"
    )
    return (
        calldata
        + ACCESS_LIST_ADDRESS_BYTES_8131 * addresses
        + ACCESS_LIST_STORAGE_KEY_BYTES_8131 * keys
        + AUTH_TUPLE_BYTES_8131 * auths
        + BLOB_VERSIONED_HASH_BYTES_8131 * blob_hashes
    )


def eip8131_floor_gas(*, intrinsic_execution_base: int, content_bytes: int) -> int:
    """Return the EIP-8131 floor under an EIP-2780 intrinsic base."""

    base = _nonnegative_int(intrinsic_execution_base, "intrinsic_execution_base")
    content = _nonnegative_int(content_bytes, "content_bytes")
    return base + FLOOR_GAS_PER_BYTE * content


def eip8279_floor_gas(
    *,
    intrinsic_execution_base: int,
    content_bytes_8131: int,
    authorization_count: int = 0,
    runtime_bal_bytes: int = 0,
) -> int:
    """Return the EIP-8131 floor after the EIP-8279 extensions."""

    auths = _nonnegative_int(authorization_count, "authorization_count")
    runtime = _nonnegative_int(runtime_bal_bytes, "runtime_bal_bytes")
    additional_bytes = AUTH_BAL_STATIC_BYTES_8279 * auths + runtime
    return eip8131_floor_gas(
        intrinsic_execution_base=intrinsic_execution_base,
        content_bytes=content_bytes_8131,
    ) + FLOOR_GAS_PER_BYTE * additional_bytes


def floor_charged_gas(*, execution_gas_used: int, floor_gas_used: int) -> int:
    """Apply the EIP-8131/EIP-8279 ``max(execution, floor)`` charge."""

    execution = _nonnegative_int(execution_gas_used, "execution_gas_used")
    floor = _nonnegative_int(floor_gas_used, "floor_gas_used")
    return max(execution, floor)


@dataclass(frozen=True)
class FloorComparison:
    execution_gas_used: int
    eip8131_floor_gas: int
    eip8279_floor_gas: int
    charged_gas_8131: int
    charged_gas_8279: int
    incremental_gas_8279: int
    headroom_before_runtime_bal: int


def incremental_eip8279_uplift(
    *,
    execution_gas_used: int,
    intrinsic_execution_base: int,
    content_bytes_8131: int,
    authorization_count: int = 0,
    runtime_bal_bytes: int = 0,
) -> FloorComparison:
    """Compare exact transaction gas under EIP-8131 and EIP-8279."""

    execution = _nonnegative_int(execution_gas_used, "execution_gas_used")
    floor_8131 = eip8131_floor_gas(
        intrinsic_execution_base=intrinsic_execution_base,
        content_bytes=content_bytes_8131,
    )
    floor_8279 = eip8279_floor_gas(
        intrinsic_execution_base=intrinsic_execution_base,
        content_bytes_8131=content_bytes_8131,
        authorization_count=authorization_count,
        runtime_bal_bytes=runtime_bal_bytes,
    )
    charged_8131 = floor_charged_gas(
        execution_gas_used=execution,
        floor_gas_used=floor_8131,
    )
    charged_8279 = floor_charged_gas(
        execution_gas_used=execution,
        floor_gas_used=floor_8279,
    )
    return FloorComparison(
        execution_gas_used=execution,
        eip8131_floor_gas=floor_8131,
        eip8279_floor_gas=floor_8279,
        charged_gas_8131=charged_8131,
        charged_gas_8279=charged_8279,
        incremental_gas_8279=charged_8279 - charged_8131,
        headroom_before_runtime_bal=execution - floor_8131,
    )
