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
    """Streaming log-return moments and quantiles for effective activity prices.

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
    _histogram: np.ndarray = field(init=False)
    _rows: np.ndarray = field(init=False)
    _columns: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        shape = (self.batch_size, self.width)
        self._sum = np.zeros(shape)
        self._sumsq = np.zeros(shape)
        self._histogram = np.zeros((*shape, self.n_bins), dtype=np.int32)
        self._rows = np.arange(self.batch_size)[:, None]
        self._columns = np.arange(self.width)[None, :]

    def update(self, prices: np.ndarray, previous_prices: np.ndarray) -> None:
        self.blocks += 1
        ret = np.log(np.maximum(prices, 1e-300) / np.maximum(previous_prices, 1e-300))
        self._sum += ret
        self._sumsq += ret * ret
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
    _floor_run: np.ndarray = field(init=False)
    _floor_run_max: np.ndarray = field(init=False)
    _at_limit: np.ndarray = field(init=False)
    _limit_run: np.ndarray = field(init=False)
    _limit_run_max: np.ndarray = field(init=False)
    _used_sum: np.ndarray = field(init=False)
    _rationed_sum: np.ndarray = field(init=False)
    _fee_sum: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        shape = (self.batch_size, 3)
        for name in ("_log_return_sum", "_log_return_sumsq", "_log_return_absmax",
                     "_at_floor", "_floor_run", "_floor_run_max",
                     "_at_limit", "_limit_run", "_limit_run_max",
                     "_used_sum", "_rationed_sum", "_fee_sum"):
            setattr(self, name, np.zeros(shape))

    def update(self, fees, previous_fees, used, offered, limits) -> None:
        self.blocks += 1
        ret = np.log(np.maximum(fees, 1e-30) / np.maximum(previous_fees, 1e-30))
        self._log_return_sum += ret
        self._log_return_sumsq += ret * ret
        np.maximum(self._log_return_absmax, np.abs(ret), out=self._log_return_absmax)

        floor = fees <= MIN_BASE_FEE_PER_GAS
        self._at_floor += floor
        self._floor_run = np.where(floor, self._floor_run + 1, 0)
        np.maximum(self._floor_run_max, self._floor_run, out=self._floor_run_max)

        at_limit = offered >= limits - 1e-9
        self._at_limit += at_limit
        self._limit_run = np.where(at_limit, self._limit_run + 1, 0)
        np.maximum(self._limit_run_max, self._limit_run, out=self._limit_run_max)

        self._used_sum += used
        self._rationed_sum += np.maximum(offered - used, 0.0)
        self._fee_sum += fees

    def to_dict(self) -> dict[str, np.ndarray]:
        n = max(self.blocks, 1)
        mean = self._log_return_sum / n
        var = np.maximum(self._log_return_sumsq / n - mean * mean, 0.0)
        return {
            "log_return_sd": np.sqrt(var),
            "log_return_absmax": self._log_return_absmax,
            "floor_fraction": self._at_floor / n,
            "longest_floor_run": self._floor_run_max,
            "limit_hit_fraction": self._at_limit / n,
            "longest_limit_run": self._limit_run_max,
            "mean_used": self._used_sum / n,
            "mean_rationed": self._rationed_sum / n,
            "mean_fee_wei": self._fee_sum / n,
        }


def run_batch(
    config: BatchConfig,
    shocks: np.ndarray,
    initial_base_fee_wei: np.ndarray,
    burn_in: int = 0,
    return_paths: bool = False,
) -> dict[str, np.ndarray]:
    """Advance every trajectory through ``shocks`` and return online summaries.

    ``shocks`` has shape (B, T, 4) as multiplicative factors ordered
    (execution, data, state, access). ``initial_base_fee_wei`` is (B, 3) and
    defines the warm or cold start.
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
        g_bal = (
            config.w_execution * config.q_execution_0 * execution_ratio ** config.rho_A
            + config.w_state * q_state
        ) * a_access

        offered = np.stack([
            config.m_execution * q_execution,
            g_static + g_bal,
            config.m_state * q_state,
        ], axis=1)
        used = np.minimum(offered, limits)

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
            summary.update(fees, previous_fees, used, offered, limits)
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
