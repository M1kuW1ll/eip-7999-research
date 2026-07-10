"""Empirical joint demand shocks for driven resource-fee simulations.

Historical resource usage contains both a price response and variation in
underlying demand.  Given an own-price elasticity ``eps_i``, this module first
removes the estimated price response,

    y_it = q_it * (p_it / p_i_ref) ** eps_i,

then divides the price-neutral usage ``y_it`` by a slow baseline.  The resulting
positive shifters are normalized to have arithmetic mean one in each resource.

Bootstrap paths always resample the execution/data/state vector jointly.  This
preserves contemporaneous resource co-movement; contiguous source positions
also preserve within-window serial dependence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

import numpy as np
import pandas as pd

from .model import RESOURCES

Frequency = Literal["block", "day"]
ShockBasis = Literal["historical_physical", "7999_metered"]

_FREQUENCIES = {"block", "day"}
_BASES = {"historical_physical", "7999_metered"}


def _resource_mapping(
    values: Mapping[str, object], *, name: str
) -> None:
    missing = set(RESOURCES) - set(values)
    if missing:
        raise ValueError(f"{name} missing resources: {sorted(missing)}")


def _validate_metadata(frequency: str, basis: str, source: str) -> None:
    if frequency not in _FREQUENCIES:
        raise ValueError(f"unsupported shock frequency {frequency!r}")
    if basis not in _BASES:
        raise ValueError(f"unsupported shock basis {basis!r}")
    if not source:
        raise ValueError("shock source must be non-empty")


def _validated_values(values: pd.DataFrame) -> pd.DataFrame:
    missing = set(RESOURCES) - set(values.columns)
    if missing:
        raise ValueError(f"shock values missing resources: {sorted(missing)}")
    if len(values) == 0:
        raise ValueError("shock values must be non-empty")
    if not values.index.is_unique:
        raise ValueError("shock index must be unique")

    out = values.loc[:, list(RESOURCES)].apply(pd.to_numeric, errors="coerce")
    array = out.to_numpy(dtype=float)
    if not np.isfinite(array).all():
        raise ValueError("shock values must be finite")
    if (array <= 0).any():
        raise ValueError("shock values must be positive")
    return out.copy()


@dataclass(frozen=True)
class ShockEstimationSpec:
    """Column mapping and detrending choices for empirical shock estimation.

    ``usage_cols`` must already be expressed per observation (for example,
    gas per block rather than a daily gas total).  A string ``price_cols``
    means all resources faced the same historical price; a mapping supports
    separate historical prices.
    """

    time_col: str
    usage_cols: Mapping[str, str]
    price_cols: str | Mapping[str, str]
    elasticities: Mapping[str, float]
    frequency: Frequency
    basis: ShockBasis
    trend_window: int = 21

    def __post_init__(self) -> None:
        if not self.time_col:
            raise ValueError("time_col must be non-empty")
        _resource_mapping(self.usage_cols, name="usage_cols")
        _resource_mapping(self.elasticities, name="elasticities")
        if not isinstance(self.price_cols, str):
            _resource_mapping(self.price_cols, name="price_cols")
        elif not self.price_cols:
            raise ValueError("price_cols must be non-empty")

        for resource in RESOURCES:
            elasticity = float(self.elasticities[resource])
            if not np.isfinite(elasticity) or elasticity < 0:
                raise ValueError(
                    f"elasticity for {resource!r} must be finite and non-negative"
                )
        if self.trend_window <= 0 or self.trend_window % 2 == 0:
            raise ValueError("trend_window must be a positive odd integer")
        _validate_metadata(self.frequency, self.basis, "estimation_spec")


@dataclass(frozen=True)
class JointShockPanel:
    """Estimated joint shocks indexed by their source time."""

    values: pd.DataFrame
    frequency: Frequency
    basis: ShockBasis
    source: str

    def __post_init__(self) -> None:
        _validate_metadata(self.frequency, self.basis, self.source)
        clean = _validated_values(self.values)
        if not clean.index.is_monotonic_increasing:
            raise ValueError("shock panel index must be sorted")
        object.__setattr__(self, "values", clean)


@dataclass(frozen=True)
class JointShockPath:
    """A replay-ready sequence plus source-row positions for auditability."""

    values: pd.DataFrame
    frequency: Frequency
    basis: ShockBasis
    source: str
    source_positions: tuple[int, ...]

    def __post_init__(self) -> None:
        _validate_metadata(self.frequency, self.basis, self.source)
        clean = _validated_values(self.values.reset_index(drop=True))
        if len(self.source_positions) != len(clean):
            raise ValueError("source_positions length must match shock path")
        if any(position < 0 for position in self.source_positions):
            raise ValueError("source_positions must be non-negative")
        object.__setattr__(self, "values", clean.reset_index(drop=True))

    def require_block_frequency(self, *, step_seconds: int = 12) -> None:
        """Reject daily shocks before an exact per-block mechanism replay.

        Daily observations require an explicit daily-to-block disaggregation;
        silently repeating one daily vector across thousands of blocks would
        manufacture persistence and distort fee volatility.
        """

        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive")
        if self.frequency != "block":
            raise ValueError(
                f"{self.frequency}-frequency shocks cannot drive a "
                f"{step_seconds}-second block replay without explicit "
                "disaggregation"
            )


def _price_columns(spec: ShockEstimationSpec) -> dict[str, str]:
    if isinstance(spec.price_cols, str):
        return {resource: spec.price_cols for resource in RESOURCES}
    return {resource: spec.price_cols[resource] for resource in RESOURCES}


def _explicit_baseline(
    baseline: pd.DataFrame,
    *,
    time_col: str,
    target_index: pd.Index,
) -> pd.DataFrame:
    if time_col in baseline.columns:
        base = baseline.set_index(time_col)
    else:
        base = baseline.copy()
    if not base.index.is_unique:
        raise ValueError("baseline index must be unique")
    missing = set(RESOURCES) - set(base.columns)
    if missing:
        raise ValueError(f"baseline missing resources: {sorted(missing)}")
    base = base.reindex(target_index).loc[:, list(RESOURCES)]
    base = base.apply(pd.to_numeric, errors="coerce")
    array = base.to_numpy(dtype=float)
    if not np.isfinite(array).all() or (array <= 0).any():
        raise ValueError(
            "baseline must align to every shock time with finite positive values"
        )
    return base


def estimate_joint_shocks(
    frame: pd.DataFrame,
    spec: ShockEstimationSpec,
    *,
    baseline: pd.DataFrame | None = None,
    source: str = "estimated",
) -> JointShockPanel:
    """Estimate positive, unit-mean resource demand shifters.

    An explicit ``baseline`` is interpreted as price-neutral usage and must
    contain resource-named columns, aligned either by ``spec.time_col`` or by
    its index.  Without it, a centered rolling median of log price-neutral
    usage supplies the slow baseline.
    """

    _validate_metadata(spec.frequency, spec.basis, source)
    price_cols = _price_columns(spec)
    required = {spec.time_col}
    required.update(spec.usage_cols[resource] for resource in RESOURCES)
    required.update(price_cols.values())
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"shock input missing columns: {sorted(missing)}")

    work = frame.loc[:, sorted(required)].copy()
    if work[spec.time_col].duplicated().any():
        raise ValueError("shock times must be unique")
    work = work.sort_values(spec.time_col).set_index(spec.time_col)

    neutral_log = pd.DataFrame(index=work.index, columns=RESOURCES, dtype=float)
    for resource in RESOURCES:
        usage = pd.to_numeric(
            work[spec.usage_cols[resource]], errors="coerce"
        ).astype(float)
        price = pd.to_numeric(work[price_cols[resource]], errors="coerce").astype(
            float
        )
        usage_array = usage.to_numpy()
        price_array = price.to_numpy()
        if (
            not np.isfinite(usage_array).all()
            or not np.isfinite(price_array).all()
            or (usage_array <= 0).any()
            or (price_array <= 0).any()
        ):
            raise ValueError(
                f"usage and price for {resource!r} must be finite and positive"
            )
        reference_price = float(np.median(price_array))
        elasticity = float(spec.elasticities[resource])
        neutral_log[resource] = np.log(usage) + elasticity * np.log(
            price / reference_price
        )

    if baseline is None:
        minimum = (spec.trend_window + 1) // 2
        baseline_log = neutral_log.rolling(
            window=spec.trend_window,
            center=True,
            min_periods=minimum,
        ).median()
        if baseline_log.isna().any().any():
            raise ValueError(
                "not enough observations for the requested centered trend window"
            )
    else:
        explicit = _explicit_baseline(
            baseline,
            time_col=spec.time_col,
            target_index=work.index,
        )
        baseline_log = np.log(explicit)

    raw = np.exp(neutral_log - baseline_log)
    if not np.isfinite(raw.to_numpy()).all() or (raw.to_numpy() <= 0).any():
        raise ValueError("estimated shocks must be finite and positive")
    shocks = raw / raw.mean(axis=0)
    shocks.index.name = spec.time_col
    return JointShockPanel(
        values=shocks,
        frequency=spec.frequency,
        basis=spec.basis,
        source=source,
    )


def empirical_shock_path(
    panel: JointShockPanel,
    *,
    start: int = 0,
    length: int | None = None,
) -> JointShockPath:
    """Take an exact contiguous slice from an empirical shock panel."""

    if start < 0 or start >= len(panel.values):
        raise ValueError("start must select a row in the shock panel")
    if length is None:
        length = len(panel.values) - start
    if length <= 0 or start + length > len(panel.values):
        raise ValueError("length must select a non-empty in-bounds path")
    positions = tuple(range(start, start + length))
    values = panel.values.iloc[list(positions)].reset_index(drop=True)
    return JointShockPath(
        values=values,
        frequency=panel.frequency,
        basis=panel.basis,
        source=f"{panel.source}:empirical",
        source_positions=positions,
    )


def vector_moving_block_bootstrap(
    panel: JointShockPanel,
    *,
    n_steps: int,
    block_length: int,
    seed: int | None,
    circular: bool = True,
) -> JointShockPath:
    """Draw contiguous chunks of the full joint resource-shock vector."""

    source_length = len(panel.values)
    if n_steps <= 0:
        raise ValueError("n_steps must be positive")
    if block_length <= 0 or block_length > source_length:
        raise ValueError("block_length must be between 1 and the panel length")

    rng = np.random.default_rng(seed)
    positions: list[int] = []
    while len(positions) < n_steps:
        if circular:
            start = int(rng.integers(0, source_length))
        else:
            start = int(rng.integers(0, source_length - block_length + 1))
        take = min(block_length, n_steps - len(positions))
        if circular:
            chunk = [
                (start + offset) % source_length for offset in range(take)
            ]
        else:
            chunk = list(range(start, start + take))
        positions.extend(chunk)

    values = panel.values.iloc[positions].reset_index(drop=True)
    return JointShockPath(
        values=values,
        frequency=panel.frequency,
        basis=panel.basis,
        source=f"{panel.source}:moving_block_bootstrap",
        source_positions=tuple(positions),
    )
