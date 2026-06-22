"""Gas schedules for candidate Glamsterdam bandwidth-limit scenarios."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GasSchedule:
    name: str
    tx_base_gas: int = 21_000

    standard_zero_calldata_gas_per_byte: int = 4
    standard_nonzero_calldata_gas_per_byte: int = 16

    calldata_floor_gas_per_byte: int = 64
    access_list_floor_gas_per_byte: int = 64

    runtime_bal_floor_gas_per_byte: int | None = None

    cold_sload_gas: int = 2_100
    cold_account_access_gas: int = 2_600

    bal_account_bytes: int = 20
    bal_storage_key_bytes: int = 32


GLAMSTERDAM_NO_8279 = GasSchedule(
    name="glamsterdam_no_8279",
    runtime_bal_floor_gas_per_byte=None,
)

GLAMSTERDAM_PLUS_8279 = GasSchedule(
    name="glamsterdam_plus_8279",
    runtime_bal_floor_gas_per_byte=64,
)
