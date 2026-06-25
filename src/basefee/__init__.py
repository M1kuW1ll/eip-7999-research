"""Base-fee update helpers."""

from .eip1559 import BASE_FEE_MAX_CHANGE_DENOMINATOR, update_eip1559_base_fee
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
    "BASE_FEE_MAX_CHANGE_DENOMINATOR",
    "BASE_FEE_UPDATE_FRACTION",
    "GAS_NORMALIZATION_FACTOR",
    "MIN_BASE_FEE_PER_GAS",
    "ResourceFeeConfig",
    "ResourceFeeState",
    "apply_resource_block",
    "apply_vector_block",
    "compute_base_fee",
    "fake_exponential",
    "update_eip1559_base_fee",
    "update_normalized_excess_gas",
]
