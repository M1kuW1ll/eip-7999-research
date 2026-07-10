"""Block-by-block driven replay for the full EIP-7999 mechanism."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Integral

import pandas as pd

from basefee import reserve_anchor_threshold_base_fee
from demand.shocks import JointShockPath
from mechanisms import (
    MechanismConfig,
    PassiveBlockUsage,
    initialize_mechanism_states,
    step_full_7999,
)

from .allocation import InclusionRule, SeparateResourceCaps
from .demand import DEMAND_RESOURCES, MeteredDemandModel

DEMAND_TO_MECHANISM = {
    "execution": "execution",
    "data": "bandwidth",
    "state": "state",
}
DEFAULT_GAS_QUANTUM = {"execution": 1, "data": 16, "state": 1}


def _quantize_nearest(value: float, quantum: int) -> int:
    if not math.isfinite(value) or value < 0:
        raise ValueError("offered demand must be finite and non-negative")
    return max(0, int(round(value / int(quantum))) * int(quantum))


def _blob_fee_path(
    value: int | Sequence[int] | None,
    *,
    n_steps: int,
    required: bool,
) -> list[int | None]:
    if value is None:
        if required:
            raise ValueError(
                "blob_base_fee_per_gas is required when the data reserve is enabled"
            )
        return [None] * n_steps
    if isinstance(value, Integral):
        if int(value) < 0:
            raise ValueError("blob base fees must be non-negative")
        return [int(value)] * n_steps
    path = [int(item) for item in value]
    if len(path) != n_steps:
        raise ValueError("blob base-fee path length must match the shock path")
    if any(item < 0 for item in path):
        raise ValueError("blob base fees must be non-negative")
    return path


def run_driven_full_7999(
    *,
    config: MechanismConfig,
    demand_model: MeteredDemandModel,
    shock_path: JointShockPath,
    blob_base_fee_per_gas: int | Sequence[int] | None,
    inclusion_rule: InclusionRule | None = None,
    gas_quantum: Mapping[str, int] | None = None,
    first_block_number: int = 0,
    step_seconds: int = 12,
) -> pd.DataFrame:
    """Run full 7999 with fee-responsive demand and joint demand shocks.

    Timing is explicit: ``*_base_fee_wei`` governs the current block, while
    ``*_next_base_fee_wei`` is produced for the following block.  Execution
    and data are capped before the exact mechanism transition; state remains
    uncapped.  Rejected gas is recorded as ``unserved`` and is not carried
    into a backlog in this first aggregate scaffold.

    ``shock_path`` must contain block-frequency observations.  Daily shocks
    cannot be silently repeated across 12-second updates; a later multiscale
    model will combine slow daily conditions with within-day block shocks.
    """

    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    shock_path.require_block_frequency(step_seconds=step_seconds)
    if config.name != "full_7999":
        raise ValueError("run_driven_full_7999 requires a full_7999 config")
    if set(config.resources) != {"execution", "bandwidth", "state"}:
        raise ValueError("full_7999 requires execution, bandwidth, and state")

    quanta = dict(DEFAULT_GAS_QUANTUM if gas_quantum is None else gas_quantum)
    for resource in DEMAND_RESOURCES:
        if resource not in quanta or int(quanta[resource]) <= 0:
            raise ValueError(f"gas_quantum[{resource!r}] must be positive")

    shocks = shock_path.values.reset_index(drop=True)
    if tuple(shocks.columns) != DEMAND_RESOURCES:
        raise ValueError(
            "shock path columns must be exactly execution, data, state"
        )
    if len(shocks) == 0:
        raise ValueError("shock path must contain at least one block")

    reserve_enabled = config.resources["bandwidth"].has_reserve_price
    blob_fees = _blob_fee_path(
        blob_base_fee_per_gas,
        n_steps=len(shocks),
        required=reserve_enabled,
    )
    allocator = inclusion_rule or SeparateResourceCaps()
    limits = {
        resource: config.resources[DEMAND_TO_MECHANISM[resource]].gas_limit
        for resource in DEMAND_RESOURCES
    }
    targets = {
        resource: config.resources[DEMAND_TO_MECHANISM[resource]].gas_target
        for resource in DEMAND_RESOURCES
    }

    states = initialize_mechanism_states(config)
    rows: list[dict[str, object]] = []

    for offset, shock_row in shocks.iterrows():
        block_number = int(first_block_number) + int(offset)
        current_fees = {
            resource: int(states[DEMAND_TO_MECHANISM[resource]].base_fee)
            for resource in DEMAND_RESOURCES
        }
        deterministic = demand_model.quantities(current_fees)
        shock = {resource: float(shock_row[resource]) for resource in DEMAND_RESOURCES}
        if any(not math.isfinite(value) or value < 0 for value in shock.values()):
            raise ValueError("demand shocks must be finite and non-negative")
        offered = {
            resource: _quantize_nearest(
                float(deterministic[resource]) * shock[resource],
                int(quanta[resource]),
            )
            for resource in DEMAND_RESOURCES
        }
        allocation = allocator.allocate(offered, limits, quanta)
        blob_fee = blob_fees[offset]

        block = PassiveBlockUsage(
            block_number=block_number,
            timestamp=None,
            execution_gas_used=int(allocation.included_gas["execution"]),
            state_gas_used=int(allocation.included_gas["state"]),
            bandwidth_gas=int(allocation.included_gas["data"]),
            bandwidth_bytes=int(allocation.included_gas["data"]) // 16,
            blob_base_fee_per_gas=blob_fee,
        )
        step = step_full_7999(
            block=block,
            config=config,
            parent_states=states,
        )

        row: dict[str, object] = {
            "block_number": block_number,
            "elapsed_seconds": int(offset) * int(step_seconds),
            "step_seconds": int(step_seconds),
            "shock_source": shock_path.source,
            "shock_source_position": int(shock_path.source_positions[offset]),
            "shock_basis": shock_path.basis,
            "allocation_rule": allocation.rule,
            "bundle_scale": float(allocation.bundle_scale),
            "binding_resources": ",".join(allocation.binding_resources),
            "blob_base_fee_per_gas": blob_fee,
            "data_reserve_active": bool(
                step.reserve_active_by_resource["bandwidth"]
            ),
            "data_reserve_threshold_wei": reserve_anchor_threshold_base_fee(
                blob_fee,
                config.resources["bandwidth"],
            ),
        }
        for resource in DEMAND_RESOURCES:
            mechanism_resource = DEMAND_TO_MECHANISM[resource]
            gas_limit = limits[resource]
            included = int(allocation.included_gas[resource])
            row.update(
                {
                    f"{resource}_base_fee_wei": int(
                        step.result.base_fee_by_resource[mechanism_resource]
                    ),
                    f"{resource}_next_base_fee_wei": int(
                        step.next_states[mechanism_resource].base_fee
                    ),
                    f"{resource}_excess_gas": int(
                        step.result.excess_gas_by_resource[mechanism_resource]
                    ),
                    f"{resource}_next_excess_gas": int(
                        step.next_states[mechanism_resource].excess_gas
                    ),
                    f"{resource}_deterministic_demand_gas": float(
                        deterministic[resource]
                    ),
                    f"{resource}_shock": shock[resource],
                    f"{resource}_offered_gas": int(offered[resource]),
                    f"{resource}_included_gas": included,
                    f"{resource}_unserved_gas": int(
                        allocation.unserved_gas[resource]
                    ),
                    f"{resource}_gas_target": int(targets[resource]),
                    f"{resource}_gas_limit": gas_limit,
                    f"{resource}_pct_target": included / int(targets[resource]),
                    f"{resource}_pct_limit": (
                        math.nan if gas_limit is None else included / int(gas_limit)
                    ),
                    f"{resource}_own_limit_exceeded": (
                        False
                        if gas_limit is None
                        else int(offered[resource]) > int(gas_limit)
                    ),
                    f"{resource}_rationed": int(
                        allocation.unserved_gas[resource]
                    ) > 0,
                    f"{resource}_limit_hit": (
                        False
                        if gas_limit is None
                        else included == int(gas_limit)
                    ),
                }
            )
        rows.append(row)
        states = dict(step.next_states)

    replay = pd.DataFrame(rows)
    replay.attrs["unserved_demand_treatment"] = "discarded; no backlog"
    replay.attrs["data_mechanism_name"] = "bandwidth"
    return replay
