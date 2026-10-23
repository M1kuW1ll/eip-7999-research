"""Final paper criteria, distinct from the retained exploratory workflow."""
from pathlib import Path
import runpy

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'reproducibility/reproduce.py'))


def test_strict_selection_has_no_tolerance_or_deviation_filter():
    cases = pd.DataFrame({
        'propagation_time_s': [3.] * 4,
        'included_execution': [100., 400., 200., 300.],
        'any_near_limit_fraction': [.047, .048, .04, .04],
        'unconstrained_equilibrium_execution_base_fee_wei': [2., 2., 2., 1.],
        'execution_mean_absolute_target_deviation': [0., 0., 999., 0.],
    })
    selected = MODULE['select'](cases, .047, conservative=True)
    assert selected.included_execution.tolist() == [200.]
    assert MODULE['select'](cases, .047, conservative=False).included_execution.tolist() == [400.]


def test_paper_grid_excludes_d77_and_targets_at_limits():
    cases = pd.DataFrame({
        'propagation_time_s': [3.] * 3,
        'execution_target': [300e6] * 3,
        'data_target': [67.5e6, 77e6, 80e6],
        'execution_limit': [600e6] * 3,
        'data_limit': [80e6] * 3,
    })
    assert MODULE['paper_grid'](cases).data_target.tolist() == [67.5e6]


@pytest.mark.parametrize('window', [21, 35, 60, 75])
def test_paper_conservative_reference_uses_strict_ceiling(window):
    reference = pd.read_csv(ROOT / 'reproducibility/reference/elasticity_conservative.csv')
    selected = reference[reference.window_days.eq(window)]
    assert len(selected) == 5
    assert selected.any_near_limit_fraction.le(.0473442920145728).all()
    assert selected.unconstrained_equilibrium_execution_base_fee_wei.gt(1 + 1e-6).all()
    assert selected.gain_M.gt(0).all()


def test_paired_paper_comparison_keeps_two_negative_conservative_paths():
    paired = pd.read_csv(ROOT / 'reproducibility/reference/paired_paths.csv')
    group = paired[paired.comparison.eq('conservative') & paired.propagation_time_s.eq(3)]
    assert len(group) == 32
    assert group.execution_gain_gas.lt(0).sum() == 2
    np.testing.assert_allclose(group.execution_gain_gas.mean() / 1e6, 6.789570206, rtol=1e-9)
