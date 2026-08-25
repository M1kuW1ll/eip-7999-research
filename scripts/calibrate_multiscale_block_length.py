"""Calibrate the fast moving-block length on the 60-day joint shock panel.

The primary diagnostic is reproduction of integrated autocorrelation time.  ACF
shape, lagged cross-resource dependence, and clustered upper-tail observations
are retained as separate validation diagnostics rather than folded into an
opaque weighted score.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dynamics.empirical_shocks import (  # noqa: E402
    SHOCK_COLUMNS,
    build_shock_panel,
    moving_block_bootstrap,
)
from run_multiscale_design_surface import (  # noqa: E402
    BLOCK_PANEL,
    BURN_IN,
    DEMAND_PARAMETERS,
    EPS,
    MEASURE_BLOCKS,
    N_SEEDS,
    REPORT_SHOCK_SEED,
    RUNTIME_BAL_PANELS,
)

CANDIDATES = (400, 800, 1_600, 3_200, 6_400)
DIAGNOSTIC_LAGS = (1, 5, 20, 50, 100, 200, 400)
MAX_TAU_LAG = 1_600


def autocorrelation(values: np.ndarray, max_lag: int) -> np.ndarray:
    """Unbiased FFT autocorrelation through ``max_lag``."""

    x = np.asarray(values, dtype=float)
    x = x - x.mean()
    n = len(x)
    if max_lag >= n:
        raise ValueError("max_lag must be smaller than the input")
    n_fft = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(x, n=n_fft)
    covariance = np.fft.irfft(spectrum * np.conjugate(spectrum), n=n_fft)
    covariance = covariance[: max_lag + 1] / np.arange(n, n - max_lag - 1, -1)
    if covariance[0] <= 0:
        return np.concatenate([[1.0], np.zeros(max_lag)])
    return covariance / covariance[0]


def integrated_tau(acf: np.ndarray) -> float:
    """Geyer initial-positive-sequence estimate of integrated correlation time."""

    tau = 1.0
    for start in range(1, len(acf) - 1, 2):
        pair = float(acf[start] + acf[start + 1])
        if pair <= 0:
            break
        tau += 2.0 * pair
    return max(tau, 1.0)


def lagged_correlation(left: np.ndarray, right: np.ndarray, lag: int) -> float:
    if lag == 0:
        return float(np.corrcoef(left, right)[0, 1])
    return float(np.corrcoef(left[:-lag], right[lag:])[0, 1])


def tail_conditional(values: np.ndarray, threshold: float, lag: int) -> float:
    high = values > threshold
    conditioning = high[:-lag]
    if not conditioning.any():
        return np.nan
    return float(high[lag:][conditioning].mean())


def main() -> None:
    panel = build_shock_panel(
        BLOCK_PANEL,
        list(RUNTIME_BAL_PANELS),
        DEMAND_PARAMETERS,
        eps=EPS,
    )
    total_blocks = BURN_IN + MEASURE_BLOCKS
    source = panel.residuals
    thresholds = np.quantile(source, 0.95, axis=0)

    source_tau: dict[str, float] = {}
    source_acf: dict[tuple[str, int], float] = {}
    source_tail: dict[tuple[str, int], float] = {}
    for index, shock in enumerate(SHOCK_COLUMNS):
        acf = autocorrelation(source[:, index], MAX_TAU_LAG)
        source_tau[shock] = integrated_tau(acf)
        for lag in DIAGNOSTIC_LAGS:
            source_acf[(shock, lag)] = float(acf[lag])
            source_tail[(shock, lag)] = tail_conditional(
                source[:, index], thresholds[index], lag
            )

    pairs = list(combinations(range(len(SHOCK_COLUMNS)), 2))
    source_cross = {
        (SHOCK_COLUMNS[left], SHOCK_COLUMNS[right], lag): lagged_correlation(
            source[:, left], source[:, right], lag
        )
        for left, right in pairs
        for lag in DIAGNOSTIC_LAGS
    }

    summary_rows: list[dict[str, float]] = []
    detail_rows: list[dict[str, float | str]] = []
    for length in CANDIDATES:
        paths = np.log(
            moving_block_bootstrap(
                panel,
                N_SEEDS,
                total_blocks,
                length,
                np.random.default_rng(REPORT_SHOCK_SEED),
            )
        )
        tau_errors: list[float] = []
        acf_errors: list[float] = []
        tail_errors: list[float] = []
        cross_errors: list[float] = []

        for index, shock in enumerate(SHOCK_COLUMNS):
            path_acfs = np.stack(
                [autocorrelation(path[:, index], MAX_TAU_LAG) for path in paths]
            )
            reproduced_tau = float(
                np.mean([integrated_tau(acf) for acf in path_acfs])
            )
            tau_error = abs(reproduced_tau - source_tau[shock]) / source_tau[shock]
            tau_errors.append(tau_error)
            detail_rows.append(
                {
                    "block_length": length,
                    "metric": "integrated_tau",
                    "shock": shock,
                    "lag": 0,
                    "source": source_tau[shock],
                    "reproduced": reproduced_tau,
                    "absolute_error": abs(reproduced_tau - source_tau[shock]),
                }
            )
            for lag in DIAGNOSTIC_LAGS:
                reproduced_acf = float(path_acfs[:, lag].mean())
                acf_error = abs(reproduced_acf - source_acf[(shock, lag)])
                acf_errors.append(acf_error)
                reproduced_tail = float(
                    np.nanmean(
                        [
                            tail_conditional(
                                path[:, index], thresholds[index], lag
                            )
                            for path in paths
                        ]
                    )
                )
                tail_error = abs(reproduced_tail - source_tail[(shock, lag)])
                tail_errors.append(tail_error)

        for left, right in pairs:
            for lag in DIAGNOSTIC_LAGS:
                reproduced = float(
                    np.mean(
                        [
                            lagged_correlation(path[:, left], path[:, right], lag)
                            for path in paths
                        ]
                    )
                )
                source_value = source_cross[
                    (SHOCK_COLUMNS[left], SHOCK_COLUMNS[right], lag)
                ]
                cross_errors.append(abs(reproduced - source_value))

        summary_rows.append(
            {
                "block_length": length,
                "source_blocks": panel.n_blocks,
                "simulated_paths": N_SEEDS,
                "blocks_per_path": total_blocks,
                "mean_relative_tau_error": float(np.mean(tau_errors)),
                "max_relative_tau_error": float(np.max(tau_errors)),
                "mean_acf_absolute_error": float(np.mean(acf_errors)),
                "mean_cross_lag_absolute_error": float(np.mean(cross_errors)),
                "mean_tail_conditional_absolute_error": float(np.mean(tail_errors)),
            }
        )
        print(f"block length {length:,} complete", flush=True)

    output = ROOT / "data/7999/fast_block_length_diagnostics_60d.csv"
    details = ROOT / "data/7999/fast_block_length_tau_details_60d.csv"
    pd.DataFrame(summary_rows).to_csv(output, index=False)
    pd.DataFrame(detail_rows).to_csv(details, index=False)
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print(f"wrote {output.relative_to(ROOT)}")
    print(f"wrote {details.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
