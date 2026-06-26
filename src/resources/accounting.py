"""Small resource accounting helpers without a replay loop."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from .types import (
    BandwidthCounts,
    BlockResourceCounts,
    BlockResourceUsage,
    ResourceAccountingResult,
    ResourceLimit,
    ResourceUsage,
    StateCreationCounts,
)

STATE_BYTES_PER_STORAGE_SET = 64
STATE_BYTES_PER_NEW_ACCOUNT = 120
STATE_BYTES_PER_DELEGATION_INDICATOR = 23

CALLDATA_ZERO_GAS_PER_BYTE = 4
CALLDATA_NONZERO_GAS_PER_BYTE = 16
DEFAULT_BAL_GAS_PER_BYTE = 16
DEFAULT_TX_ACCESS_LIST_GAS_PER_BYTE = 64
DEFAULT_AUTHORIZATION_TUPLE_GAS_PER_BYTE = 64
DEFAULT_BLOB_HASH_GAS_PER_BYTE = 64


def shared_resource_used(
    *used_values: int,
    mode: Literal["max", "sum"] = "max",
) -> int:
    if not used_values:
        raise ValueError("at least one used value is required")

    values = [int(value) for value in used_values]
    if any(value < 0 for value in values):
        raise ValueError("used values must be non-negative")

    if mode == "max":
        return max(values)
    if mode == "sum":
        return sum(values)
    raise ValueError(f"Unknown shared accounting mode: {mode}")


def account_resource(
    usage: ResourceUsage,
    limit: ResourceLimit,
) -> ResourceAccountingResult:
    if usage.name != limit.name:
        raise ValueError(
            f"usage and limit names differ: {usage.name!r} != {limit.name!r}"
        )

    used = int(usage.used)
    target = int(limit.target)
    hard_limit = int(limit.limit)

    return ResourceAccountingResult(
        name=usage.name,
        used=used,
        target=target,
        limit=hard_limit,
        excess=max(0, used - target),
        limit_hit=used >= hard_limit,
        target_ratio=used / target,
        limit_ratio=used / hard_limit,
    )


def account_resources(
    usages: Iterable[ResourceUsage],
    limits: Mapping[str, ResourceLimit],
) -> dict[str, ResourceAccountingResult]:
    results: dict[str, ResourceAccountingResult] = {}
    for usage in usages:
        if usage.name not in limits:
            raise KeyError(f"Missing resource limit for {usage.name!r}")
        results[usage.name] = account_resource(usage, limits[usage.name])
    return results


def account_execution_state_shared(
    regular_gas_used: int,
    state_gas_used: int,
    target_gas: int,
    limit_gas: int,
    name: str = "execution_state",
) -> ResourceAccountingResult:
    used = shared_resource_used(regular_gas_used, state_gas_used, mode="max")
    return account_resource(
        ResourceUsage(name=name, used=used),
        ResourceLimit(name=name, target=int(target_gas), limit=int(limit_gas)),
    )


def compute_state_bytes_equivalent(counts: StateCreationCounts) -> int:
    return (
        int(counts.new_storage_slots) * STATE_BYTES_PER_STORAGE_SET
        + int(counts.new_accounts) * STATE_BYTES_PER_NEW_ACCOUNT
        + int(counts.code_bytes)
        + int(counts.new_delegation_indicators)
        * STATE_BYTES_PER_DELEGATION_INDICATOR
    )


def compute_state_gas(
    counts: StateCreationCounts,
    cpsb: int,
) -> int:
    if cpsb <= 0:
        raise ValueError("cpsb must be positive")
    return compute_state_bytes_equivalent(counts) * int(cpsb)


def compute_calldata_gas(
    calldata_zero_bytes: int,
    calldata_nonzero_bytes: int,
) -> int:
    if calldata_zero_bytes < 0 or calldata_nonzero_bytes < 0:
        raise ValueError("calldata byte counts must be non-negative")
    return (
        CALLDATA_ZERO_GAS_PER_BYTE * int(calldata_zero_bytes)
        + CALLDATA_NONZERO_GAS_PER_BYTE * int(calldata_nonzero_bytes)
    )


def compute_bandwidth_usage(
    counts: BandwidthCounts,
    bal_gas_per_byte: int = DEFAULT_BAL_GAS_PER_BYTE,
    tx_access_list_gas_per_byte: int = DEFAULT_TX_ACCESS_LIST_GAS_PER_BYTE,
    authorization_tuple_gas_per_byte: int = DEFAULT_AUTHORIZATION_TUPLE_GAS_PER_BYTE,
    blob_hash_gas_per_byte: int = DEFAULT_BLOB_HASH_GAS_PER_BYTE,
) -> dict[str, int]:
    if bal_gas_per_byte < 0:
        raise ValueError("bal_gas_per_byte must be non-negative")
    if tx_access_list_gas_per_byte < 0:
        raise ValueError("tx_access_list_gas_per_byte must be non-negative")
    if authorization_tuple_gas_per_byte < 0:
        raise ValueError("authorization_tuple_gas_per_byte must be non-negative")
    if blob_hash_gas_per_byte < 0:
        raise ValueError("blob_hash_gas_per_byte must be non-negative")

    calldata_bytes = int(counts.calldata_zero_bytes) + int(
        counts.calldata_nonzero_bytes
    )
    calldata_gas = compute_calldata_gas(
        calldata_zero_bytes=counts.calldata_zero_bytes,
        calldata_nonzero_bytes=counts.calldata_nonzero_bytes,
    )
    bal_gas = int(bal_gas_per_byte) * int(counts.bal_rlp_bytes)
    tx_access_list_gas = int(tx_access_list_gas_per_byte) * int(
        counts.tx_access_list_bytes
    )
    authorization_tuple_gas = int(authorization_tuple_gas_per_byte) * int(
        counts.authorization_tuple_bytes
    )
    blob_versioned_hash_gas = int(blob_hash_gas_per_byte) * int(
        counts.blob_versioned_hash_bytes
    )
    bandwidth_bytes = (
        calldata_bytes
        + int(counts.bal_rlp_bytes)
        + int(counts.tx_access_list_bytes)
        + int(counts.authorization_tuple_bytes)
        + int(counts.blob_versioned_hash_bytes)
    )
    bandwidth_gas = (
        calldata_gas
        + bal_gas
        + tx_access_list_gas
        + authorization_tuple_gas
        + blob_versioned_hash_gas
    )

    return {
        "calldata_zero_bytes": int(counts.calldata_zero_bytes),
        "calldata_nonzero_bytes": int(counts.calldata_nonzero_bytes),
        "calldata_bytes": calldata_bytes,
        "calldata_gas": calldata_gas,
        "bal_rlp_bytes": int(counts.bal_rlp_bytes),
        "bal_gas": bal_gas,
        "tx_access_list_bytes": int(counts.tx_access_list_bytes),
        "tx_access_list_gas": tx_access_list_gas,
        "authorization_tuple_bytes": int(counts.authorization_tuple_bytes),
        "authorization_tuple_gas": authorization_tuple_gas,
        "blob_versioned_hash_bytes": int(counts.blob_versioned_hash_bytes),
        "blob_versioned_hash_gas": blob_versioned_hash_gas,
        "bandwidth_bytes": bandwidth_bytes,
        "bandwidth_gas": bandwidth_gas,
    }


def compute_block_resource_usage(
    block: BlockResourceCounts,
    cpsb: int,
    bal_gas_per_byte: int = DEFAULT_BAL_GAS_PER_BYTE,
    tx_access_list_gas_per_byte: int = DEFAULT_TX_ACCESS_LIST_GAS_PER_BYTE,
    authorization_tuple_gas_per_byte: int = DEFAULT_AUTHORIZATION_TUPLE_GAS_PER_BYTE,
    blob_hash_gas_per_byte: int = DEFAULT_BLOB_HASH_GAS_PER_BYTE,
) -> BlockResourceUsage:
    state_bytes_created_equivalent = compute_state_bytes_equivalent(block.state)
    state_gas_used = compute_state_gas(block.state, cpsb=cpsb)
    bandwidth = compute_bandwidth_usage(
        block.bandwidth,
        bal_gas_per_byte=bal_gas_per_byte,
        tx_access_list_gas_per_byte=tx_access_list_gas_per_byte,
        authorization_tuple_gas_per_byte=authorization_tuple_gas_per_byte,
        blob_hash_gas_per_byte=blob_hash_gas_per_byte,
    )

    return BlockResourceUsage(
        block_number=int(block.block_number),
        execution_gas_used=int(block.execution_gas_used),
        new_storage_slots=int(block.state.new_storage_slots),
        new_accounts=int(block.state.new_accounts),
        code_bytes=int(block.state.code_bytes),
        new_delegation_indicators=int(block.state.new_delegation_indicators),
        state_gas_used=state_gas_used,
        state_bytes_created_equivalent=state_bytes_created_equivalent,
        calldata_zero_bytes=bandwidth["calldata_zero_bytes"],
        calldata_nonzero_bytes=bandwidth["calldata_nonzero_bytes"],
        calldata_bytes=bandwidth["calldata_bytes"],
        calldata_gas=bandwidth["calldata_gas"],
        bal_rlp_bytes=bandwidth["bal_rlp_bytes"],
        bal_gas=bandwidth["bal_gas"],
        tx_access_list_bytes=bandwidth["tx_access_list_bytes"],
        tx_access_list_gas=bandwidth["tx_access_list_gas"],
        authorization_tuple_bytes=bandwidth["authorization_tuple_bytes"],
        authorization_tuple_gas=bandwidth["authorization_tuple_gas"],
        blob_versioned_hash_bytes=bandwidth["blob_versioned_hash_bytes"],
        blob_versioned_hash_gas=bandwidth["blob_versioned_hash_gas"],
        bandwidth_bytes=bandwidth["bandwidth_bytes"],
        bandwidth_gas=bandwidth["bandwidth_gas"],
    )
