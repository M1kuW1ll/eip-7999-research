"""Shared types for passive mechanism replay.

The mechanism layer is passive replay only: historical resource usage is fixed,
and invalid blocks mean the hypothetical mechanism would not have accepted the
historical block as-is. Elastic demand, reserve prices, and builder packing are
intentionally out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class PassiveBlockUsage:
    """One block of already-separated resource usage.

    ``execution_gas_used`` must be the regular execution component after
    separating state gas and bandwidth gas. Do not pass raw receipt gas if it
    still includes calldata/state costs, or replay will double count them.
    """

    block_number: int
    timestamp: int | None
    execution_gas_used: int
    state_gas_used: int
    bandwidth_gas: int
    bandwidth_bytes: int
    calldata_gas: int = 0
    bal_gas: int = 0
    calldata_bytes: int = 0
    bal_bytes: int = 0

    def __post_init__(self) -> None:
        values = [
            self.execution_gas_used,
            self.state_gas_used,
            self.bandwidth_gas,
            self.bandwidth_bytes,
            self.calldata_gas,
            self.bal_gas,
            self.calldata_bytes,
            self.bal_bytes,
        ]
        if any(value < 0 for value in values):
            raise ValueError("passive block usage values must be non-negative")


@dataclass(frozen=True)
class MechanismBlockResult:
    block_number: int
    timestamp: int | None
    mechanism: str
    valid: bool
    invalid_reasons: tuple[str, ...]
    gas_used_by_resource: Mapping[str, int]
    gas_limit_by_resource: Mapping[str, int]
    gas_target_by_resource: Mapping[str, int]
    base_fee_by_resource: Mapping[str, int]
    excess_gas_by_resource: Mapping[str, int]
    pct_limit_by_resource: Mapping[str, float]
    pct_target_by_resource: Mapping[str, float]
    execution_gas_used: int
    state_gas_used: int
    bandwidth_gas: int
    bandwidth_bytes: int
