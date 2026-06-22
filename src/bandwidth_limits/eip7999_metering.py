"""Map byte-denominated bandwidth caps into EIP-7999 resource gas units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BandwidthMeteringConfig:
    safe_bandwidth_bytes: int
    gas_per_safe_byte: int = 16
    bal_gas_per_byte: int = 16
    calldata_mode: str = "eip7999_4_16"
    bal_mode: str = "fixed_16_per_byte"


def compute_bandwidth_usage(
    calldata_zero_bytes: int,
    calldata_nonzero_bytes: int,
    bal_rlp_bytes: int,
    config: BandwidthMeteringConfig,
) -> dict:
    calldata_bytes = int(calldata_zero_bytes) + int(calldata_nonzero_bytes)

    if config.calldata_mode == "eip7999_4_16":
        calldata_gas = (
            4 * int(calldata_zero_bytes) + 16 * int(calldata_nonzero_bytes)
        )
    elif config.calldata_mode == "fixed_16_per_byte":
        calldata_gas = 16 * calldata_bytes
    else:
        raise ValueError(f"Unknown calldata_mode: {config.calldata_mode}")

    if config.bal_mode != "fixed_16_per_byte":
        raise ValueError(f"Unknown bal_mode: {config.bal_mode}")

    bal_gas = int(config.bal_gas_per_byte) * int(bal_rlp_bytes)

    bandwidth_bytes = calldata_bytes + int(bal_rlp_bytes)
    bandwidth_gas = calldata_gas + bal_gas

    bandwidth_gas_limit = int(config.gas_per_safe_byte) * int(
        config.safe_bandwidth_bytes
    )

    return {
        "calldata_bytes": calldata_bytes,
        "calldata_gas": calldata_gas,
        "bal_bytes": int(bal_rlp_bytes),
        "bal_gas": bal_gas,
        "bandwidth_bytes": bandwidth_bytes,
        "bandwidth_gas": bandwidth_gas,
        "bandwidth_gas_limit": bandwidth_gas_limit,
        "bandwidth_bytes_pct_limit": bandwidth_bytes / config.safe_bandwidth_bytes,
        "bandwidth_gas_pct_limit": bandwidth_gas / bandwidth_gas_limit,
    }
