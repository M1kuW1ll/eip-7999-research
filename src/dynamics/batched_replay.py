"""Batched bundle-priced EIP-7999 dynamic replay.

The fee recursion is sequential in time, so the only axis available for
vectorisation is the trajectory. This runs one time loop over blocks with every
trajectory advanced together, where a trajectory is one point in

    designs x seeds x model specifications x initial conditions.

Statistics are accumulated online. A full Stage A sweep is order 10^8 block
updates, and retaining even one float field per block per trajectory would run
to gigabytes, so only running summaries are kept and full paths are returned
for explicitly requested trajectories.

The base-fee update reproduces `basefee.eip7999_normalized` exactly over the
whole realistic fee range: the integer `fake_exponential` and
`floor(min_fee * exp(excess / update_fraction))` agree on every one of 3,943
excess values tested from 1 wei to 3.58 gwei.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RESOURCES = ("execution", "data", "state")
DATA_COMPONENTS = ("static", "bal_execution", "bal_state")
GAS_NORMALIZATION_FACTOR = 10**9
BASE_FEE_UPDATE_FRACTION = 4_245_093_508
MIN_BASE_FEE_PER_GAS = 1.0
GWEI = 1e9


@dataclass(frozen=True)
class BatchConfig:
    """Per-trajectory arrays, each of shape (B,) unless noted."""

    execution_target: np.ndarray
    execution_limit: np.ndarray
    data_target: np.ndarray
    data_limit: np.ndarray
    state_target: np.ndarray

    eps_execution: np.ndarray
    eps_data: np.ndarray
    eps_state: np.ndarray

    w_execution: np.ndarray
    w_state: np.ndarray
    rho_A: np.ndarray

    m_execution: float
    m_state: float
    m_data_static: float
    q_execution_0: float
    q_state_0: float
    g_static_0: float
    p0_gwei: float

    @property
    def batch_size(self) -> int:
        return int(self.execution_target.shape[0])


def bundle_cost_equivalent_start(config: BatchConfig) -> np.ndarray:
    """Historically cost-equivalent EIP-7999 launch fees, in wei."""

    p0 = config.p0_gwei * GWEI
    data_fee = p0 / config.m_data_static
    execution_fee = np.maximum(
        MIN_BASE_FEE_PER_GAS,
        (p0 - config.w_execution * data_fee) / config.m_execution,
    )
    state_fee = np.maximum(
        MIN_BASE_FEE_PER_GAS,
        (p0 - config.w_state * data_fee) / config.m_state,
    )
    return np.stack(
        [execution_fee, np.full_like(execution_fee, data_fee), state_fee],
        axis=1,
    )


def compute_base_fee(excess_gas: np.ndarray) -> np.ndarray:
    """Vectorised EIP-7999 normalised base fee, in wei."""

    return np.maximum(
        MIN_BASE_FEE_PER_GAS,
        np.floor(MIN_BASE_FEE_PER_GAS * np.exp(excess_gas / BASE_FEE_UPDATE_FRACTION)),
    )


def excess_gas_for_base_fee(base_fee: np.ndarray) -> np.ndarray:
    """Smallest excess gas whose fee reaches ``base_fee``. Inverse of the above."""

    base_fee = np.maximum(base_fee, MIN_BASE_FEE_PER_GAS)
    return BASE_FEE_UPDATE_FRACTION * np.log(base_fee / MIN_BASE_FEE_PER_GAS)


def update_excess_gas(
    excess_gas: np.ndarray, gas_used: np.ndarray, target: np.ndarray,
    denominator: np.ndarray,
) -> np.ndarray:
    """Normalised excess-gas update, matching the integer reference exactly.

    The reference floors the normalised delta magnitude before applying it, in
    both directions. Without the floor the float recursion drifts away from the
    integer one over thousands of blocks, because the truncation is one-sided.
    """

    magnitude = np.floor(
        np.abs(gas_used - target) * GAS_NORMALIZATION_FACTOR / denominator
    )
    signed = np.where(gas_used >= target, magnitude, -magnitude)
    return np.maximum(0.0, excess_gas + signed)


@dataclass
class EffectivePriceSummary:
    """Streaming log-return and log-level moments for effective activity prices.

    What a user actually pays for a unit of activity is not a single base fee.
    Under EIP-7999 an execution unit is charged its own metered gas plus the BAL
    data gas it produces, so its price mixes two fees that move independently;
    under Glamsterdam all three prices are fixed multiples of one shared fee and
    therefore move together exactly. Comparing raw base fees across the two
    mechanisms compares different gas units, so the comparison is made on these
    prices instead.

    Quantiles come from a histogram of absolute log returns rather than retained
    paths: the grid runs reach order 1e8 block updates, where keeping the series
    needed for an exact percentile would run to gigabytes. Bin width is
    ``max_abs / n_bins``, which sets the resolution of the reported quantile.
    """

    batch_size: int
    width: int = 3
    n_bins: int = 400
    max_abs: float = 4.0

    blocks: int = 0
    _sum: np.ndarray = field(init=False)
    _sumsq: np.ndarray = field(init=False)
    _level_sum: np.ndarray = field(init=False)
    _level_sumsq: np.ndarray = field(init=False)
    _histogram: np.ndarray = field(init=False)
    _rows: np.ndarray = field(init=False)
    _columns: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        shape = (self.batch_size, self.width)
        self._sum = np.zeros(shape)
        self._sumsq = np.zeros(shape)
        self._level_sum = np.zeros(shape)
        self._level_sumsq = np.zeros(shape)
        self._histogram = np.zeros((*shape, self.n_bins), dtype=np.int32)
        self._rows = np.arange(self.batch_size)[:, None]
        self._columns = np.arange(self.width)[None, :]

    def update(self, prices: np.ndarray, previous_prices: np.ndarray) -> None:
        self.blocks += 1
        log_prices = np.log(np.maximum(prices, 1e-300))
        ret = log_prices - np.log(np.maximum(previous_prices, 1e-300))
        self._sum += ret
        self._sumsq += ret * ret
        self._level_sum += log_prices
        self._level_sumsq += log_prices * log_prices
        # Returns beyond max_abs land in the final bin, so a reported quantile
        # that saturates there is a lower bound rather than a wrong number.
        index = np.clip(
            (np.abs(ret) * (self.n_bins / self.max_abs)).astype(np.int64),
            0, self.n_bins - 1,
        )
        # Each (trajectory, resource) contributes exactly one bin per block, so
        # the index triple is unique within a call and plain fancy indexing is
        # safe here. np.add.at would be correct too but is an order of magnitude
        # slower, and this runs once per block for the whole batch.
        self._histogram[self._rows, self._columns, index] += 1

    def quantile(self, q: float) -> np.ndarray:
        """Quantile of |log return|, taken at the upper edge of its bin."""

        cumulative = np.cumsum(self._histogram, axis=-1)
        threshold = q * cumulative[..., -1:]
        index = (cumulative < threshold).sum(axis=-1)
        return (index + 1) * (self.max_abs / self.n_bins)

    def to_dict(self, prefix: str = "effective_price") -> dict[str, np.ndarray]:
        n = max(self.blocks, 1)
        mean = self._sum / n
        var = np.maximum(self._sumsq / n - mean * mean, 0.0)
        return {
            f"{prefix}_log_return_sd": np.sqrt(var),
            f"{prefix}_log_return_p95": self.quantile(0.95),
            f"{prefix}_log_return_p99": self.quantile(0.99),
            f"{prefix}_mean_log_level": self._level_sum / n,
            f"{prefix}_mean_square_log_level": self._level_sumsq / n,
        }


@dataclass
class OnlineSummary:
    """Streaming accumulators. Nothing here grows with the number of blocks."""

    batch_size: int
    blocks: int = 0
    _log_return_sum: np.ndarray = field(init=False)
    _log_return_sumsq: np.ndarray = field(init=False)
    _log_return_absmax: np.ndarray = field(init=False)
    _at_floor: np.ndarray = field(init=False)
    _floor_downward_pressure: np.ndarray = field(init=False)
    _floor_run: np.ndarray = field(init=False)
    _floor_run_max: np.ndarray = field(init=False)
    _offered_pressure: np.ndarray = field(init=False)
    _included_at_limit: np.ndarray = field(init=False)
    _included_near_limit: np.ndarray = field(init=False)
    _cap_active: np.ndarray = field(init=False)
    _scale_determining: np.ndarray = field(init=False)
    _limit_run: np.ndarray = field(init=False)
    _limit_run_max: np.ndarray = field(init=False)
    _any_limit: np.ndarray = field(init=False)
    _any_limit_run: np.ndarray = field(init=False)
    _any_limit_run_max: np.ndarray = field(init=False)
    _any_near_limit: np.ndarray = field(init=False)
    _used_sum: np.ndarray = field(init=False)
    _absolute_target_gap_sum: np.ndarray = field(init=False)
    _absolute_target_deviation_sum: np.ndarray = field(init=False)
    _rationed_sum: np.ndarray = field(init=False)
    _fee_sum: np.ndarray = field(init=False)
    _burn_wei_sum: np.ndarray = field(init=False)
    _execution_only_cap_active: np.ndarray = field(init=False)
    _data_only_cap_active: np.ndarray = field(init=False)
    _both_caps_active: np.ndarray = field(init=False)
    _data_components_offered_sum: np.ndarray = field(init=False)
    _data_components_included_sum: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        shape = (self.batch_size, 3)
        for name in ("_log_return_sum", "_log_return_sumsq", "_log_return_absmax",
                     "_at_floor", "_floor_downward_pressure",
                     "_floor_run", "_floor_run_max",
                     "_offered_pressure", "_included_at_limit",
                     "_included_near_limit", "_cap_active",
                     "_scale_determining", "_limit_run", "_limit_run_max",
                     "_used_sum", "_absolute_target_gap_sum",
                     "_absolute_target_deviation_sum", "_rationed_sum",
                     "_fee_sum", "_burn_wei_sum"):
            setattr(self, name, np.zeros(shape))
        self._any_limit = np.zeros(self.batch_size)
        self._any_limit_run = np.zeros(self.batch_size)
        self._any_limit_run_max = np.zeros(self.batch_size)
        self._any_near_limit = np.zeros(self.batch_size)
        self._execution_only_cap_active = np.zeros(self.batch_size)
        self._data_only_cap_active = np.zeros(self.batch_size)
        self._both_caps_active = np.zeros(self.batch_size)
        self._data_components_offered_sum = np.zeros(shape)
        self._data_components_included_sum = np.zeros(shape)

    def update(
        self, fees, previous_fees, used, offered, limits,
        targets=None,
        cap_active=None, scale_determining=None,
        data_components_offered=None, data_components_included=None,
    ) -> None:
        self.blocks += 1
        ret = np.log(np.maximum(fees, 1e-30) / np.maximum(previous_fees, 1e-30))
        self._log_return_sum += ret
        self._log_return_sumsq += ret * ret
        np.maximum(self._log_return_absmax, np.abs(ret), out=self._log_return_absmax)

        # ``previous_fees`` are the fees that governed the included usage in
        # this measured block; ``fees`` are the updates for the next block.
        floor = previous_fees <= MIN_BASE_FEE_PER_GAS
        self._at_floor += floor
        self._floor_run = np.where(floor, self._floor_run + 1, 0)
        np.maximum(self._floor_run_max, self._floor_run, out=self._floor_run_max)

        # A one-wei observation does not by itself show that the minimum is
        # constraining the market. Align the fee that governed this block with
        # its included usage: if that fee is already one wei and usage remains
        # below target, the controller calls for a further downward adjustment
        # that the protocol minimum prevents.
        if targets is not None:
            targets = np.asarray(targets, dtype=float)
            self._floor_downward_pressure += floor & (used < targets - 1e-9)
            absolute_target_gap = np.abs(used - targets)
            self._absolute_target_gap_sum += absolute_target_gap
            self._absolute_target_deviation_sum += np.divide(
                absolute_target_gap,
                targets,
                out=np.zeros_like(absolute_target_gap),
                where=targets > 0,
            )

        finite_limit = np.isfinite(limits)
        offered_pressure = finite_limit & (offered >= limits - 1e-9)
        included_at_limit = finite_limit & (used >= limits - 1e-6)
        # Historical blocks are not expected to equal their gas limit exactly,
        # because transactions are indivisible. The 98% threshold matches the
        # historical-source diagnostic and provides a comparable congestion
        # statistic alongside the simulator's exact included-limit measure.
        included_near_limit = finite_limit & (used >= 0.98 * limits)

        if cap_active is None:
            cap_active = offered_pressure
        else:
            cap_active = np.asarray(cap_active, dtype=bool)
        if scale_determining is None:
            ratios = np.where(
                finite_limit,
                limits / np.maximum(offered, 1e-300),
                np.inf,
            )
            determining_index = np.argmin(ratios, axis=1)
            scale_determining = np.zeros_like(cap_active)
            constrained = ratios[np.arange(self.batch_size), determining_index] <= 1.0
            scale_determining[
                np.arange(self.batch_size)[constrained], determining_index[constrained]
            ] = True
        else:
            scale_determining = np.asarray(scale_determining, dtype=bool)

        self._offered_pressure += offered_pressure
        self._included_at_limit += included_at_limit
        self._included_near_limit += included_near_limit
        self._cap_active += cap_active
        self._scale_determining += scale_determining
        self._limit_run = np.where(included_at_limit, self._limit_run + 1, 0)
        np.maximum(self._limit_run_max, self._limit_run, out=self._limit_run_max)
        any_limit = np.any(included_at_limit, axis=1)
        any_near_limit = np.any(included_near_limit, axis=1)
        self._any_limit += any_limit
        self._any_near_limit += any_near_limit
        self._any_limit_run = np.where(any_limit, self._any_limit_run + 1, 0)
        np.maximum(
            self._any_limit_run_max,
            self._any_limit_run,
            out=self._any_limit_run_max,
        )

        execution_active = cap_active[:, 0]
        data_active = cap_active[:, 1]
        self._execution_only_cap_active += execution_active & ~data_active
        self._data_only_cap_active += data_active & ~execution_active
        self._both_caps_active += execution_active & data_active

        self._used_sum += used
        self._rationed_sum += np.maximum(offered - used, 0.0)
        self._fee_sum += fees
        # ``previous_fees`` governed this block's inclusion decision and are
        # therefore the fees paid on ``used``. ``fees`` apply to the next block.
        self._burn_wei_sum += used * previous_fees
        if data_components_offered is not None:
            self._data_components_offered_sum += data_components_offered
        if data_components_included is not None:
            self._data_components_included_sum += data_components_included

    def to_dict(self) -> dict[str, np.ndarray]:
        n = max(self.blocks, 1)
        mean = self._log_return_sum / n
        var = np.maximum(self._log_return_sumsq / n - mean * mean, 0.0)
        floor_downward_share = np.divide(
            self._floor_downward_pressure,
            self._at_floor,
            out=np.zeros_like(self._floor_downward_pressure),
            where=self._at_floor > 0,
        )
        return {
            "log_return_sd": np.sqrt(var),
            "log_return_absmax": self._log_return_absmax,
            "floor_fraction": self._at_floor / n,
            "floor_downward_pressure_fraction": self._floor_downward_pressure / n,
            "floor_downward_pressure_given_floor": floor_downward_share,
            "longest_floor_run": self._floor_run_max,
            # ``limit_hit`` is reserved for included usage at the hard limit.
            "limit_hit_fraction": self._included_at_limit / n,
            "included_limit_fraction": self._included_at_limit / n,
            "near_limit_fraction": self._included_near_limit / n,
            "offered_limit_pressure_fraction": self._offered_pressure / n,
            "cap_active_fraction": self._cap_active / n,
            "scale_determining_fraction": self._scale_determining / n,
            "execution_only_cap_active_fraction": self._execution_only_cap_active / n,
            "data_only_cap_active_fraction": self._data_only_cap_active / n,
            "both_caps_active_fraction": self._both_caps_active / n,
            "longest_limit_run": self._limit_run_max,
            "any_limit_hit_fraction": self._any_limit / n,
            "any_near_limit_fraction": self._any_near_limit / n,
            "longest_any_limit_run": self._any_limit_run_max,
            "mean_used": self._used_sum / n,
            "mean_absolute_target_gap": self._absolute_target_gap_sum / n,
            "mean_absolute_target_deviation": (
                self._absolute_target_deviation_sum / n
            ),
            "mean_rationed": self._rationed_sum / n,
            "mean_fee_wei": self._fee_sum / n,
            "mean_burn_wei": self._burn_wei_sum / n,
            "mean_total_burn_wei": self._burn_wei_sum.sum(axis=1) / n,
            "mean_data_components_offered": self._data_components_offered_sum / n,
            "mean_data_components_included": self._data_components_included_sum / n,
        }


def run_batch(
    config: BatchConfig,
    shocks: np.ndarray,
    initial_base_fee_wei: np.ndarray,
    *,
    bundle_consistent: bool,
    burn_in: int = 0,
    return_paths: bool = False,
) -> dict[str, np.ndarray]:
    """Advance every trajectory through ``shocks`` and return online summaries.

    ``shocks`` has shape (B, T, 4) as multiplicative factors ordered
    (execution, data, state, access). ``initial_base_fee_wei`` is (B, 3) and
    defines the warm or cold start. ``bundle_consistent`` is deliberately
    required: ``False`` permits the infeasible diagnostic that caps BAL
    independently of the parent activity that generated it, so callers must
    opt into that behavior explicitly.
    """

    n_paths, n_blocks, n_shocks = shocks.shape
    if n_shocks != 4:
        raise ValueError("shocks must have four components")
    batch = config.batch_size
    if n_paths == batch:
        shock_index = None
    elif batch % n_paths == 0:
        # The shock path varies only over seeds, so designs and specifications
        # index into a shared array instead of materialising a tiled copy. At
        # Stage C scale the tiled array was 2.65 GB and the run was memory
        # bound rather than compute bound.
        shock_index = np.tile(np.arange(n_paths), batch // n_paths)
    else:
        raise ValueError(
            f"batch {batch} is not a multiple of the {n_paths} supplied shock paths"
        )

    p0_wei = config.p0_gwei * GWEI
    fees = np.maximum(initial_base_fee_wei.astype(float), MIN_BASE_FEE_PER_GAS)
    excess = excess_gas_for_base_fee(fees)

    targets = np.stack(
        [config.execution_target, config.data_target, config.state_target], axis=1
    )
    limits = np.stack(
        [config.execution_limit, config.data_limit,
         np.full_like(config.state_target, np.inf)], axis=1
    )
    # EIP-7999 normalises limited resources by their limit; state has no block
    # limit and normalises by its target.
    denominator = np.stack(
        [config.execution_limit, config.data_limit, config.state_target], axis=1
    )

    summary = OnlineSummary(batch)
    effective_prices = EffectivePriceSummary(batch)
    # Seeded from the launch fees so the first measured block has a predecessor
    # and the price series covers exactly the same blocks as the fee series. At
    # t=0 the execution ratio is 1, so the realised access intensity equals the
    # reference one for every rho_A.
    previous_prices = np.stack([
        config.m_execution * fees[:, 0] + config.w_execution * fees[:, 1],
        config.m_data_static * fees[:, 1],
        config.m_state * fees[:, 2] + config.w_state * fees[:, 1],
    ], axis=1)
    # Stress runs are short enough to retain full paths; screening runs are not,
    # which is why summaries are otherwise accumulated online.
    fee_paths = np.empty((batch, n_blocks, 3)) if return_paths else None
    used_paths = np.empty((batch, n_blocks, 3)) if return_paths else None
    # Average execution BAL intensity depends on realised execution, so it uses
    # the previous block's ratio: within a block, users cannot know the ratio
    # their own inclusion produces.
    execution_ratio = np.ones(batch)

    for t in range(n_blocks):
        block_shocks = shocks[:, t, :] if shock_index is None else shocks[shock_index, t, :]
        s_execution, s_data, s_state, a_access = (block_shocks[:, i] for i in range(4))

        average_intensity = config.w_execution * execution_ratio ** (config.rho_A - 1.0)
        parent_execution = config.m_execution * fees[:, 0] + average_intensity * fees[:, 1]
        parent_state = config.m_state * fees[:, 2] + config.w_state * fees[:, 1]

        q_execution = (
            config.q_execution_0
            * np.maximum(parent_execution / p0_wei, 1e-300) ** (-config.eps_execution)
            * s_execution
        )
        q_state = (
            config.q_state_0
            * np.maximum(parent_state / p0_wei, 1e-300) ** (-config.eps_state)
            * s_state
        )
        g_static = (
            config.g_static_0
            * np.maximum(config.m_data_static * fees[:, 1] / p0_wei, 1e-300)
            ** (-config.eps_data)
            * s_data
        )

        execution_ratio = np.maximum(q_execution / config.q_execution_0, 1e-12)
        # Kept split by parent, because bundle-consistent inclusion has to scale
        # execution-linked BAL with execution and state-linked BAL with state.
        g_bal_execution = (
            config.w_execution * config.q_execution_0 * execution_ratio ** config.rho_A
        ) * a_access
        g_bal_state = config.w_state * q_state * a_access
        g_bal = g_bal_execution + g_bal_state

        offered = np.stack([
            config.m_execution * q_execution,
            g_static + g_bal,
            config.m_state * q_state,
        ], axis=1)

        if bundle_consistent:
            # Vectorised ParentBALConsistentCaps. Capping each resource on its own
            # is not a feasible block: a transaction's execution gas and the BAL
            # bytes it produces are included or excluded together, so clipping the
            # data resource while retaining all execution describes a block no
            # builder could assemble. Execution is capped first, which scales
            # execution-linked BAL with it; if the remaining data bundle still
            # exceeds the limit, all remaining parent activity is scaled together.
            #
            # The second step is an aggregate selection assumption, and a
            # pessimistic one: a real builder would drop the most data-intensive
            # transactions first rather than a uniform share of everything, so
            # this brackets the truth from below where independent capping
            # brackets it from above.
            execution_scale = np.minimum(
                1.0, limits[:, 0] / np.maximum(offered[:, 0], 1e-300)
            )
            data_after_execution_cap = (
                g_static + g_bal_execution * execution_scale + g_bal_state
            )
            data_scale = np.minimum(
                1.0, limits[:, 1] / np.maximum(data_after_execution_cap, 1e-300)
            )
            execution_cap_active = execution_scale < 1.0
            data_cap_active = data_scale < 1.0
            cap_active = np.stack([
                execution_cap_active,
                data_cap_active,
                np.zeros(batch, dtype=bool),
            ], axis=1)
            # The data cap determines the final common bundle scale whenever it
            # remains active after execution capping. Otherwise execution is the
            # determining cap. This distinguishes actual allocation from raw
            # offered-demand exceedance.
            scale_determining = np.stack([
                execution_cap_active & ~data_cap_active,
                data_cap_active,
                np.zeros(batch, dtype=bool),
            ], axis=1)
            used = np.stack([
                offered[:, 0] * execution_scale * data_scale,
                np.minimum(data_after_execution_cap, limits[:, 1]),
                offered[:, 2] * data_scale,
            ], axis=1)
            data_components_included = np.stack([
                g_static * data_scale,
                g_bal_execution * execution_scale * data_scale,
                g_bal_state * data_scale,
            ], axis=1)
        else:
            used = np.minimum(offered, limits)
            data_scale = used[:, 1] / np.maximum(offered[:, 1], 1e-300)
            data_components_included = np.stack([
                g_static * data_scale,
                g_bal_execution * data_scale,
                g_bal_state * data_scale,
            ], axis=1)
            cap_active = offered >= limits - 1e-9
            ratios = limits / np.maximum(offered, 1e-300)
            determining_index = np.argmin(ratios, axis=1)
            scale_determining = np.zeros_like(cap_active, dtype=bool)
            constrained = ratios[np.arange(batch), determining_index] <= 1.0
            scale_determining[
                np.arange(batch)[constrained], determining_index[constrained]
            ] = True

        previous_fees = fees
        excess = update_excess_gas(excess, used, targets, denominator)
        fees = compute_base_fee(excess)

        # What a unit of each activity costs, not what its own base fee is. Both
        # parent prices carry the data fee through the BAL charge, so execution
        # and state prices move with b_data even when their own fee is flat --
        # which is the whole point of bundle pricing and is invisible in the raw
        # fee series. The realised access intensity is used rather than the
        # reference one, so that rho_A != 1 specifications price what their own
        # BAL load implies; at the central rho_A = 1 the two coincide exactly.
        prices = np.stack([
            config.m_execution * fees[:, 0] + average_intensity * fees[:, 1],
            config.m_data_static * fees[:, 1],
            config.m_state * fees[:, 2] + config.w_state * fees[:, 1],
        ], axis=1)

        if t >= burn_in:
            data_components_offered = np.stack([
                g_static, g_bal_execution, g_bal_state,
            ], axis=1)
            summary.update(
                fees, previous_fees, used, offered, limits,
                targets=targets,
                cap_active=cap_active,
                scale_determining=scale_determining,
                data_components_offered=data_components_offered,
                data_components_included=data_components_included,
            )
            effective_prices.update(prices, previous_prices)
        previous_prices = prices
        if fee_paths is not None:
            fee_paths[:, t, :] = fees
            used_paths[:, t, :] = used

    result = summary.to_dict()
    result.update(effective_prices.to_dict())
    result["final_base_fee_wei"] = fees
    result["final_excess_gas"] = excess
    if fee_paths is not None:
        result["fee_paths"] = fee_paths
        result["used_paths"] = used_paths
    return result
