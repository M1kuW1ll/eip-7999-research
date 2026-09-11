"""Illustrative traces preserve canonical summaries and block/fee alignment."""
from pathlib import Path
import runpy

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def test_shared_trace_observes_existing_kernel_without_changing_outputs():
    module = runpy.run_path(str(ROOT / "scripts/shared_fee/make_example_paths.py"))
    replay = module["shared_replay"]
    original_summary = replay.OnlineSummary
    arr = lambda x: np.array([x], dtype=float)
    config = replay.SharedFeeConfig(arr(100), arr(200), arr(.12), arr(.23), arr(.335),
        1.45, 2.16, 5.65, 70., 20., 10., 1e-7)
    shocks = np.exp(np.random.default_rng(42).normal(0, .5, (1, 100, 4)))
    initial = arr(100.)
    expected = replay.run_shared_fee_batch(config, shocks, initial, burn_in=10)
    trace, result = module["shared_trace"](config, shocks, initial, 10)
    assert replay.OnlineSummary is original_summary
    for key in expected:
        np.testing.assert_array_equal(expected[key], result[key])
    assert len(trace["fee"]) == 90
    np.testing.assert_array_equal(trace["fee"][1:], trace["next_fee"][:-1])
    np.testing.assert_allclose(trace["next_fee"], replay.update_base_fee_1559(
        trace["fee"], trace["shared"], np.full(90, 100.)))
    np.testing.assert_allclose(trace["regular"], trace["execution"] + trace["data"])
    assert max(trace["regular"].max(), trace["state"].max()) <= 200. * (1 + 1e-12)


def test_saved_paths_have_requested_limits_and_pre_update_fee_alignment():
    data = np.load(ROOT / "data/shared_fee/example_paths/central_replication_00.npz")
    assert data["eip7999_included_gas"].shape == (50_400, 3)
    assert data["shocks"].shape == (50_400, 4)
    np.testing.assert_array_equal(data["measured_block"], np.arange(1, 50_401))
    np.testing.assert_array_equal(data["eip7999_base_fee_wei"][1:],
                                  data["eip7999_next_base_fee_wei"][:-1])
    np.testing.assert_array_equal(data["baseline_fee"][1:], data["baseline_next_fee"][:-1])
    assert data["eip7999_included_gas"][:, 0].max() <= 450e6 * (1 + 1e-12)
    assert data["eip7999_included_gas"][:, 1].max() <= 90e6 * (1 + 1e-12)
    for stem in ("dynamic_7999_E225_D60_example_path", "dynamic_baseline_3s_example_path"):
        for suffix in ("", "_full_week"):
            assert 1_000 < (ROOT / f"plots/{stem}{suffix}.png").stat().st_size < 1_000_000
            assert (ROOT / f"plots/{stem}{suffix}.pdf").stat().st_size > 1_000


def test_figures_show_full_path_with_requested_labels(monkeypatch):
    module = runpy.run_path(str(ROOT / "scripts/shared_fee/make_example_paths.py"))
    assert module['DISPLAY_BLOCKS'] == 50_400
    figures = []
    monkeypatch.setitem(module['eip_figure'].__globals__, 'save', lambda fig, name: figures.append(fig))
    data = np.load(ROOT / 'data/shared_fee/example_paths/central_replication_00.npz')
    module['eip_figure'](data['eip7999_included_gas'], data['eip7999_base_fee_wei'], 50_400)
    for ax in figures[0].axes[:3]:
        assert ax.get_ylabel() == 'gas usage (M)'
        assert len(ax.lines[0].get_xdata()) == 50_400
        assert 'included gas' not in [t.get_text() for t in ax.get_legend().get_texts()]
    for ax in figures[0].axes[3:]:
        assert ax.get_xlabel() == 'block number'
    _, config, _, _ = module['settings']()
    trace = {k.removeprefix('baseline_'):data[k] for k in data.files if k.startswith('baseline_')}
    module['shared_figure'](trace, config, 50_400)
    assert len(figures[1].axes) == 3
    assert [ax.get_title() for ax in figures[1].axes] == [
        'Metered regular gas', 'Metered state gas', 'Shared base fee']
    for ax in figures[1].axes[:2]:
        assert ax.get_ylabel() == 'gas usage (M)'
        assert len(ax.get_legend().get_texts()) == 2
    assert figures[1].axes[0].get_ylim() == figures[1].axes[1].get_ylim()
    for ax in figures[1].axes:
        assert ax.get_xlabel() == 'block number'
        assert len(ax.lines[0].get_xdata()) == 50_400
    for fig in figures:
        module['plt'].close(fig)
