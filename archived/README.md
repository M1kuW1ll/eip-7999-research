# Archived Research Material

This directory preserves superseded or exploratory work that is not part of the
active notebook and report sequence.

- `notebooks/` contains older experiments and superseded aggregate-demand
  models.
- `notebooks/2.0-full-7999-equilibrium-model.ipynb` preserves the earlier
  coupled three-fee equilibrium with a one-sided BAL demand specification.
- `notebooks/2.1-full-7999-driven-replay-scaffold.ipynb` preserves the earlier
  driven replay scaffold with one aggregate metered-data demand curve.
- `notebooks/2.2-full-7999-two-sided-bal-equilibrium.ipynb` preserves the
  two-sided BAL extension to the earlier equilibrium model. Notebooks 2.0--2.2
  are superseded by the supported bundle-pricing reference in notebook 2.4 and
  dynamic replay in notebook 2.5.
- `notebooks/2.3-joint-composite-cost-equilibrium.ipynb` preserves the
  transaction-class bundle-pricing extension. It is archived because its
  imposed class elasticities do not reproduce the historical aggregate
  elasticity; notebook 2.4 is the supported equilibrium specification.
- `markdowns/` contains earlier reports, working notes, and Maria's original
  modeling plan.
- `plots/` contains generated figures from archived notebook branches.
- `src/` and `tests/` contain retired Xatu BAL helpers and their test.

Archived notebooks may still write outputs to the repository's top-level
`data/` or `plots/` directories if rerun. They are kept for methodological
history, not as supported entry points for the current analysis.
