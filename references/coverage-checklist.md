# Stage 4: proving coverage

Completeness cannot come from having thought of everything. It comes from
enumerating the composition space and pruning it with three checks.

## The metric grammar

Every metric is a composition, which is why the space can be enumerated rather
than recalled:

```
<aggregation> of <measure> [per <entity>] [over <grain>]
              [by <dimension>] [against <baseline>]

aggregation   constrained by the measure's additivity class — see semantic-roles.md
grain         from the persona's cadence, not the data's native grain
baseline      prior period | plan | threshold | peer | distribution
```

Shapes, and what each needs present in the data:

| Shape | Needs | Answers |
|---|---|---|
| `level` | — | where are we now |
| `distribution` | — | what is the spread |
| `outlier` | — | what is extreme |
| `trend` | temporal | which way is it going |
| `period_change` | temporal | versus when |
| `composition` | categorical | what is it made of |
| `mix_shift` | temporal + categorical | what changed the total |
| `per_entity` | entity | who or which |
| `concentration` | entity | how exposed |
| `worklist` | entity | what to act on |
| `cohort` | temporal + entity | do groups behave differently |
| `drill_path` | hierarchy | where inside it |

## The three checks

**1. Decision coverage.** Every decision has at least one metric where a change
in the number changes the action. `derive_metrics.py` reports uncovered
decisions; an uncovered decision is a gap to fix or a decision to drop.

**2. Shape coverage.** For the owned object, is each of level / rate / trend /
distribution / composition / outlier present where meaningful? This catches
"we have totals but no trend" and "a trend but no distribution".
`shapes_available_unused` lists what the data supports that nothing exploits —
check each one is a deliberate omission rather than an oversight.

**3. Negative coverage.** What the dataset cannot answer is written down and put
on the dashboard. A derivation that cannot state its gaps has not finished.

## Altitude budget

`ic` 6 headline metrics · `manager` 5 · `director` 5 · `exec` 3. Rows are
allowed for ic, manager and director; never for exec. Exceeding the budget is
how a dashboard becomes a column dump.
