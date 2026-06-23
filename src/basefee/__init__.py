"""Base-fee update helpers."""

from .eip7999_normalized import (
    BASE_FEE_UPDATE_FRACTION,
    GAS_NORMALIZATION_FACTOR,
    MIN_BASE_FEE_PER_GAS,
    ResourceFeeConfig,
    ResourceFeeState,
    apply_resource_block,
    apply_vector_block,
    compute_base_fee,
    fake_exponential,
    update_normalized_excess_gas,
)

__all__ = [
    "BASE_FEE_UPDATE_FRACTION",
    "GAS_NORMALIZATION_FACTOR",
    "MIN_BASE_FEE_PER_GAS",
    "ResourceFeeConfig",
    "ResourceFeeState",
    "apply_resource_block",
    "apply_vector_block",
    "compute_base_fee",
    "fake_exponential",
    "update_normalized_excess_gas",
]
