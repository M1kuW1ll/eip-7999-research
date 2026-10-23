"""Figures for the isolated EIP-8372 target-ratio experiment."""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data/shared_fee/eip8372_target_ratio'
PLOTS = ROOT/'plots'
RATIOS = [.5, .6, 2/3, .75, .8]
LABELS = ['1/2', '3/5', '2/3', '3/4', '4/5']


def save(fig, name, *, dpi=150):
    fig.savefig(PLOTS/f'{name}.png', dpi=dpi, bbox_inches='tight',
                pil_kwargs={'optimize': True})
    with plt.rc_context({'pdf.fonttype': 42}):
        fig.savefig(PLOTS/f'{name}.pdf', bbox_inches='tight')
    plt.close(fig)


def target_ratio_figure(outcomes):
    """Mean-outcome summary; uncertainty stays in the paired-week tables.

    Preserve numerical ratio spacing. Color, marker, and dash pattern encode
    the same propagation allocation across all three panels. Darkened viridis
    gives each curve at least 3:1 contrast against the white background.
    """
    style = {'font.family': 'DejaVu Sans', 'font.size': 12,
             'axes.labelsize': 13, 'axes.titlesize': 14,
             'xtick.labelsize': 12, 'ytick.labelsize': 12,
             'legend.fontsize': 12, 'axes.spines.top': False,
             'axes.spines.right': False, 'axes.linewidth': .8,
             'pdf.fonttype': 42}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.0), sharex=True)
    metrics = [('metered_execution_gas', 1e-6, '(a) Execution throughput', 'Execution gas (M/block)'),
               ('annualized_state_growth_gib', 1, '(b) State growth', 'State growth (GiB/year)'),
               ('hard_limit_fraction', 1, '(c) Hard-limit frequency', 'Full block fraction (%)')]
    colors = plt.colormaps['viridis'](np.linspace(.08, .64, 5))[:, :3]*.9
    markers = ['o', 's', 'D', '^', 'v']
    dashes = ['-', (0, (5, 2)), (0, (1.5, 1.5)),
              (0, (5, 2, 1, 2)), (0, (6, 2, 1, 2, 1, 2))]
    groups = outcomes.groupby('propagation_time_s', sort=True)
    if len(groups) != 5:
        raise ValueError('Expected the five propagation allocations')
    for color, marker, dash, (propagation, group) in zip(colors, markers, dashes, groups):
        group = group.sort_values('target_ratio')
        np.testing.assert_allclose(group.target_ratio, RATIOS, rtol=1e-12)
        for ax, (metric, scale, title, ylabel) in zip(axes, metrics):
            ax.plot(group.target_ratio, group[metric]*scale, marker=marker, color=color,
                    ls=dash, lw=2, ms=5.5, markerfacecolor='white', markeredgewidth=1.3,
                    label=f'{propagation:.1f}s', zorder=3)
    for ax, (_, _, title, ylabel) in zip(axes, metrics):
        ax.set_title(title, loc='left', fontsize=14, pad=10)
        ax.set_ylabel(ylabel, fontsize=13, labelpad=7)
        ax.set_xticks(RATIOS, LABELS)
        ax.set_xlim(.49, .81)
        ax.grid(axis='y', color='.9', lw=.65, zorder=0)
        ax.tick_params(length=3.5, width=.8)
    axes[0].set_ylim(148, 220)
    axes[0].yaxis.set_major_locator(MultipleLocator(20))
    axes[1].axhline(120, color='.4', ls='--', lw=1.1, zorder=1)
    axes[1].text(.805, 122, 'State-growth target: 120 GiB/year',
                 ha='right', va='bottom', fontsize=10, color='.3')
    axes[1].set_ylim(48, 131)
    axes[1].yaxis.set_major_locator(MultipleLocator(20))
    axes[2].yaxis.set_major_formatter(PercentFormatter(1, decimals=0, symbol=''))
    axes[2].yaxis.set_major_locator(MultipleLocator(.05))
    axes[2].set_ylim(0, .22)
    handles, labels = axes[0].get_legend_handles_labels()
    prefix = Line2D([], [], color='none', linestyle='none')
    fig.legend([prefix]+handles, ['Propagation:']+labels, loc='upper center',
               ncol=6, frameon=False, fontsize=12, bbox_to_anchor=(.49, .985),
               handlelength=2.4, columnspacing=1.35, handletextpad=.55)
    fig.supxlabel('Target ratio', fontsize=14, y=.035)
    fig.subplots_adjust(left=.065, right=.99, bottom=.19, top=.77, wspace=.31)
    return fig


def target_ratio_tradeoff_figure(outcomes):
    """Plot realized trade-offs, not a fitted or Pareto-efficient frontier.

    Lines join the five tested target ratios in order, using only the integer
    controller. The separate unrounded diagnostic is not part of this figure.
    """
    style = {'font.family': 'DejaVu Sans', 'font.size': 12,
             'axes.labelsize': 13, 'axes.titlesize': 14,
             'xtick.labelsize': 12, 'ytick.labelsize': 12,
             'axes.spines.top': False, 'axes.spines.right': False,
             'axes.linewidth': .8}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.7), sharey=True)
    colors = plt.colormaps['viridis'](np.linspace(.08, .64, 5))[:, :3]*.9
    markers = ['o', 's', 'D', '^', 'v']
    dashes = ['-', (0, (5, 2)), (0, (1.5, 1.5)),
              (0, (5, 2, 1, 2)), (0, (6, 2, 1, 2, 1, 2))]
    metrics = ['hard_limit_fraction', 'annualized_state_growth_gib']
    groups = outcomes.groupby('propagation_time_s', sort=True)
    if len(groups) != 5:
        raise ValueError('Expected the five propagation allocations')
    for color, marker, dash, (propagation, group) in zip(colors, markers, dashes, groups):
        group = group.sort_values('target_ratio')
        np.testing.assert_allclose(group.target_ratio, RATIOS, rtol=1e-12)
        for ax, metric in zip(axes, metrics):
            ax.plot(group[metric], group.metered_execution_gas/1e6,
                    color=color, marker=marker, ls=dash, lw=2, ms=5.5,
                    markerfacecolor='white', markeredgewidth=1.3,
                    label=f'{propagation:.1f}s', zorder=3)

    # Labels refer to one identified line, with leaders to disambiguate nearby
    # 3/4 and 4/5 points. No coordinates or simulated quantities are jittered.
    reference = outcomes[outcomes.propagation_time_s.eq(3.5)].sort_values('target_ratio')
    offsets = [
        [(-13, 8), (-16, 9), (-24, 10), (-25, 11), (16, 6)],
        [(14, -3), (17, 5), (9, 11), (2, 13), (-9, 11)],
    ]
    for ax, metric, positions in zip(axes, metrics, offsets):
        for (_, row), offset in zip(reference.iterrows(), positions):
            ax.annotate(row.ratio_label,
                        xy=(row[metric], row.metered_execution_gas/1e6),
                        xytext=offset, textcoords='offset points',
                        ha='center', va='bottom', color=colors[1], fontsize=10.5,
                        bbox=dict(boxstyle='round,pad=.12', fc='white', ec='none', alpha=.95),
                        arrowprops=dict(arrowstyle='-', color=colors[1], lw=.7,
                                        shrinkA=2, shrinkB=5), zorder=6)

    axes[0].set_title('(a) Execution and congestion', loc='left', fontsize=14, pad=10)
    axes[1].set_title('(b) Execution and state growth', loc='left', fontsize=14, pad=10)
    axes[0].set_xlabel('Full block fraction (%)', fontsize=13, labelpad=8)
    axes[1].set_xlabel('State growth (GiB/year)', fontsize=13, labelpad=8)
    axes[0].set_ylabel('Mean execution gas (M/block)', fontsize=13, labelpad=8)
    axes[0].set_xlim(0, .21)
    axes[0].xaxis.set_major_locator(MultipleLocator(.05))
    axes[0].xaxis.set_major_formatter(PercentFormatter(1, decimals=0, symbol=''))
    axes[1].set_xlim(50, 125)
    axes[1].xaxis.set_major_locator(MultipleLocator(20))
    axes[1].axvline(120, color='.45', ls='--', lw=1.15, zorder=1)
    axes[1].text(118, 218, '120 GiB/year\ntarget',
                 ha='right', va='top', fontsize=10.5, color='.35')
    for ax in axes:
        ax.set_ylim(145, 228)
        ax.yaxis.set_major_locator(MultipleLocator(20))
        ax.grid(color='.91', lw=.6, zorder=0)
        ax.tick_params(length=3.5, width=.8)
    handles, labels = axes[0].get_legend_handles_labels()
    prefix = Line2D([], [], color='none', linestyle='none')
    fig.legend([prefix]+handles, ['Propagation:']+labels,
               loc='upper center', ncol=6, frameon=False, fontsize=12,
               bbox_to_anchor=(.49, .99), handlelength=2.4,
               columnspacing=1.35, handletextpad=.55)
    fig.text(.53, .015,
             'Means across 32 simulated weeks. Target ratios are labelled on the 3.5s curve.',
             ha='center', va='bottom', fontsize=10, color='.3')
    fig.subplots_adjust(left=.075, right=.985, bottom=.20, top=.80, wspace=.16)
    return fig


def target_ratio_dumbbell_figure(outcomes):
    """Show all target ratios on connected rows, with endpoint value labels."""
    propagation = np.sort(outcomes.propagation_time_s.unique())
    if len(propagation) != 5:
        raise ValueError('Expected the five propagation allocations')
    settings = {}
    for ratio in LABELS:
        selected = outcomes[outcomes.ratio_label.eq(ratio)]
        if len(selected) != 5 or selected.propagation_time_s.duplicated().any():
            raise ValueError(f'Expected one {ratio} setting per propagation allocation')
        settings[ratio] = selected.set_index('propagation_time_s').loc[propagation]

    style = {'font.family': 'DejaVu Sans', 'font.size': 22,
             'axes.labelsize': 24, 'axes.titlesize': 25,
             'xtick.labelsize': 22, 'ytick.labelsize': 22,
             'axes.spines.top': False, 'axes.spines.right': False,
             'axes.spines.left': False, 'axes.linewidth': .8}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.2), sharey=True)
    metrics = [
        ('metered_execution_gas', 1e-6, '(a) Execution gas usage', 'Execution gas (M/block)', (130, 235)),
        ('annualized_state_growth_gib', 1, '(b) State growth', 'State growth (GiB/year)', (44, 126)),
    ]
    colors = {'1/2': '#46327E', '3/5': '#365C8D', '2/3': '#277F8E',
              '3/4': '#249684', '4/5': '#16846E'}
    markers = {'1/2': 'o', '3/5': 's', '2/3': 'D', '3/4': '^', '4/5': 'o'}
    y = np.arange(len(propagation))
    for ax, (metric, scale, title, xlabel, limits) in zip(axes, metrics):
        values = {ratio: frame[metric].to_numpy()*scale for ratio, frame in settings.items()}
        ax.hlines(y, values['1/2'], values['4/5'], color='#ADB4BC', lw=2.4, zorder=2)
        for ratio in LABELS:
            ax.scatter(values[ratio], y, s=85 if ratio in ('1/2', '4/5') else 62,
                       marker=markers[ratio],
                       facecolors='white' if ratio == '1/2' else colors[ratio],
                       edgecolors=colors[ratio], linewidths=1.8 if ratio == '1/2' else .7,
                       zorder=3,
                       label=ratio, gid=f'target-ratio-{ratio}')
            if ratio not in ('1/2', '4/5'):
                continue
            other = values['4/5' if ratio == '1/2' else '1/2']
            for row, value, paired in zip(y, values[ratio], other):
                left = value < paired
                ax.annotate(f'{value:.1f}', (value, row),
                            xytext=(-10 if left else 10, 0), textcoords='offset points',
                            ha='right' if left else 'left', va='center',
                            fontsize=20, color=colors[ratio])
        ax.set_title(title, loc='left', fontsize=25, pad=14)
        ax.set_xlabel(xlabel, fontsize=24, labelpad=12)
        ax.set_xlim(*limits)
        ax.set_ylim(-.55, 4.65)
        ax.set_yticks(y, [f'{value:.1f}' for value in propagation])
        ax.tick_params(axis='y', length=0, pad=9)
        ax.tick_params(axis='x', length=3.5, width=.8)
        ax.grid(axis='x', color='.92', lw=.65, zorder=0)
        ax.set_axisbelow(True)
    axes[0].set_ylabel('Propagation time (s)', fontsize=24, labelpad=14)
    axes[0].xaxis.set_major_locator(MultipleLocator(20))
    axes[1].xaxis.set_major_locator(MultipleLocator(20))
    axes[1].axvline(120, color='.5', ls='--', lw=1.1, zorder=1)
    axes[1].text(118.5, 4.42, 'Target: 120', ha='right', va='bottom',
                 fontsize=20, color='.4')
    legend_handles = [Line2D([], [], color='none', linestyle='none')]
    for ratio in LABELS:
        legend_handles.append(Line2D([], [], marker=markers[ratio], ls='none', markersize=8,
                                     markerfacecolor='white' if ratio == '1/2' else colors[ratio],
                                     markeredgecolor=colors[ratio], markeredgewidth=1.8))
    fig.legend(legend_handles, ['Target ratio:']+LABELS, ncol=6,
               loc='upper center', bbox_to_anchor=(.5, .995), frameon=False,
               fontsize=22, handletextpad=.35, columnspacing=1.25)
    fig.subplots_adjust(left=.085, right=.985, bottom=.16, top=.78, wspace=.12)
    return fig


def main(which='all'):
    if which in ('all', 'dumbbell'):
        outcomes = pd.read_csv(DATA/'outcomes.csv')
        save(target_ratio_dumbbell_figure(outcomes),
             'shared_fee_eip8372_target_ratio_dumbbell', dpi=300)
    if which == 'dumbbell':
        return
    if which in ('all', 'tradeoffs'):
        outcomes = pd.read_csv(DATA/'outcomes.csv')
        save(target_ratio_tradeoff_figure(outcomes),
             'shared_fee_eip8372_target_ratio_tradeoffs', dpi=300)
    if which == 'tradeoffs':
        return
    if which in ('all', 'target-ratio'):
        outcomes = pd.read_csv(DATA/'outcomes.csv')
        save(target_ratio_figure(outcomes), 'shared_fee_eip8372_target_ratio', dpi=300)
    if which == 'target-ratio':
        return

    plt.rcParams.update({'font.size': 12, 'axes.labelsize': 13, 'axes.titlesize': 14,
                         'axes.spines.top': False, 'axes.spines.right': False})
    metrics = [('metered_execution_gas', 1e-6, 'Delivered execution', 'gas usage per block (M)'),
               ('annualized_state_growth_gib', 1, 'Physical state growth', 'annualized state growth (GiB/year)'),
               ('hard_limit_fraction', 1, 'Blocks at either hard limit', 'full block fraction')]
    diagnostics = pd.read_csv(DATA/'update_diagnostics.csv')
    diagnostics = diagnostics[diagnostics.initial_fee_convention.eq('inherited_half_target')]
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.7))
    for controller, label, color, marker in [
            ('integer', 'Integer EIP-1559', '#4c78a8', 'o'),
            ('continuous', 'Unrounded proportional diagnostic', '#e78b35', 's')]:
        group = diagnostics[diagnostics.controller.eq(controller)].sort_values('target_ratio')
        for ax, metric, scale in zip(axes,
                ['metered_execution_gas', 'annualized_state_growth_gib', 'hard_limit_fraction'], [1e-6, 1, 1]):
            ax.plot(group.target_ratio, group[metric]*scale, marker=marker, color=color,
                    lw=2, ms=6, label=label)
    for ax, (_, _, title, ylabel) in zip(axes, metrics):
        ax.set(title=title, xlabel='Target ratio', ylabel=ylabel)
        ax.set_xticks([.5, 2/3, .8], ['1/2', '2/3', '4/5'])
        ax.grid(alpha=.22)
    axes[2].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, frameon=False,
               bbox_to_anchor=(.5, 1.01), title='3.5-second propagation allocation')
    fig.tight_layout(rect=(0, 0, 1, .85), w_pad=2)
    save(fig, 'shared_fee_eip8372_target_ratio_update_diagnostic')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--figure', choices=['all', 'target-ratio', 'update-diagnostic', 'tradeoffs', 'dumbbell'], default='all')
    main(parser.parse_args().figure)
