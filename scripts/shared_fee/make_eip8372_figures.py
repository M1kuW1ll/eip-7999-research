"""Figures for the frozen demand-calibrated, normalized-state benchmark."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'data/shared_fee/eip8372'
plt.rcParams.update({'font.size':14, 'axes.spines.top':False, 'axes.spines.right':False})
FAMILY = {
    'proposal_faithful':('Baseline one-dimensional','#737373','^','--'),
    'fully_optimized':('Floor-adjusted + EIP-8368','#54a24b','D','-'),
    'normalized_state':('Floor-adjusted + EIP-8372','#148878','P','-'),
    'balanced':('EIP-7999 multi-dimensional: historically anchored','#ed8618','s','-'),
    'maximum':('EIP-7999 multi-dimensional: maximum throughput','#477eaf','o','-'),
}
VECTORS = [(21,'#2171b5','-','o'),(35,'#e17c05','--','s'),
           (60,'#389957','-.','^'),(75,'#777777',':','D')]


def save(fig, name):
    fig.savefig(ROOT/'plots'/f'{name}.png', dpi=145, bbox_inches='tight', pil_kwargs={'optimize':True})
    fig.savefig(ROOT/'plots'/f'{name}.pdf', bbox_inches='tight')
    plt.close(fig)


def central_figure():
    normalized = pd.read_csv(DATA/'normalized_outcomes.csv')
    eip = pd.read_csv(DATA/'fixed_7999_outcomes.csv')
    old = pd.read_csv(ROOT/'data/shared_fee/shared_fee_elasticity_reselected.csv')
    old = old[old.benchmark.isin(['proposal_faithful','fully_optimized'])]
    full = pd.concat([normalized,eip,old], ignore_index=True)
    full = full[full.window_days.eq(35)]
    fig, axes = plt.subplots(1,2,figsize=(14,4.8))
    for family,(label,color,marker,style) in FAMILY.items():
        group = full[full.benchmark.eq(family)].sort_values('propagation_time_s')
        assert len(group) == 5
        axes[0].plot(group.propagation_time_s,group.metered_execution_gas/1e6,label=label,
            color=color,marker=marker,ls=style,lw=2)
        axes[1].plot(group.propagation_time_s,group.annualized_state_growth_gib,
            color=color,marker=marker,ls=style,lw=2)
    axes[0].set(title='Included execution',ylabel='mean execution gas per block (M)')
    axes[1].set(title='Physical state creation',ylabel='annualized state growth (GiB/year)')
    axes[1].axhline(120,color='black',lw=1,ls=':',zorder=0)
    for ax in axes:
        ax.set_xticks([3,3.5,4,4.5,5]);ax.set_xlabel('propagation time (s)');ax.grid(alpha=.25)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,-.28),ncol=2,frameon=False,fontsize=12)
    fig.subplots_adjust(wspace=.28)
    save(fig,'shared_fee_eip8372_central')


def elasticity_figure():
    normalized=pd.read_csv(DATA/'normalized_outcomes.csv')
    gains=pd.read_csv(DATA/'paired_gains.csv')
    fig,axes=plt.subplots(1,3,figsize=(18,4.6))
    for w,color,style,marker in VECTORS:
        a=normalized[normalized.window_days.eq(w)].sort_values('propagation_time_s')
        axes[0].plot(a.propagation_time_s,a.metered_execution_gas/1e6,label=f'{w}-day vector',
            color=color,ls=style,marker=marker,lw=2)
        for ax,family in zip(axes[1:],('balanced','maximum')):
            b=gains[gains.window_days.eq(w)&gains.benchmark.eq(family)].sort_values('propagation_time_s')
            ax.plot(b.propagation_time_s,b.mean_execution_gain/1e6,color=color,ls=style,marker=marker,lw=2)
    axes[0].set(title='Floor-adjusted + EIP-8372',ylabel='mean execution gas per block (M)')
    axes[1].set(title='Frozen historically anchored EIP-7999',ylabel='execution gain over EIP-8372 benchmark (M)')
    axes[2].set(title='Frozen maximum-throughput EIP-7999',ylabel='execution gain over EIP-8372 benchmark (M)')
    for ax in axes[1:]:ax.axhline(0,color='black',lw=1.5)
    for ax in axes:
        ax.set_xticks([3,3.5,4,4.5,5]);ax.set_xlabel('propagation time (s)');ax.grid(alpha=.25)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,-.12),ncol=4,frameon=False)
    fig.subplots_adjust(wspace=.38)
    save(fig,'shared_fee_eip8372_frozen_elasticities')


def stress_figure():
    frame=pd.read_csv(DATA/'stress_response_curve.csv')
    fig,axes=plt.subplots(1,3,figsize=(16,4.5))
    for ax,resource,title in zip(axes,('execution','static_data','state'),
                                ('Execution-demand pulse','Static-data-demand pulse','State-demand pulse')):
        for family in ('normalized_state','balanced','maximum'):
            label,color,marker,style=FAMILY[family]
            g=frame[frame.resource.eq(resource)&frame.benchmark.eq(family)]
            ax.plot(g.blocks_after_onset,g.execution_fraction,label=label,color=color,ls=style,lw=2)
        ax.axhline(0,color='black',lw=1)
        ax.set(title=title,xlabel='blocks after pulse onset');ax.grid(alpha=.25)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
    axes[0].set_ylabel('execution change\nversus no-pulse path')
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,-.14),ncol=3,frameon=False,fontsize=11)
    save(fig,'shared_fee_eip8372_resource_pulses')


def fixed_calibration_performance_figure():
    """Fixed central physical/state-price constants; complete alternative vectors."""
    frame = pd.read_csv(DATA/'normalized_outcomes.csv')
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for window, color, style, marker in VECTORS:
        group = frame[frame.window_days.eq(window)].sort_values('propagation_time_s')
        assert group.propagation_time_s.tolist() == [3, 3.5, 4, 4.5, 5]
        kwargs = dict(color=color, ls=style, marker=marker,
                      lw=2.8 if window == 35 else 1.8, ms=6)
        axes[0].plot(group.propagation_time_s, group.metered_execution_gas/1e6,
                     label=f'{window}-day vector', **kwargs)
        axes[1].plot(group.propagation_time_s, group.state_utilization, **kwargs)
    axes[0].set(title='Delivered execution', ylabel='mean execution gas per block (M)',
                ylim=(90, 190))
    axes[1].set(title='Normalized state-target utilization',
                ylabel='mean state-target utilization', ylim=(.65, 1.03))
    axes[1].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    axes[1].axhline(1, color='#444444', ls='--', lw=1.3)
    axes[1].text(4.98, 1.005, 'state target', ha='right', va='bottom', fontsize=11)
    for ax in axes:
        ax.set_xticks([3, 3.5, 4, 4.5, 5])
        ax.set_xlabel('propagation time (s)')
        ax.grid(alpha=.22)
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center',
               bbox_to_anchor=(.5, -.12), ncol=4, frameon=False)
    fig.subplots_adjust(wspace=.30)
    save(fig, 'shared_fee_eip8372_fixed_calibration_performance')


def fixed_design_execution_gain_figure():
    """Paired mean gains, without reselection or specification envelopes."""
    frame = pd.read_csv(DATA/'paired_gains.csv')
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    for ax, family, title in zip(axes, ('balanced', 'maximum'),
            ('Frozen historically anchored EIP-7999', 'Frozen maximum-throughput EIP-7999')):
        for window, color, style, marker in VECTORS:
            group = frame[frame.window_days.eq(window) & frame.benchmark.eq(family)].sort_values('propagation_time_s')
            assert group.propagation_time_s.tolist() == [3, 3.5, 4, 4.5, 5]
            ax.plot(group.propagation_time_s, group.mean_execution_gain/1e6,
                    label=f'{window}-day vector', color=color, ls=style, marker=marker,
                    lw=2.8 if window == 35 else 1.8, ms=6)
        ax.axhline(0, color='#333333', lw=1.5)
        ax.set(title=title, xlabel='propagation time (s)', ylim=(-5, 135))
        ax.set_xticks([3, 3.5, 4, 4.5, 5])
        ax.grid(alpha=.22)
    axes[0].set_ylabel('additional execution gas per block (M)')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center',
               bbox_to_anchor=(.5, -.12), ncol=4, frameon=False)
    fig.subplots_adjust(wspace=.17)
    save(fig, 'shared_fee_eip8372_fixed_design_execution_gains')


def three_mechanism_elasticity_figure():
    """Metered execution and physical state growth with central designs frozen."""
    fixed = pd.read_csv(ROOT/'data/shared_fee/shared_fee_elasticity_fixed_central.csv')
    normalized = pd.read_csv(DATA/'normalized_outcomes.csv')
    frame = pd.concat([
        fixed[fixed.benchmark.isin(['proposal_faithful', 'fully_optimized'])],
        normalized,
    ], ignore_index=True)
    panels = [('proposal_faithful', 'Baseline'),
              ('fully_optimized', 'Floor-adjusted + EIP-8368'),
              ('normalized_state', 'Floor-adjusted + EIP-8372')]
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 8.4))
    for col, (family, title) in enumerate(panels):
        subset = frame[frame.benchmark.eq(family)]
        for _, group in subset.groupby('propagation_time_s'):
            assert set(group.window_days) == {21, 35, 60, 75}
            for column in ('shared_limit', 'shared_target', 'floor_rate', 'cpsb', 'm_data'):
                assert group[column].nunique() == 1, (family, column)
        for window, color, style, marker in VECTORS:
            group = subset[subset.window_days.eq(window)].sort_values('propagation_time_s')
            assert group.propagation_time_s.tolist() == [3, 3.5, 4, 4.5, 5]
            kwargs = dict(label=f'{window}-day vector', color=color, ls=style, marker=marker,
                          lw=2.8 if window == 35 else 1.8, ms=6,
                          zorder=4 if window == 35 else 3)
            axes[0, col].plot(group.propagation_time_s, group.metered_execution_gas/1e6, **kwargs)
            axes[1, col].plot(group.propagation_time_s, group.annualized_state_growth_gib, **kwargs)
        axes[0, col].set(title=title,
                         ylabel='mean execution gas per block (M)', ylim=(0, 200))
        axes[1, col].set(
                         ylabel='annualized state growth (GiB/year)',
                         ylim=(0, 450) if col == 0 else (0, 135))
        axes[1, col].axhline(120, color='#444444', ls='--', lw=1.1, zorder=1)
        axes[1, col].text(4.98, 124 if col == 0 else 124.5,
                          '120 GiB/year', ha='right', va='bottom', fontsize=10)
        for ax in axes[:, col]:
            ax.set_xticks([3, 3.5, 4, 4.5, 5])
            ax.set_xlabel('propagation time (s)')
            ax.grid(alpha=.22)
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc='lower center',
               bbox_to_anchor=(.5, .005), ncol=4, frameon=False)
    fig.subplots_adjust(left=.075, right=.98, top=.93, bottom=.14,
                        hspace=.40, wspace=.35)
    save(fig, 'shared_fee_elasticity_execution_state')


if __name__=='__main__':
    central_figure()
    elasticity_figure()
    stress_figure()
    fixed_calibration_performance_figure()
    fixed_design_execution_gain_figure()
    three_mechanism_elasticity_figure()
