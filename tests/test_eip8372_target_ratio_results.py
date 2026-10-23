"""Result accounting, matched paths, and preservation for the ratio sweep."""
import pytest
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/shared_fee/eip8372_target_ratio'


def test_grid_path_counts_aggregation_and_calibration():
    rows = pd.read_csv(DATA/'outcomes.csv')
    paths = pd.read_csv(DATA/'paths.csv')
    assert len(rows) == 25 and len(paths) == 25*32
    keys = ['propagation_time_s', 'ratio_label']
    assert paths.groupby(keys).replication.nunique().eq(32).all()
    assert not paths.duplicated(keys+['replication']).any()
    for metric in ('metered_execution_gas', 'annualized_state_growth_gib',
                   'hard_limit_fraction', 'mean_fee_wei', 'execution_price_variation'):
        np.testing.assert_allclose(paths.groupby(keys)[metric].mean().sort_index(),
                                   rows.set_index(keys)[metric].sort_index(), rtol=1e-12)
    for _, group in rows.groupby('propagation_time_s'):
        for col in ('floor_rate', 'shared_limit', 'm_execution', 'm_data', 'initial_fee_wei'):
            assert group[col].nunique() == 1
    np.testing.assert_array_equal(rows.shared_target,
                                  rows.shared_limit*rows.ratio_numerator//rows.ratio_denominator)
    assert rows.target_state_growth_gib.between(119.95, 120.05).all()
    np.testing.assert_allclose(rows.equilibrium_regular_utilization, 1, atol=1e-5)
    np.testing.assert_allclose(rows.equilibrium_state_utilization, 1, atol=1e-5)
    np.testing.assert_allclose(rows.annualized_state_growth_gib,
                               rows.state_utilization*rows.target_state_growth_gib, rtol=1e-7)
    np.testing.assert_allclose(rows.regular_binding_fraction+rows.state_binding_fraction+rows.branch_tie_fraction, 1)
    assert (rows.hard_limit_fraction >= rows.regular_limit_fraction-1e-12).all()
    assert (rows.hard_limit_fraction >= rows.raw_state_limit_fraction-1e-12).all()
    assert (rows.hard_limit_fraction <= rows.regular_limit_fraction+rows.raw_state_limit_fraction+1e-12).all()
    assert (rows.below_target_zero_decrease_fraction <= rows.below_target_fraction).all()


def test_original_artifacts_unchanged_and_manifest_complete():
    manifest = json.loads((DATA/'manifest.json').read_text())
    assert manifest['workload_shape'] == [32, 57600, 4]
    assert manifest['burn_in'] == 7200 and manifest['measured_blocks'] == 50400
    assert len(manifest['half_target_reproduced_metrics']) == 24
    old = json.loads((ROOT/'data/shared_fee/eip8372/manifest.json').read_text())
    assert manifest['workload_sha256'] == old['workload_sha256']
    # The 25% rule changes comparison references, not target-ratio simulations.
    refreshed = manifest.get('selection_refresh', {}).get('source_hashes', {})
    for file, digest in {**manifest['source_hashes'], **refreshed, **manifest['implementation_hashes']}.items():
        # The runner checks the user-edited report is unchanged during this
        # experiment; later legitimate prose edits should not invalidate data.
        if file.endswith('.md'):
            continue
        assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest() == digest, file


def test_paired_changes_and_7999_comparison():
    paths = pd.read_csv(DATA/'paths.csv')
    changes = pd.read_csv(DATA/'paired_changes.csv')
    for _, row in changes.iterrows():
        p = paths[paths.propagation_time_s.eq(row.propagation_time_s)]
        base = p[p.ratio_label.eq('1/2')].set_index('replication').metered_execution_gas
        other = p[p.ratio_label.eq(row.ratio_label)].set_index('replication').metered_execution_gas
        delta = other-base
        np.testing.assert_allclose(
            [row.metered_execution_gas_change, row.metered_execution_gas_change_week_p05,
             row.metered_execution_gas_change_week_p95, row.metered_execution_gas_change_mcse],
            [delta.mean(), delta.quantile(.05), delta.quantile(.95), delta.std(ddof=1)/np.sqrt(32)], atol=1e-8)
    comparisons = pd.read_csv(DATA/'paired_7999_comparison.csv')
    assert len(comparisons) == 50
    np.testing.assert_allclose(comparisons.execution_gain_7999,
                               comparisons.execution_7999-comparisons.execution_8372, atol=1e-7)


def test_initialization_controls_and_fractional_diagnostic():
    controls = pd.read_csv(DATA/'unshocked_controls.csv')
    assert len(controls) == 12
    smooth = controls[controls.controller.eq('continuous')]
    np.testing.assert_allclose(smooth.regular_utilization, 1, atol=1e-5)
    np.testing.assert_allclose(smooth.state_utilization, 1, atol=1e-5)
    stochastic = pd.read_csv(DATA/'update_diagnostics.csv')
    assert len(stochastic) == 9
    # In this empirical replay (not as a general property), the different
    # integer initializations have coalesced by the measured period.
    integer = stochastic[stochastic.controller.eq('integer')]
    old = integer[integer.initial_fee_convention.eq('inherited_half_target')].set_index('ratio_label')
    own = integer[integer.initial_fee_convention.eq('own_root_ceiling')].set_index('ratio_label')
    for metric in ('metered_execution_gas', 'mean_fee_wei', 'annualized_state_growth_gib'):
        np.testing.assert_allclose(old[metric].sort_index(), own[metric].sort_index(), rtol=1e-12)


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / 'markdowns/eip8372_target_ratio_sensitivity.md').exists(), reason='Private report prose is excluded from the review artifact.')
def test_report_full_grid_matches_output():
    report = (ROOT/'markdowns/eip8372_target_ratio_sensitivity.md').read_text()
    for _, r in pd.read_csv(DATA/'outcomes.csv').iterrows():
        line = (f'| {r.propagation_time_s:.1f}s | {r.ratio_label} | '
                f'{r.equilibrium_fee_wei:.2f} | {r.metered_execution_gas/1e6:.1f}M | '
                f'{r.regular_utilization:.1%} | {r.state_utilization:.1%} | '
                f'{r.annualized_state_growth_gib:.1f} | {r.hard_limit_fraction:.2%} | '
                f'{r.execution_price_variation:.4f} |')
        assert line in report


def test_main_figure_preserves_every_value_and_accessible_styles():
    import runpy
    import matplotlib.pyplot as plt

    module = runpy.run_path(str(ROOT/'scripts/shared_fee/make_eip8372_target_ratio_figures.py'))
    rows = pd.read_csv(DATA/'outcomes.csv')
    figure = module['target_ratio_figure'](rows)
    try:
        metrics = [('metered_execution_gas', 1e-6),
                   ('annualized_state_growth_gib', 1), ('hard_limit_fraction', 1)]
        for ax, (metric, scale) in zip(figure.axes, metrics):
            for line, (propagation, group) in zip(ax.lines[:5], rows.groupby('propagation_time_s')):
                group = group.sort_values('target_ratio')
                np.testing.assert_array_equal(line.get_xdata(), group.target_ratio)
                np.testing.assert_array_equal(line.get_ydata(), group[metric]*scale)
                assert line.get_label() == f'{propagation:.1f}s'
        colors = np.array([line.get_color() for line in figure.axes[0].lines])
        linear = np.where(colors <= .04045, colors/12.92, ((colors+.055)/1.055)**2.4)
        contrast = 1.05/(linear@np.array([.2126, .7152, .0722])+.05)
        assert (contrast >= 3).all()
        assert len({line.get_marker() for line in figure.axes[0].lines}) == 5
        assert len({str(line._unscaled_dash_pattern) for line in figure.axes[0].lines}) == 5
        np.testing.assert_array_equal(figure.axes[1].lines[-1].get_ydata(), [120, 120])
        assert figure.axes[2].get_ylim()[0] == 0
        assert figure._supxlabel.get_text() == 'Target ratio'
    finally:
        plt.close(figure)


def test_tradeoff_figure_uses_matched_coordinates_without_unrounded_diagnostic():
    import runpy
    import matplotlib.pyplot as plt

    module = runpy.run_path(str(ROOT/'scripts/shared_fee/make_eip8372_target_ratio_figures.py'))
    rows = pd.read_csv(DATA/'outcomes.csv')
    figure = module['target_ratio_tradeoff_figure'](rows)
    try:
        assert len(figure.axes) == 2
        for ax, metric in zip(figure.axes, ['hard_limit_fraction', 'annualized_state_growth_gib']):
            for line, (propagation, group) in zip(ax.lines[:5], rows.groupby('propagation_time_s')):
                group = group.sort_values('target_ratio')
                np.testing.assert_array_equal(line.get_xdata(), group[metric])
                np.testing.assert_array_equal(line.get_ydata(), group.metered_execution_gas/1e6)
                assert line.get_label() == f'{propagation:.1f}s'
            labels = [text.get_text() for text in ax.texts]
            assert all(label in labels for label in ['1/2', '3/5', '2/3', '3/4', '4/5'])
            assert not any('unrounded' in label.lower() for label in labels)
            assert not any(line.get_marker() == '*' for line in ax.lines)
        assert len(figure.axes[0].lines) == 5
        assert len(figure.axes[1].lines) == 6  # Five curves and the target reference.
        np.testing.assert_array_equal(figure.axes[1].lines[-1].get_xdata(), [120, 120])
        assert figure.axes[0].get_ylim() == figure.axes[1].get_ylim()
        assert figure.axes[0].get_xlim()[0] == 0
        assert any('Target ratios' in text.get_text() for text in figure.texts)
    finally:
        plt.close(figure)


def test_dumbbell_figure_preserves_all_ratios_and_allocation_order():
    import runpy
    import matplotlib.pyplot as plt

    module = runpy.run_path(str(ROOT/'scripts/shared_fee/make_eip8372_target_ratio_figures.py'))
    rows = pd.read_csv(DATA/'outcomes.csv')
    figure = module['target_ratio_dumbbell_figure'](rows)
    try:
        assert len(figure.axes) == 2
        metrics = [('metered_execution_gas', 1e-6),
                   ('annualized_state_growth_gib', 1)]
        for ax, (metric, scale) in zip(figure.axes, metrics):
            for ratio in ('1/2', '3/5', '2/3', '3/4', '4/5'):
                group = rows[rows.ratio_label.eq(ratio)].sort_values('propagation_time_s')
                points = next(artist for artist in ax.collections
                              if artist.get_gid() == f'target-ratio-{ratio}')
                np.testing.assert_array_equal(points.get_offsets()[:, 0], group[metric]*scale)
                np.testing.assert_array_equal(points.get_offsets()[:, 1], np.arange(5))
            assert len(ax.collections) == 6  # Connector collection and all five target ratios.
            assert ax.get_ylim()[0] < ax.get_ylim()[1]  # Propagation increases upward.
            assert ax.xaxis.label.get_fontsize() >= 24
            assert all(text.get_fontsize() >= 20 for text in ax.texts)
            assert all(text.get_fontsize() >= 22 for text in ax.get_xticklabels())
        assert [text.get_text() for text in figure.axes[0].get_yticklabels()] == ['3.0', '3.5', '4.0', '4.5', '5.0']
        np.testing.assert_array_equal(figure.axes[1].lines[0].get_xdata(), [120, 120])
        assert [text.get_text() for text in figure.legends[0].get_texts()] == ['Target ratio:', '1/2', '3/5', '2/3', '3/4', '4/5']
        assert all(text.get_fontsize() >= 22 for text in figure.legends[0].get_texts())
        assert not figure.texts  # No bottom note.
    finally:
        plt.close(figure)
