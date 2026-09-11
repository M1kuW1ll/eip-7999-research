"""Focused report figures, unchanged-source diagnostics, and section scope."""
import hashlib
import json
from pathlib import Path
import runpy

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/shared_fee/eip8372'


def test_focused_figures_plot_all_fixed_vectors_and_reference_lines(monkeypatch):
    module = runpy.run_path(str(ROOT/'scripts/shared_fee/make_eip8372_figures.py'))
    normalized = pd.read_csv(DATA/'normalized_outcomes.csv')
    gains = pd.read_csv(DATA/'paired_gains.csv')
    for function, name in [
        ('fixed_calibration_performance_figure', 'fixed_calibration_performance'),
        ('fixed_design_execution_gain_figure', 'fixed_design_execution_gains'),
    ]:
        figures = []
        render = module[function]
        monkeypatch.setitem(render.__globals__, 'save', lambda fig, name: figures.append((fig, name)))
        render()
        fig, stem = figures[0]
        try:
            assert stem == f'shared_fee_eip8372_{name}'
            assert len(fig.axes) == 2
            assert [t.get_text() for t in fig.legends[0].get_texts()] == [f'{w}-day vector' for w in (21, 35, 60, 75)]
            for axis, ax in enumerate(fig.axes):
                np.testing.assert_array_equal(ax.get_xticks(), [3, 3.5, 4, 4.5, 5])
                assert not ax.collections  # No specification envelope or error bars.
                for window, line in zip((21, 35, 60, 75), ax.lines[:4]):
                    if name == 'fixed_calibration_performance':
                        g = normalized[normalized.window_days.eq(window)].sort_values('propagation_time_s')
                        expected = g.metered_execution_gas/1e6 if axis == 0 else g.state_utilization
                    else:
                        family = ('balanced', 'maximum')[axis]
                        g = gains[gains.window_days.eq(window) & gains.benchmark.eq(family)].sort_values('propagation_time_s')
                        expected = g.mean_execution_gain/1e6
                    np.testing.assert_allclose(line.get_ydata(), expected)
                    np.testing.assert_allclose(line.get_xdata(), [3, 3.5, 4, 4.5, 5])
                assert ax.lines[1].get_linewidth() > ax.lines[0].get_linewidth()
                if name == 'fixed_design_execution_gains' or axis == 1:
                    np.testing.assert_array_equal(ax.lines[-1].get_ydata(), [0, 0] if name.endswith('gains') else [1, 1])
            for extension in ('png', 'pdf'):
                assert 1000 < (ROOT/'plots'/f'{stem}.{extension}').stat().st_size < 1_000_000
        finally:
            plt.close(fig)


def test_diagnostic_paths_reproduce_cached_outcomes_without_new_workload():
    summary = pd.read_csv(DATA/'state_utilization_diagnostics.csv')
    paths = pd.read_csv(DATA/'state_utilization_diagnostic_paths.csv')
    cached = pd.read_csv(DATA/'normalized_outcomes.csv')
    keys = ['window_days', 'propagation_time_s']
    assert len(summary) == 4 and len(paths) == 128
    assert paths.groupby(keys).path.nunique().eq(32).all()
    assert set(map(tuple, summary[keys].to_numpy())) == {(60, 3.5), (60, 5), (75, 3.5), (75, 5)}
    expected = paths.drop(columns='path').groupby(keys).mean().sort_index()
    np.testing.assert_allclose(summary.set_index(keys).sort_index(), expected)
    joined = summary.merge(cached, on=keys, suffixes=('_diagnostic', '_cached'))
    for metric in ('state_utilization', 'state_binding_fraction'):
        np.testing.assert_allclose(joined[f'{metric}_diagnostic'], joined[f'{metric}_cached'], rtol=1e-12)
    np.testing.assert_allclose(paths.state_offered_utilization-paths.state_excluded_utilization, paths.state_utilization)
    np.testing.assert_allclose(paths.below_target_fraction*paths.zero_decrease_given_below_target,
                               paths.below_target_zero_decrease_fraction)
    manifest = json.loads((DATA/'state_utilization_diagnostic_manifest.json').read_text())
    original = json.loads((DATA/'manifest.json').read_text())
    assert manifest['workload_sha256'] == original['workload_sha256']
    assert manifest['source_sha256'] == hashlib.sha256((DATA/'normalized_outcomes.csv').read_bytes()).hexdigest()
    assert manifest['burn_in_blocks'] == 7200 and manifest['measured_blocks'] == 50400


def test_integer_downward_update_threshold_examples():
    from shared_fee.normalized_state import integer_fee_update
    np.testing.assert_array_equal(integer_fee_update([20, 20, 80, 80], [61, 60, 91, 90], [100]*4),
                                  [20, 19, 80, 79])


def test_report_keeps_primary_fixed_design_comparison_separate_from_reselection():
    report = (ROOT/'markdowns/eip8279_floor_calibration_report.md').read_text()
    main, appendix = report.split('## Appendix:', 1)
    sensitivity = main.split('## Sensitivity to demand assumptions')[1].split('## Limitations')[0]
    assert sensitivity.count('### ') == 3
    # Includes the three-second cap extension for the third benchmark.
    assert len(sensitivity.split()) < 1450
    assert main.index('### How a state disturbance reaches execution') < main.index('## Sensitivity')
    for stem in ('shared_fee_elasticity_performance', 'shared_fee_elasticity_state_growth',
                 'shared_fee_elasticity_equilibrium_fee', 'shared_fee_elasticity_execution_gains'):
        assert stem not in main and stem in appendix
    assert 'shared_fee_elasticity_execution_state.png' in sensitivity
    assert sensitivity.count('![') == 1
    assert '| Elasticity vector | Frozen historically anchored execution gain |' in sensitivity
    assert 'shared_fee_eip8372_fixed_design_execution_gains.png' not in sensitivity
    assert 'all 40 comparisons' in sensitivity
    assert 'causal contribution of rounding' in sensitivity


def test_three_mechanism_figure_uses_fixed_designs_and_physical_state_units(monkeypatch):
    module = runpy.run_path(str(ROOT/'scripts/shared_fee/make_eip8372_figures.py'))
    fixed = pd.read_csv(ROOT/'data/shared_fee/shared_fee_elasticity_fixed_central.csv')
    normalized = pd.read_csv(DATA/'normalized_outcomes.csv')
    render = module['three_mechanism_elasticity_figure']
    figures = []
    monkeypatch.setitem(render.__globals__, 'save', lambda fig, name: figures.append((fig, name)))
    render()
    fig, stem = figures[0]
    try:
        assert stem == 'shared_fee_elasticity_execution_state'
        assert len(fig.axes) == 6
        assert fig.get_figwidth() > fig.get_figheight()
        for col, family in enumerate(('proposal_faithful', 'fully_optimized', 'normalized_state')):
            data = normalized if col == 2 else fixed
            for row in range(2):
                ax = fig.axes[3*row+col]
                assert ax.get_subplotspec().get_gridspec().get_geometry() == (2, 3)
                np.testing.assert_array_equal(ax.get_xticks(), [3, 3.5, 4, 4.5, 5])
                for window, line in zip((21, 35, 60, 75), ax.lines[:4]):
                    group = data[data.benchmark.eq(family) & data.window_days.eq(window)].sort_values('propagation_time_s')
                    expected = group.metered_execution_gas/1e6 if row == 0 else group.annualized_state_growth_gib
                    np.testing.assert_allclose(line.get_ydata(), expected)
                    assert line.get_label() == f'{window}-day vector'
                assert ax.lines[1].get_linewidth() > ax.lines[0].get_linewidth()
                if row == 1:
                    assert 'GiB/year' in ax.get_ylabel()
                    np.testing.assert_array_equal(ax.lines[-1].get_ydata(), [120, 120])
                assert ax.get_ylim()[0] == 0
        assert len(fig.legends) == 1 and len(fig.legends[0].get_texts()) == 4
        for extension in ('png', 'pdf'):
            assert 1000 < (ROOT/'plots'/f'{stem}.{extension}').stat().st_size < 1_000_000
    finally:
        plt.close(fig)
