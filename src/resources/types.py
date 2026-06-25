"""Shared dataclasses for resource accounting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceLimit:
    name: str
    target: int
    limit: int

    def __post_init__(self) -> None:
        if self.target <= 0:
            raise ValueError("target must be positive")
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.limit < self.target:
            raise ValueError("limit must be greater than or equal to target")


@dataclass(frozen=True)
class ResourceUsage:
    name: str
    used: int

    def __post_init__(self) -> None:
        if self.used < 0:
            raise ValueError("used must be non-negative")


@dataclass(frozen=True)
class ResourceAccountingResult:
    name: str
    used: int
    target: int
    limit: int
    excess: int
    limit_hit: bool
    target_ratio: float
    limit_ratio: float


@dataclass(frozen=True)
class StateCreationCounts:
    new_storage_slots: int = 0
    new_accounts: int = 0
    code_bytes: int = 0
    new_delegation_indicators: int = 0

    def __post_init__(self) -> None:
        values = [
            self.new_storage_slots,
            self.new_accounts,
            self.code_bytes,
            self.new_delegation_indicators,
        ]
        if any(value < 0 for value in values):
            raise ValueError("state creation counts must be non-negative")


@dataclass(frozen=True)
class BandwidthCounts:
    calldata_zero_bytes: int = 0
    calldata_nonzero_bytes: int = 0
    bal_rlp_bytes: int = 0
    authorization_tuple_bytes: int = 0
    blob_versioned_hash_bytes: int = 0

    def __post_init__(self) -> None:
        values = [
            self.calldata_zero_bytes,
            self.calldata_nonzero_bytes,
            self.bal_rlp_bytes,
            self.authorization_tuple_bytes,
            self.blob_versioned_hash_bytes,
        ]
        if any(value < 0 for value in values):
            raise ValueError("bandwidth counts must be non-negative")


@dataclass(frozen=True)
class BlockResourceCounts:
    block_number: int
    # execution_gas_used should be the regular execution component after
    # separating state-gas and bandwidth gas. Do not pass raw receipt gas if it
    # still includes calldata/state costs, or replay will double count them.
    execution_gas_used: int
    state: StateCreationCounts
    bandwidth: BandwidthCounts

    def __post_init__(self) -> None:
        if self.execution_gas_used < 0:
            raise ValueError("execution_gas_used must be non-negative")


@dataclass(frozen=True)
class BlockResourceUsage:
    block_number: int
    execution_gas_used: int
    new_storage_slots: int
    new_accounts: int
    code_bytes: int
    new_delegation_indicators: int
    state_gas_used: int
    state_bytes_created_equivalent: int
    calldata_zero_bytes: int
    calldata_nonzero_bytes: int
    calldata_bytes: int
    calldata_gas: int
    bal_rlp_bytes: int
    bal_gas: int
    authorization_tuple_bytes: int
    authorization_tuple_gas: int
    blob_versioned_hash_bytes: int
    blob_versioned_hash_gas: int
    bandwidth_bytes: int
    bandwidth_gas: int
