"""Worst-case payload strategies under candidate bandwidth schedules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd

from .scenarios import GasSchedule

BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True)
class StrategyResult:
    schedule_name: str
    strategy: str
    execution_gas_limit: int
    gas_used: int
    calldata_bytes: int
    bal_bytes: int
    tx_access_list_bytes: int
    total_payload_bytes: int
    total_payload_mib: float
    notes: str


def _capacity(gas_limit: int, schedule: GasSchedule) -> int:
    return max(0, int(gas_limit) - schedule.tx_base_gas)


def _result(
    *,
    schedule: GasSchedule,
    strategy: str,
    gas_limit: int,
    gas_used: int,
    calldata_bytes: int = 0,
    bal_bytes: int = 0,
    tx_access_list_bytes: int = 0,
    notes: str = "",
) -> StrategyResult:
    total_payload_bytes = (
        int(calldata_bytes) + int(bal_bytes) + int(tx_access_list_bytes)
    )
    return StrategyResult(
        schedule_name=schedule.name,
        strategy=strategy,
        execution_gas_limit=int(gas_limit),
        gas_used=int(gas_used),
        calldata_bytes=int(calldata_bytes),
        bal_bytes=int(bal_bytes),
        tx_access_list_bytes=int(tx_access_list_bytes),
        total_payload_bytes=total_payload_bytes,
        total_payload_mib=total_payload_bytes / BYTES_PER_MIB,
        notes=notes,
    )


def all_calldata_nonzero(gas_limit: int, schedule: GasSchedule) -> StrategyResult:
    """Single transaction with only nonzero calldata under the 64 gas/byte floor."""

    capacity = _capacity(gas_limit, schedule)
    calldata_bytes = capacity // schedule.calldata_floor_gas_per_byte
    gas_used = schedule.tx_base_gas + (
        calldata_bytes * schedule.calldata_floor_gas_per_byte
    )
    return _result(
        schedule=schedule,
        strategy="all_calldata_nonzero",
        gas_limit=gas_limit,
        gas_used=min(gas_used, int(gas_limit)),
        calldata_bytes=calldata_bytes,
        notes="Single data-heavy transaction; calldata floor binds.",
    )


def sload_bal_only(gas_limit: int, schedule: GasSchedule) -> StrategyResult:
    """Single transaction with one cold account and many cold SLOADs."""

    capacity = _capacity(gas_limit, schedule)
    if capacity < schedule.cold_account_access_gas:
        return _result(
            schedule=schedule,
            strategy="sload_bal_only",
            gas_limit=gas_limit,
            gas_used=min(schedule.tx_base_gas, int(gas_limit)),
            notes="Gas limit does not fit one cold account access.",
        )

    max_by_execution = (
        capacity - schedule.cold_account_access_gas
    ) // schedule.cold_sload_gas
    max_by_floor = max_by_execution
    if schedule.runtime_bal_floor_gas_per_byte is not None:
        floor_capacity = capacity // schedule.runtime_bal_floor_gas_per_byte
        max_by_floor = (
            floor_capacity - schedule.bal_account_bytes
        ) // schedule.bal_storage_key_bytes

    sload_count = max(0, min(max_by_execution, max_by_floor))
    bal_bytes = schedule.bal_account_bytes + (
        sload_count * schedule.bal_storage_key_bytes
    )
    execution_component = schedule.cold_account_access_gas + (
        sload_count * schedule.cold_sload_gas
    )
    floor_component = (
        0
        if schedule.runtime_bal_floor_gas_per_byte is None
        else schedule.runtime_bal_floor_gas_per_byte * bal_bytes
    )
    gas_used = schedule.tx_base_gas + max(execution_component, floor_component)

    return _result(
        schedule=schedule,
        strategy="sload_bal_only",
        gas_limit=gas_limit,
        gas_used=gas_used,
        bal_bytes=bal_bytes,
        notes=f"{sload_count:,} cold SLOADs; one cold account BAL entry.",
    )


def mixed_calldata_plus_cold_sloads(
    gas_limit: int, schedule: GasSchedule
) -> StrategyResult:
    """Search calldata plus cold-SLOAD BAL bytes under one transaction gas limit."""

    capacity = _capacity(gas_limit, schedule)
    best: StrategyResult | None = None

    max_sloads_by_execution = max(
        0,
        (capacity - schedule.cold_account_access_gas) // schedule.cold_sload_gas,
    )
    max_sloads_by_floor = max_sloads_by_execution
    if schedule.runtime_bal_floor_gas_per_byte is not None:
        max_floor_bytes = capacity // schedule.runtime_bal_floor_gas_per_byte
        max_sloads_by_floor = max(
            0,
            (max_floor_bytes - schedule.bal_account_bytes)
            // schedule.bal_storage_key_bytes,
        )

    max_sloads = min(max_sloads_by_execution, max_sloads_by_floor)
    for sload_count in range(max_sloads + 1):
        execution_component = schedule.cold_account_access_gas + (
            sload_count * schedule.cold_sload_gas
        )
        bal_bytes = schedule.bal_account_bytes + (
            sload_count * schedule.bal_storage_key_bytes
        )
        runtime_bal_floor_component = (
            0
            if schedule.runtime_bal_floor_gas_per_byte is None
            else schedule.runtime_bal_floor_gas_per_byte * bal_bytes
        )

        max_by_execution = (
            capacity - execution_component
        ) // schedule.standard_nonzero_calldata_gas_per_byte
        max_by_floor = (
            capacity - runtime_bal_floor_component
        ) // schedule.calldata_floor_gas_per_byte
        calldata_bytes = max(0, min(max_by_execution, max_by_floor))

        execution_branch = (
            schedule.standard_nonzero_calldata_gas_per_byte * calldata_bytes
            + execution_component
        )
        floor_branch = (
            schedule.calldata_floor_gas_per_byte * calldata_bytes
            + runtime_bal_floor_component
        )
        gas_used = schedule.tx_base_gas + max(execution_branch, floor_branch)
        if gas_used > gas_limit:
            continue

        candidate = _result(
            schedule=schedule,
            strategy="mixed_calldata_plus_cold_sloads",
            gas_limit=gas_limit,
            gas_used=gas_used,
            calldata_bytes=calldata_bytes,
            bal_bytes=bal_bytes,
            notes=f"{sload_count:,} cold SLOADs plus nonzero calldata.",
        )
        if best is None or (
            candidate.total_payload_bytes,
            -candidate.gas_used,
        ) > (
            best.total_payload_bytes,
            -best.gas_used,
        ):
            best = candidate

    if best is None:
        return _result(
            schedule=schedule,
            strategy="mixed_calldata_plus_cold_sloads",
            gas_limit=gas_limit,
            gas_used=min(schedule.tx_base_gas, int(gas_limit)),
            notes="No valid mixed transaction fits the gas limit.",
        )
    return best


def tx_access_list_plus_calldata(
    gas_limit: int, schedule: GasSchedule
) -> StrategyResult:
    """Toy EIP-7981 access-list payload strategy under a 64 gas/byte floor."""

    capacity = _capacity(gas_limit, schedule)
    total_floor_bytes = capacity // schedule.access_list_floor_gas_per_byte
    tx_access_list_bytes = total_floor_bytes // 2
    calldata_bytes = total_floor_bytes - tx_access_list_bytes
    gas_used = schedule.tx_base_gas + (
        calldata_bytes * schedule.calldata_floor_gas_per_byte
        + tx_access_list_bytes * schedule.access_list_floor_gas_per_byte
    )

    return _result(
        schedule=schedule,
        strategy="tx_access_list_plus_calldata",
        gas_limit=gas_limit,
        gas_used=min(gas_used, int(gas_limit)),
        calldata_bytes=calldata_bytes,
        tx_access_list_bytes=tx_access_list_bytes,
        notes="Access-list bytes pay the same 64 gas/byte floor as calldata.",
    )


def strategies_for(gas_limit: int, schedule: GasSchedule) -> list[StrategyResult]:
    return [
        all_calldata_nonzero(gas_limit, schedule),
        sload_bal_only(gas_limit, schedule),
        mixed_calldata_plus_cold_sloads(gas_limit, schedule),
        tx_access_list_plus_calldata(gas_limit, schedule),
    ]


def best_strategy(gas_limit: int, schedule: GasSchedule) -> StrategyResult:
    """Return the largest combined payload strategy for a gas limit/schedule."""

    best = strategies_for(gas_limit, schedule)[0]
    for candidate in strategies_for(gas_limit, schedule)[1:]:
        if candidate.total_payload_bytes > best.total_payload_bytes:
            best = candidate
    return best


def sweep_strategies(
    gas_limits: Iterable[int], schedules: Iterable[GasSchedule]
) -> pd.DataFrame:
    """Evaluate all strategies and mark the best one for each schedule/limit."""

    rows = []
    for schedule in schedules:
        for gas_limit in gas_limits:
            best = best_strategy(int(gas_limit), schedule)
            for result in strategies_for(int(gas_limit), schedule):
                row = asdict(result)
                row["schedule"] = row.pop("schedule_name")
                row["is_best"] = result.strategy == best.strategy
                row["best_strategy"] = best.strategy
                rows.append(row)
    return pd.DataFrame(rows)
