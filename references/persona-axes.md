# Stage 1–2: resolving any persona, and eliciting decisions

## Why axes rather than a list

A list answers for the personas on it. These five axes are finite, and every
persona — "CFO", "warehouse shift lead", "clinical trial coordinator", "head of
trust and safety" — resolves onto them. Do this from what the person actually
does, not from their title.

| Axis | Values | Decides |
|---|---|---|
| **altitude** | `ic`, `manager`, `director`, `exec` | Counts vs ratios vs a single trend; how many headline metrics; whether individual rows belong on the page |
| **cadence** | `live`, `hourly`, `daily`, `weekly`, `monthly`, `ad_hoc` | The grain |
| **owned_object** | money, work items, customers, supply, systems, people, experiments, risk | Which part of the schema is relevant at all, and what the subject gate requires |
| **action** | allocate, intervene, escalate, investigate, report | Worklist vs anomaly flag vs trend |
| **horizon** | this shift → this year | Which comparison baselines mean anything |

Two worked resolutions:

- *Warehouse shift lead* → `ic` / `hourly` / work items / intervene / this shift.
  Raw counts, live grain, a worklist, and no year-on-year anywhere.
- *Chief risk officer* → `exec` / `monthly` / risk / escalate / this year.
  Three ratios against thresholds, an anomaly flag, and no rows at all.

Altitude is the one people get wrong most. A director who is shown 200 rows will
not read them; an IC who is shown a single ratio cannot act on it.

## Eliciting decisions

Force this sentence:

> **"Given `<signal>`, I will `<action>` on `<object>` within `<horizon>`."**

Rules:
- 2–5 decisions. More means the persona has not been thought through.
- If the sentence will not complete, drop it. "Wants visibility into sales" is
  not a decision.
- The signal must be something a number can move.

## Declaring what each decision requires

Every decision names the **semantic roles its subject needs**, using the role
vocabulary in `semantic-roles.md`. This is the subject gate, and it is the
difference between a refusal and a fabrication.

```json
{
  "id": "d1",
  "statement": "Given a fall in weekly revenue against last year, I will rebalance territory focus within the week.",
  "requires_roles": ["monetary_amount", "temporal_event"],
  "shapes": ["trend", "period_change"],
  "prefer_aggregation": "SUM"
}
```

Without `requires_roles`, a revenue persona pointed at passenger records will
chart a survival flag and label it revenue. The gate is not optional.

## The persona spec

```json
{
  "persona": "Revenue Operations Lead",
  "axes": {"altitude": "director", "cadence": "weekly",
           "owned_object": "money+customers", "action": "intervene",
           "horizon": "this_quarter"},
  "decisions": [ ... ]
}
```

Write it fresh each time. Do not keep a library of these — a stored spec is a
catalogue by another name, and it will be wrong for the next schema.
