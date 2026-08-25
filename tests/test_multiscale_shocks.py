import numpy as np
import pandas as pd
import pytest

from dynamics.multiscale_shocks import (
    DailyFactorDraws,
    compose_full_multiscale_paths,
    sample_daily_factors,
)


def test_daily_sampler_preserves_joint_consecutive_rows():
    panel = pd.DataFrame(
        {
            "execution": np.arange(1, 9, dtype=float),
            "data": np.arange(101, 109, dtype=float),
            "state": np.arange(201, 209, dtype=float),
        }
    )
    draws = sample_daily_factors(
        panel,
        n_paths=3,
        n_days=4,
        block_length=2,
        rng=np.random.default_rng(7),
    )

    assert draws.factors.shape == (3, 4, 3)
    assert np.all(np.diff(draws.source_positions.reshape(3, 2, 2), axis=2) == 1)
    assert draws.factors[:, :, 1] == pytest.approx(draws.factors[:, :, 0] + 100)
    assert draws.factors[:, :, 2] == pytest.approx(draws.factors[:, :, 0] + 200)


def test_multiscale_composition_keeps_access_fast_and_does_not_path_normalize():
    fast = np.ones((1, 48, 4))
    fast[:, :, 3] = 1.25
    hourly = pd.DataFrame(
        {
            "execution": np.r_[np.full(12, 0.5), np.full(12, 1.5)],
            "data": np.ones(24),
            "state": np.ones(24),
        },
        index=np.arange(24),
    )
    daily = DailyFactorDraws(
        factors=np.array([[[2.0, 3.0, 4.0], [2.0, 3.0, 4.0]]]),
        source_positions=np.array([[0, 1]]),
    )

    workload = compose_full_multiscale_paths(
        fast,
        hourly,
        daily,
        blocks_per_day=24,
    )

    assert workload[0, :12, 0] == pytest.approx(1.0)
    assert workload[0, 12:24, 0] == pytest.approx(3.0)
    assert workload[0, :, 0].mean() == pytest.approx(2.0)
    assert np.all(workload[:, :, 3] == 1.25)
