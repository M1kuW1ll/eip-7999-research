"""Multiscale workload construction for the dynamic EIP-7999 experiment.

The fast shock panel in :mod:`dynamics.empirical_shocks` deliberately removes
the recurring UTC-hour profile and each calendar day's activity level.  This
module puts those components back explicitly:

    shock[i, t] = daily[i, day(t)] * hourly[i, hour(t)] * fast[i, t]

The factors are normalized at the *source-distribution* level.  Individual
simulated paths are not normalized back to one, so a path that happens to draw
several busy days remains a busy path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .empirical_shocks import (
    CENTRAL_EPS,
    ShockPanel,
    build_shock_panel,
    moving_block_bootstrap,
)

PRIMITIVE_RESOURCES = ("execution", "data", "state")


@dataclass(frozen=True)
class DailyFactorDraws:
    """Joint daily-factor paths and their source-row positions."""

    factors: np.ndarray  # (n_paths, n_days, 3)
    source_positions: np.ndarray  # (n_paths, n_days)

    def __post_init__(self) -> None:
        if self.factors.ndim != 3 or self.factors.shape[2] != 3:
            raise ValueError("daily factors must have shape (n_paths, n_days, 3)")
        if self.source_positions.shape != self.factors.shape[:2]:
            raise ValueError("daily source positions must match the factor paths")
        if not np.isfinite(self.factors).all() or np.any(self.factors <= 0):
            raise ValueError("daily factors must be finite and positive")


@dataclass(frozen=True)
class FullMultiscaleWorkload:
    """Canonical multiscale workload and its measured source components."""

    fast_panel: ShockPanel
    fast_paths: np.ndarray
    hourly_profile: pd.DataFrame
    daily_panel: pd.DataFrame
    daily_draws: DailyFactorDraws
    paths: np.ndarray


def _price_adjusted_log_activity(
    frame: pd.DataFrame,
    eps: dict[str, float],
) -> pd.DataFrame:
    """Return block-level log activity after removing the observed fee response."""

    required = {
        "block_date_time",
        "base_fee_per_gas",
        "execution_gas",
        "data_gas_current",
        "state_creation_gas",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"block panel is missing columns: {sorted(missing)}")

    fee = pd.to_numeric(frame["base_fee_per_gas"], errors="coerce").astype(float)
    if not np.isfinite(fee).all() or (fee <= 0).any():
        raise ValueError("base fees must be finite and positive")
    reference_fee = float(fee.median())

    out = pd.DataFrame(index=frame.index)
    for resource, column in (
        ("execution", "execution_gas"),
        ("data", "data_gas_current"),
        ("state", "state_creation_gas"),
    ):
        quantity = pd.to_numeric(frame[column], errors="coerce").astype(float).clip(lower=1.0)
        if not np.isfinite(quantity).all():
            raise ValueError(f"{column} must be finite")
        out[resource] = np.log(quantity) + float(eps[resource]) * np.log(
            fee / reference_fee
        )
    return out


def build_hourly_profile(
    block_panel_path: str | Path,
    eps: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Estimate the recurring price-adjusted UTC-hour profile.

    This matches the first detrending step in ``build_shock_panel``: take the
    median log activity for each UTC hour.  Each resource profile is normalized
    to have arithmetic mean one over the 24 simulated hours.
    """

    eps = dict(eps or CENTRAL_EPS)
    frame = pd.read_csv(block_panel_path)
    frame["block_date_time"] = pd.to_datetime(frame["block_date_time"])
    frame = frame.sort_values("block_date_time").reset_index(drop=True)
    log_activity = _price_adjusted_log_activity(frame, eps)
    hour = frame["block_date_time"].dt.hour
    log_profile = log_activity.groupby(hour).median().reindex(range(24))
    if log_profile.isna().any().any():
        raise ValueError("the block panel does not cover every UTC hour")

    # Subtracting the column maximum before exponentiating is numerically
    # neutral because each column is subsequently normalized.
    shifted = log_profile - log_profile.max(axis=0)
    profile = np.exp(shifted)
    profile = profile / profile.mean(axis=0)
    profile.index.name = "utc_hour"
    return profile.loc[:, list(PRIMITIVE_RESOURCES)]


def source_round_trip_diagnostics(
    block_panel_path: str | Path,
    eps: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Check that hour, day, and fast terms reconstruct block log activity.

    The daily term in this diagnostic is the local day effect from the contiguous
    block panel. The simulation replaces that local distribution with the longer
    daily panel, but the identity verifies that the sequential decomposition
    itself neither drops nor double-counts block-panel activity.
    """

    eps = dict(eps or CENTRAL_EPS)
    frame = pd.read_csv(block_panel_path)
    frame["block_date_time"] = pd.to_datetime(frame["block_date_time"])
    frame = frame.sort_values("block_date_time").reset_index(drop=True)
    log_activity = _price_adjusted_log_activity(frame, eps)
    hour = frame["block_date_time"].dt.hour
    day = frame["block_date_time"].dt.date
    rows: list[dict[str, float | str]] = []
    for resource in PRIMITIVE_RESOURCES:
        hourly_log = log_activity[resource].groupby(hour).transform("median")
        after_hour = log_activity[resource] - hourly_log
        daily_log = after_hour.groupby(day).transform("median")
        fast_log = after_hour - daily_log
        reconstructed = hourly_log + daily_log + fast_log
        error = reconstructed - log_activity[resource]
        rows.append(
            {
                "resource": resource,
                "observations": float(len(error)),
                "max_abs_log_reconstruction_error": float(np.abs(error).max()),
                "mean_abs_log_reconstruction_error": float(np.abs(error).mean()),
            }
        )
    return pd.DataFrame(rows)


def build_daily_factors(
    accounting_panel_path: str | Path,
    current_data_gas_path: str | Path,
    *,
    hourly_profile: pd.DataFrame,
    eps: dict[str, float] | None = None,
    trend_window: int = 21,
) -> pd.DataFrame:
    """Estimate joint slow daily conditions from the longer accounting panel.

    The daily quantities first have the maintained fee response removed.  A
    centered rolling median then removes secular movement over the 120-day
    source window, leaving busy/quiet-day factors.  Daily observations cover
    complete UTC days; because the recurring hourly profile is normalized to
    average one over 24 hours, its full-day aggregate is one and no second
    hourly adjustment is required here.
    """

    eps = dict(eps or CENTRAL_EPS)
    if trend_window <= 0 or trend_window % 2 == 0:
        raise ValueError("trend_window must be a positive odd integer")
    if not np.allclose(
        hourly_profile.loc[:, list(PRIMITIVE_RESOURCES)].mean(axis=0),
        1.0,
        rtol=0,
        atol=1e-12,
    ):
        raise ValueError("hourly profiles must average one before daily estimation")

    accounting = pd.read_csv(accounting_panel_path)
    historical_data = pd.read_csv(
        current_data_gas_path,
        usecols=["date", "data_gas_current"],
    )
    daily = accounting.merge(
        historical_data,
        on="date",
        how="inner",
        validate="one_to_one",
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").set_index("date")
    required = {
        "current_gas_used",
        "current_state_creation_gas_calibrated",
        "data_gas_current",
        "block_count",
        "median_base_fee_per_gas",
    }
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"daily accounting panel is missing columns: {sorted(missing)}")

    quantities = pd.DataFrame(index=daily.index)
    quantities["execution"] = (
        daily["current_gas_used"]
        - daily["data_gas_current"]
        - daily["current_state_creation_gas_calibrated"]
    ) / daily["block_count"]
    quantities["data"] = daily["data_gas_current"] / daily["block_count"]
    quantities["state"] = (
        daily["current_state_creation_gas_calibrated"] / daily["block_count"]
    )
    fees = pd.to_numeric(daily["median_base_fee_per_gas"], errors="coerce").astype(float)
    quantity_values = quantities.to_numpy(dtype=float)
    if (
        not np.isfinite(quantity_values).all()
        or np.any(quantity_values <= 0)
        or not np.isfinite(fees).all()
        or (fees <= 0).any()
    ):
        raise ValueError("daily quantities and fees must be finite and positive")

    reference_fee = float(fees.median())
    neutral_log = pd.DataFrame(index=daily.index)
    for resource in PRIMITIVE_RESOURCES:
        neutral_log[resource] = np.log(quantities[resource]) + float(eps[resource]) * np.log(
            fees / reference_fee
        )
    minimum = (trend_window + 1) // 2
    trend = neutral_log.rolling(
        window=trend_window,
        center=True,
        min_periods=minimum,
    ).median()
    if trend.isna().any().any():
        raise ValueError("not enough daily observations for the trend window")
    factors = np.exp(neutral_log - trend)
    factors = factors / factors.mean(axis=0)
    factors.index.name = "date"
    return factors.loc[:, list(PRIMITIVE_RESOURCES)]


def sample_daily_factors(
    panel: pd.DataFrame,
    *,
    n_paths: int,
    n_days: int,
    block_length: int,
    rng: np.random.Generator,
) -> DailyFactorDraws:
    """Draw joint daily factors in contiguous, non-circular multi-day strips."""

    values = panel.loc[:, list(PRIMITIVE_RESOURCES)].to_numpy(dtype=float)
    if n_paths <= 0 or n_days <= 0:
        raise ValueError("n_paths and n_days must be positive")
    if block_length <= 0 or block_length > len(values):
        raise ValueError("daily block length must fit inside the source panel")

    draws_per_path = int(np.ceil(n_days / block_length))
    max_start = len(values) - block_length
    starts = rng.integers(0, max_start + 1, size=(n_paths, draws_per_path))
    offsets = np.arange(block_length)
    positions = (starts[:, :, None] + offsets[None, None, :]).reshape(n_paths, -1)
    positions = positions[:, :n_days]
    return DailyFactorDraws(factors=values[positions], source_positions=positions)


def score_daily_block_lengths(
    panel: pd.DataFrame,
    *,
    candidates: tuple[int, ...] = (1, 2, 3, 5, 7, 8),
    n_paths: int = 4_096,
    n_days: int = 8,
    seed: int = 42,
) -> pd.DataFrame:
    """Score daily strip lengths by reproduction of lag-one log correlation."""

    source = np.log(panel.loc[:, list(PRIMITIVE_RESOURCES)].to_numpy(dtype=float))
    source_lag_one = np.array(
        [
            np.corrcoef(source[:-1, index], source[1:, index])[0, 1]
            for index in range(3)
        ]
    )
    rows: list[dict[str, float]] = []
    for block_length in candidates:
        draws = sample_daily_factors(
            panel,
            n_paths=n_paths,
            n_days=n_days,
            block_length=block_length,
            rng=np.random.default_rng(seed),
        )
        logs = np.log(draws.factors)
        reproduced = np.array(
            [
                np.corrcoef(
                    logs[:, :-1, index].ravel(),
                    logs[:, 1:, index].ravel(),
                )[0, 1]
                for index in range(3)
            ]
        )
        row: dict[str, float] = {"daily_block_length": float(block_length)}
        for index, resource in enumerate(PRIMITIVE_RESOURCES):
            row[f"source_lag1_{resource}"] = float(source_lag_one[index])
            row[f"reproduced_lag1_{resource}"] = float(reproduced[index])
        row["mean_abs_lag1_error"] = float(
            np.mean(np.abs(reproduced - source_lag_one))
        )
        rows.append(row)
    return pd.DataFrame(rows)


def compose_full_multiscale_paths(
    fast_paths: np.ndarray,
    hourly_profile: pd.DataFrame,
    daily_draws: DailyFactorDraws,
    *,
    blocks_per_day: int = 7_200,
) -> np.ndarray:
    """Compose the full daily x hourly x fast workload.

    The fourth column is the fast access-composition residual.  The first
    multiscale experiment intentionally leaves it unchanged; only the three
    primitive demand shocks receive daily and hourly factors.
    """

    fast = np.asarray(fast_paths, dtype=float)
    if fast.ndim != 3 or fast.shape[2] != 4:
        raise ValueError("fast paths must have shape (n_paths, n_blocks, 4)")
    if not np.isfinite(fast).all() or np.any(fast <= 0):
        raise ValueError("fast paths must be finite and positive")
    if blocks_per_day <= 0 or blocks_per_day % 24 != 0:
        raise ValueError("blocks_per_day must be positive and divisible by 24")
    n_paths, n_blocks, _ = fast.shape
    if n_blocks % blocks_per_day != 0:
        raise ValueError("the synthetic path must contain a whole number of days")
    n_days = n_blocks // blocks_per_day
    if daily_draws.factors.shape != (n_paths, n_days, 3):
        raise ValueError("daily draws do not match the fast paths")

    hourly = hourly_profile.reindex(range(24)).loc[:, list(PRIMITIVE_RESOURCES)]
    hourly_values = hourly.to_numpy(dtype=float)
    if not np.isfinite(hourly_values).all() or np.any(hourly_values <= 0):
        raise ValueError("hourly factors must be finite and positive")
    blocks_per_hour = blocks_per_day // 24
    one_day = np.repeat(hourly_values, blocks_per_hour, axis=0)
    hourly_path = np.tile(one_day, (n_days, 1))[None, :, :]
    daily_path = np.repeat(daily_draws.factors, blocks_per_day, axis=1)

    path = fast.copy()
    path[:, :, :3] = fast[:, :, :3] * hourly_path * daily_path
    return path


def build_full_multiscale_workload(
    *,
    block_panel_path: str | Path,
    runtime_bal_paths: list[str | Path],
    demand_parameters_path: str | Path,
    accounting_panel_path: str | Path,
    current_data_gas_path: str | Path,
    n_paths: int,
    n_blocks: int,
    fast_block_length: int,
    daily_block_length: int,
    fast_seed: int,
    daily_seed: int,
    blocks_per_day: int = 7_200,
    eps: dict[str, float] | None = None,
    rho_A: float = 1.0,
    trend_window: int = 21,
) -> FullMultiscaleWorkload:
    """Build one shared full-multiscale workload for all replay mechanisms.

    Keeping this construction in one function prevents target-grid, slot-time,
    and mechanism-comparison scripts from silently using different source
    panels, bootstrap seeds, or fast-only shocks.
    """

    eps = dict(eps or CENTRAL_EPS)
    if n_blocks % blocks_per_day != 0:
        raise ValueError("n_blocks must contain a whole number of simulated days")
    fast_panel = build_shock_panel(
        block_panel_path,
        runtime_bal_paths,
        demand_parameters_path,
        eps=eps,
        rho_A=rho_A,
    )
    fast_paths = moving_block_bootstrap(
        fast_panel,
        n_paths,
        n_blocks,
        fast_block_length,
        np.random.default_rng(fast_seed),
    )
    hourly_profile = build_hourly_profile(block_panel_path, eps=eps)
    daily_panel = build_daily_factors(
        accounting_panel_path,
        current_data_gas_path,
        hourly_profile=hourly_profile,
        eps=eps,
        trend_window=trend_window,
    )
    daily_draws = sample_daily_factors(
        daily_panel,
        n_paths=n_paths,
        n_days=n_blocks // blocks_per_day,
        block_length=daily_block_length,
        rng=np.random.default_rng(daily_seed),
    )
    paths = compose_full_multiscale_paths(
        fast_paths,
        hourly_profile,
        daily_draws,
        blocks_per_day=blocks_per_day,
    )
    return FullMultiscaleWorkload(
        fast_panel=fast_panel,
        fast_paths=fast_paths,
        hourly_profile=hourly_profile,
        daily_panel=daily_panel,
        daily_draws=daily_draws,
        paths=paths,
    )


def summarize_workload_paths(paths: np.ndarray) -> pd.DataFrame:
    """Summarize the full simulated shock distribution before mechanism replay."""

    rows: list[dict[str, float | str]] = []
    for index, resource in enumerate((*PRIMITIVE_RESOURCES, "access")):
        values = np.asarray(paths[:, :, index], dtype=float).ravel()
        rows.append(
            {
                "workload": "full_multiscale",
                "shock": resource,
                "mean": float(values.mean()),
                "median": float(np.median(values)),
                "p05": float(np.quantile(values, 0.05)),
                "p95": float(np.quantile(values, 0.95)),
                "p99": float(np.quantile(values, 0.99)),
                "log_sd": float(np.std(np.log(values), ddof=1)),
            }
        )
    return pd.DataFrame(rows)
