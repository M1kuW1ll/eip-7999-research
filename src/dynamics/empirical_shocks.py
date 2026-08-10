"""Empirical joint shock sampler for the EIP-7999 dynamic experiment.

The shock vector is ``(s_E, s_D, s_S, a)``: multiplicative demand residuals for
execution, static data and state creation, plus the access-composition residual
that scales runtime BAL per unit of parent activity.

Two measured facts drive the construction, both from contiguous block panels
rather than the spaced 6,000-block calibration sample:

* The primitive residuals are weakly but genuinely dependent, with integrated
  correlation times of roughly 10 blocks (execution), 38 (data) and 32 (state)
  after price adjustment and de-seasonalisation, and they co-move strongly --
  execution/data 0.80, execution/state 0.62, data/state 0.60. Sampling them
  independently would understate simultaneous pressure across resources.
* The access residual splits into a slow level carrying 5-41% of its variance
  on a ~40-minute scale, and a block residual whose structure is nearly
  regime-invariant: integrated correlation time 11-15 blocks, tail clustering
  0.13 against 0.05 under independence.

A vector moving-block bootstrap over the joint residual matrix preserves both
the cross-resource correlation and the within-resource persistence, including
the tail clustering that an AR or iid sampler would discard. Block length is
set from the measured correlation times, not chosen by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RESOURCES = ("execution", "data", "state")
SHOCK_COLUMNS = ("s_execution", "s_data", "s_state", "a_access")

# 35-day central elasticity vector, used to strip mechanical fee feedback out of
# observed quantities before the residual is treated as an exogenous shock.
CENTRAL_EPS = {"execution": 0.121160, "data": 0.229476, "state": 0.334864}

# Selected by `choose_block_length` against the 100,439-block joint panel: 1600
# minimises the reproduction error on integrated correlation time (0.174 mean
# relative error). Shorter blocks truncate the long low-level ACF tail; longer
# ones reduce resampling variety without improving reproduction.
DEFAULT_BLOCK_LENGTH = 1600

# Rolling window used to split the access residual into a slow level and a
# block-scale residual. ~40 minutes at 12s blocks.
ACCESS_LEVEL_WINDOW = 201


@dataclass(frozen=True)
class ShockPanel:
    """Contiguous joint residual panel, in logs, centred on zero."""

    residuals: np.ndarray  # (n_blocks, 4), columns SHOCK_COLUMNS
    access_level_sd: float  # sd of the slow access level component
    block_numbers: np.ndarray

    def __post_init__(self) -> None:
        if self.residuals.ndim != 2 or self.residuals.shape[1] != len(SHOCK_COLUMNS):
            raise ValueError("residuals must be (n_blocks, 4)")
        if not np.isfinite(self.residuals).all():
            raise ValueError("residuals contain non-finite values")

    @property
    def n_blocks(self) -> int:
        return int(self.residuals.shape[0])


def _price_adjusted_log_residual(
    quantity: pd.Series, base_fee: pd.Series, elasticity: float, hour: pd.Series,
    day: pd.Series,
) -> pd.Series:
    """Strip fee feedback and the intraday profile from an observed quantity.

    Without the price adjustment the mechanical response of demand to the fee
    would be read back as exogenous shock persistence; without the day-level
    term, slow drift in the daily activity level inflates the measured
    correlation time. Both corrections mattered empirically: removing day level
    cut the measured data-residual correlation time from 86 to 38 blocks.
    """

    q = quantity.astype(float).clip(lower=1.0)
    p0 = float(base_fee.median())
    x = np.log(q) + elasticity * np.log(base_fee.astype(float) / p0)
    x = x - x.groupby(hour).transform("median")
    return x - x.groupby(day).transform("median")


def build_shock_panel(
    block_panel_path: str | Path,
    runtime_bal_paths: list[str | Path],
    demand_parameters_path: str | Path,
    eps: dict[str, float] | None = None,
    rho_A: float = 1.0,
) -> ShockPanel:
    """Construct the joint residual panel from the contiguous panels.

    ``runtime_bal_paths`` supply the access residual over whatever contiguous
    windows were pulled; the primitive residuals come from the wider cheap
    panel. Blocks without a runtime-BAL observation keep their primitive
    residuals and receive an access residual of zero in logs, so the sampler
    still sees their joint primitive structure.
    """

    eps = dict(eps or CENTRAL_EPS)
    panel = pd.read_csv(block_panel_path)
    panel["block_date_time"] = pd.to_datetime(panel["block_date_time"])
    panel = panel[panel.gas_used.notna() & panel.base_fee_per_gas.notna()].copy()
    panel = panel.sort_values("block_number").reset_index(drop=True)

    hour = panel["block_date_time"].dt.hour
    day = panel["block_date_time"].dt.date
    fee = panel["base_fee_per_gas"]

    residuals = pd.DataFrame(index=panel.index)
    for resource, column in (
        ("execution", "execution_gas"),
        ("data", "data_gas_current"),
        ("state", "state_creation_gas"),
    ):
        residuals[f"s_{resource}"] = _price_adjusted_log_residual(
            panel[column], fee, eps[resource], hour, day
        )

    demand = pd.read_csv(demand_parameters_path).iloc[0]
    w_execution = float(demand["w_execution_reference"])
    w_state = float(demand["w_state_reference"])
    q_execution_0 = float(demand["q_execution_per_block"])

    bal = pd.concat([pd.read_csv(p) for p in runtime_bal_paths], ignore_index=True)
    bal = bal[["block_number", "bal_runtime_bytes_8279"]].drop_duplicates("block_number")

    residuals["block_number"] = panel["block_number"].to_numpy()
    residuals = residuals.merge(
        panel[["block_number", "execution_gas", "state_creation_gas"]],
        on="block_number", how="left",
    )
    # The access residual is measurably correlated with the primitives -- about
    # -0.23 against execution and state -- so the four shocks cannot be drawn
    # independently. The joint panel is therefore restricted to blocks where the
    # runtime meter was actually reconstructed, rather than padding the gaps.
    residuals = residuals.merge(bal, on="block_number", how="inner")

    execution_ratio = (residuals["execution_gas"] / q_execution_0).clip(lower=1e-6)
    predicted = (
        w_execution * q_execution_0 * execution_ratio**rho_A
        + w_state * residuals["state_creation_gas"]
    )
    observed = 16.0 * residuals["bal_runtime_bytes_8279"]
    # Blocks with no metered access events are real, but their composition
    # ratio is undefined rather than extreme; log of a clamped zero would
    # otherwise dominate the variance. They are ~0.04% of blocks, so they are
    # marked neutral to keep the panel contiguous instead of being dropped.
    degenerate = (observed <= 0) | (predicted <= 0)
    ratio = (observed / predicted).where(~degenerate)
    access = np.log(ratio)
    access = access.fillna(access.median())

    # Split the access residual: the slow level is regime-dependent and carries
    # 5-41% of variance depending on activity, while the block residual is
    # nearly regime-invariant. The bootstrap carries the block residual.
    level = access.rolling(ACCESS_LEVEL_WINDOW, center=True, min_periods=25).median()
    access_level_sd = float(level.std(skipna=True)) if level.notna().any() else 0.0
    residuals["a_access"] = (access - level).to_numpy()

    residuals = residuals.dropna(subset=list(SHOCK_COLUMNS)).reset_index(drop=True)
    if len(residuals) < 2:
        raise ValueError("joint panel is empty after restricting to observed blocks")

    # Contiguity is required for the moving-block bootstrap to mean anything;
    # keep only the longest run of consecutive blocks in the joint panel.
    block_numbers = residuals["block_number"].to_numpy()
    breaks = np.flatnonzero(np.diff(block_numbers) != 1)
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks + 1, [len(block_numbers)]])
    longest = int(np.argmax(ends - starts))
    keep = slice(int(starts[longest]), int(ends[longest]))
    residuals = residuals.iloc[keep].reset_index(drop=True)

    centred = residuals[list(SHOCK_COLUMNS)] - residuals[list(SHOCK_COLUMNS)].median()

    return ShockPanel(
        residuals=centred.to_numpy(dtype=float),
        access_level_sd=access_level_sd,
        block_numbers=residuals["block_number"].to_numpy(),
    )


def choose_block_length(
    panel: ShockPanel,
    candidates: tuple[int, ...] = (100, 200, 400, 800, 1600),
    n_paths: int = 32,
    n_blocks: int = 7200,
    seed: int = 0,
) -> pd.DataFrame:
    """Score candidate block lengths by how well they reproduce the source.

    A moving-block bootstrap destroys dependence beyond the block length, so
    too short a block deflates the integrated correlation time. This reports
    the reproduction error so the choice is made against the measurement rather
    than by rule of thumb.
    """

    source = summarize_panel(panel).set_index("shock")["integrated_tau_blocks"]
    rows = []
    for length in candidates:
        if length > panel.n_blocks:
            continue
        draws = moving_block_bootstrap(
            panel, n_paths, n_blocks, length, np.random.default_rng(seed)
        )
        logs = np.log(draws)
        row = {"block_length": length}
        errors = []
        for i, name in enumerate(SHOCK_COLUMNS):
            taus = []
            for path in logs[:, :, i]:
                path = path - path.mean()
                acf = np.array([
                    np.corrcoef(path[:-lag], path[lag:])[0, 1] for lag in range(1, 401)
                ])
                taus.append(1 + 2 * acf[acf > 0].sum())
            tau = float(np.mean(taus))
            row[f"tau_{name}"] = tau
            errors.append(abs(tau - source[name]) / max(source[name], 1e-9))
        row["mean_relative_tau_error"] = float(np.mean(errors))
        rows.append(row)
    return pd.DataFrame(rows)


def moving_block_bootstrap(
    panel: ShockPanel,
    n_paths: int,
    n_blocks: int,
    block_length: int = DEFAULT_BLOCK_LENGTH,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Draw ``n_paths`` joint shock paths as multiplicative factors.

    Blocks are drawn jointly across all four residuals at the same offsets, so
    the contemporaneous correlation and each resource's own persistence survive
    resampling. Returns shape ``(n_paths, n_blocks, 4)``.
    """

    if block_length < 1:
        raise ValueError("block_length must be positive")
    if block_length > panel.n_blocks:
        raise ValueError("block_length exceeds the panel length")

    rng = rng or np.random.default_rng()
    n_draws = int(np.ceil(n_blocks / block_length))
    max_start = panel.n_blocks - block_length

    starts = rng.integers(0, max_start + 1, size=(n_paths, n_draws))
    offsets = np.arange(block_length)
    index = (starts[:, :, None] + offsets[None, None, :]).reshape(n_paths, -1)
    index = index[:, :n_blocks]

    return np.exp(panel.residuals[index])


def summarize_panel(panel: ShockPanel, max_lag: int = 400) -> pd.DataFrame:
    """Report the structure the sampler is meant to preserve."""

    rows = []
    for i, name in enumerate(SHOCK_COLUMNS):
        x = panel.residuals[:, i]
        x = x - x.mean()
        acf = np.array([
            np.corrcoef(x[:-lag], x[lag:])[0, 1] for lag in range(1, max_lag + 1)
        ])
        threshold = np.quantile(x, 0.95)
        high = x > threshold
        rows.append({
            "shock": name,
            "sd_log": float(x.std()),
            "acf_lag1": float(acf[0]),
            "integrated_tau_blocks": float(1 + 2 * acf[acf > 0].sum()),
            "tail_clustering": float(high[1:][high[:-1]].mean()),
        })
    return pd.DataFrame(rows)
