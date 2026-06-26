"""Map byte-denominated bandwidth caps into EIP-7999 resource gas units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BandwidthMeteringConfig:
    safe_bandwidth_bytes: int
    gas_per_safe_byte: int = 16
    bal_gas_per_byte: int = 16
    tx_access_list_gas_per_byte: int = 64
    authorization_tuple_gas_per_byte: int = 64
    blob_hash_gas_per_byte: int = 64
    calldata_mode: str = "eip7999_4_16"
    bal_mode: str = "fixed_16_per_byte"


def compute_bandwidth_usage(
    calldata_zero_bytes: int,
    calldata_nonzero_bytes: int,
    bal_rlp_bytes: int,
    config: BandwidthMeteringConfig,
    tx_access_list_bytes: int = 0,
    authorization_tuple_bytes: int = 0,
    blob_versioned_hash_bytes: int = 0,
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
    tx_access_list_gas = int(config.tx_access_list_gas_per_byte) * int(
        tx_access_list_bytes
    )
    authorization_tuple_gas = int(config.authorization_tuple_gas_per_byte) * int(
        authorization_tuple_bytes
    )
    blob_versioned_hash_gas = int(config.blob_hash_gas_per_byte) * int(
        blob_versioned_hash_bytes
    )

    bandwidth_bytes = (
        calldata_bytes
        + int(bal_rlp_bytes)
        + int(tx_access_list_bytes)
        + int(authorization_tuple_bytes)
        + int(blob_versioned_hash_bytes)
    )
    bandwidth_gas = (
        calldata_gas
        + bal_gas
        + tx_access_list_gas
        + authorization_tuple_gas
        + blob_versioned_hash_gas
    )

    bandwidth_gas_limit = int(config.gas_per_safe_byte) * int(
        config.safe_bandwidth_bytes
    )

    return {
        "calldata_bytes": calldata_bytes,
        "calldata_gas": calldata_gas,
        "bal_bytes": int(bal_rlp_bytes),
        "bal_gas": bal_gas,
        "tx_access_list_bytes": int(tx_access_list_bytes),
        "tx_access_list_gas": tx_access_list_gas,
        "authorization_tuple_bytes": int(authorization_tuple_bytes),
        "authorization_tuple_gas": authorization_tuple_gas,
        "blob_versioned_hash_bytes": int(blob_versioned_hash_bytes),
        "blob_versioned_hash_gas": blob_versioned_hash_gas,
        "bandwidth_bytes": bandwidth_bytes,
        "bandwidth_gas": bandwidth_gas,
        "bandwidth_gas_limit": bandwidth_gas_limit,
        "bandwidth_bytes_pct_limit": bandwidth_bytes / config.safe_bandwidth_bytes,
        "bandwidth_gas_pct_limit": bandwidth_gas / bandwidth_gas_limit,
    }
