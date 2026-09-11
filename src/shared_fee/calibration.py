"""Aggregation helpers for the February--May shared-fee multiplier."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MultiplierEstimate:
    data_multiplier_8131: float
    incremental_multiplier_8279: float
    data_multiplier_8131_8279: float
    reference_data_gas: float
    incremental_gas_8279: float


def estimate_data_multiplier(
    *,
    reference_data_gas: pd.Series,
    counterfactual_data_gas_8131: pd.Series,
    incremental_gas_8279: pd.Series,
) -> MultiplierEstimate:
    """Estimate pooled multipliers as ratios of totals, never mean ratios."""

    reference = pd.to_numeric(reference_data_gas, errors="raise").astype(float)
    counterfactual = pd.to_numeric(
        counterfactual_data_gas_8131, errors="raise"
    ).astype(float)
    incremental = pd.to_numeric(incremental_gas_8279, errors="raise").astype(float)
    if not (len(reference) == len(counterfactual) == len(incremental)):
        raise ValueError("Multiplier inputs must have equal length")
    if not (
        np.isfinite(reference).all()
        and np.isfinite(counterfactual).all()
        and np.isfinite(incremental).all()
    ):
        raise ValueError("Multiplier inputs must be finite")
    if (reference < 0).any() or (counterfactual < 0).any() or (incremental < 0).any():
        raise ValueError("Multiplier inputs cannot be negative")
    reference_total = float(reference.sum())
    if reference_total <= 0:
        raise ValueError("Reference data gas total must be positive")
    counterfactual_total = float(counterfactual.sum())
    incremental_total = float(incremental.sum())
    multiplier_8131 = counterfactual_total / reference_total
    incremental_multiplier = incremental_total / reference_total
    return MultiplierEstimate(
        data_multiplier_8131=multiplier_8131,
        incremental_multiplier_8279=incremental_multiplier,
        data_multiplier_8131_8279=multiplier_8131 + incremental_multiplier,
        reference_data_gas=reference_total,
        incremental_gas_8279=incremental_total,
    )
