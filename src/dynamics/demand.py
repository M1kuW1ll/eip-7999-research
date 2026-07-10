"""Demand curves used by the driven fee-market replay.

The dynamic benchmark uses the independent isoelastic estimates recovered in
notebook 1.8.  A matrix version is provided as an explicit coupling
sensitivity: off-diagonal entries describe how demand for resource ``i``
changes when the price of resource ``j`` changes.

All quantities returned here are already in candidate-world resource gas.
The public demand name ``data`` is translated to the mechanism's internal
name ``bandwidth`` only at the replay boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Protocol

DEMAND_RESOURCES = ("execution", "data", "state")


class MeteredDemandModel(Protocol):
    """A fee-responsive source of offered resource gas."""

    def quantities(
        self,
        base_fees_wei: Mapping[str, float],
    ) -> dict[str, float]: ...


def _require_resource_mapping(
    values: Mapping[str, float],
    *,
    label: str,
    allow_zero: bool,
) -> None:
    for resource in DEMAND_RESOURCES:
        if resource not in values:
            raise ValueError(f"{label} is missing {resource!r}")
        value = float(values[resource])
        if not math.isfinite(value):
            raise ValueError(f"{label}[{resource!r}] must be finite")
        if value < 0 or (value == 0 and not allow_zero):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"{label}[{resource!r}] must be {qualifier}")


@dataclass(frozen=True)
class IndependentIsoelasticDemand:
    """Three independently price-responsive isoelastic demand curves.

    For each resource ``i``::

        q_i(p_i) = q_i_ref * (p_i / p_i_ref) ** (-epsilon_i)

    ``anchor_metered_gas`` is gas per block under the candidate metering, not
    historical receipt gas.  ``reference_base_fees_wei`` must therefore use
    the same transport convention as the anchor (notebook 2.0 preserves the
    historical effective price when constructing these values).
    """

    anchor_metered_gas: Mapping[str, float]
    reference_base_fees_wei: Mapping[str, float]
    elasticities: Mapping[str, float]

    def __post_init__(self) -> None:
        _require_resource_mapping(
            self.anchor_metered_gas,
            label="anchor_metered_gas",
            allow_zero=False,
        )
        _require_resource_mapping(
            self.reference_base_fees_wei,
            label="reference_base_fees_wei",
            allow_zero=False,
        )
        _require_resource_mapping(
            self.elasticities,
            label="elasticities",
            allow_zero=True,
        )

    def quantities(
        self,
        base_fees_wei: Mapping[str, float],
    ) -> dict[str, float]:
        _require_resource_mapping(
            base_fees_wei,
            label="base_fees_wei",
            allow_zero=False,
        )
        return {
            resource: float(self.anchor_metered_gas[resource])
            * (
                float(base_fees_wei[resource])
                / float(self.reference_base_fees_wei[resource])
            )
            ** (-float(self.elasticities[resource]))
            for resource in DEMAND_RESOURCES
        }


@dataclass(frozen=True)
class ElasticityMatrixDemand:
    """Constant-elasticity demand with explicit cross-price responses.

    The matrix entry ``matrix[i][j]`` is ``d log(q_i) / d log(p_j)``.
    Diagonal entries are normally negative.  A negative off-diagonal entry
    represents bundle complementarity: raising fee ``j`` removes some of
    resource ``i`` carried by the same transactions.  A positive entry
    represents substitution.
    """

    anchor_metered_gas: Mapping[str, float]
    reference_base_fees_wei: Mapping[str, float]
    matrix: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        _require_resource_mapping(
            self.anchor_metered_gas,
            label="anchor_metered_gas",
            allow_zero=False,
        )
        _require_resource_mapping(
            self.reference_base_fees_wei,
            label="reference_base_fees_wei",
            allow_zero=False,
        )
        for demand_resource in DEMAND_RESOURCES:
            if demand_resource not in self.matrix:
                raise ValueError(f"matrix is missing row {demand_resource!r}")
            row = self.matrix[demand_resource]
            for price_resource in DEMAND_RESOURCES:
                if price_resource not in row:
                    raise ValueError(
                        "matrix is missing entry "
                        f"[{demand_resource!r}][{price_resource!r}]"
                    )
                if not math.isfinite(float(row[price_resource])):
                    raise ValueError("matrix entries must be finite")

    @classmethod
    def from_independent(
        cls,
        *,
        anchor_metered_gas: Mapping[str, float],
        reference_base_fees_wei: Mapping[str, float],
        elasticities: Mapping[str, float],
    ) -> "ElasticityMatrixDemand":
        _require_resource_mapping(
            elasticities,
            label="elasticities",
            allow_zero=True,
        )
        matrix = {
            i: {
                j: -float(elasticities[i]) if i == j else 0.0
                for j in DEMAND_RESOURCES
            }
            for i in DEMAND_RESOURCES
        }
        return cls(
            anchor_metered_gas=anchor_metered_gas,
            reference_base_fees_wei=reference_base_fees_wei,
            matrix=matrix,
        )

    def quantities(
        self,
        base_fees_wei: Mapping[str, float],
    ) -> dict[str, float]:
        _require_resource_mapping(
            base_fees_wei,
            label="base_fees_wei",
            allow_zero=False,
        )
        ratios = {
            resource: float(base_fees_wei[resource])
            / float(self.reference_base_fees_wei[resource])
            for resource in DEMAND_RESOURCES
        }
        output: dict[str, float] = {}
        for demand_resource in DEMAND_RESOURCES:
            log_quantity = math.log(float(self.anchor_metered_gas[demand_resource]))
            for price_resource in DEMAND_RESOURCES:
                log_quantity += float(
                    self.matrix[demand_resource][price_resource]
                ) * math.log(ratios[price_resource])
            output[demand_resource] = math.exp(log_quantity)
        return output
