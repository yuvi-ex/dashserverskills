---
name: persona-metrics
description: Derive the metrics a persona needs from whatever dataset is loaded, then build a dashboard from them. Works for any persona and any schema — nothing is looked up from a list. Use when a request names a role rather than naming metrics or SQL, such as "build a dashboard for the CFO", "what should ops see from this data", or "make a view for our warehouse shift leads".
---

# Persona-driven metric derivation

## What this is

A **procedure**, not a catalogue. There is no file of pre-written CFO metrics,
because a catalogue only answers for the personas someone remembered to write
down, on the schemas they had in mind. This derives the answer for an arbitrary
persona against an arbitrary dataset.

Read that as a constraint on you: never satisfy a persona request by recalling
metrics that "a CFO usually wants". Run the pipeline against the data in front
of you.

## The pipeline

Six stages. Stages 3 and 5 are code because they are where a plausible wrong
answer is easy to produce and hard to notice. Stages 1, 2 and 4 are judgement
and are yours.

### 1. Resolve the persona onto axes  → `references/persona-axes.md`
Personas are infinite; the axes that decide dashboard shape are five. Never
match a job title against a list.

### 2. Elicit decisions  → `references/persona-axes.md`
Write 2–5 decisions in the form
*"Given `<signal>`, I will `<action>` on `<object>` within `<horizon>`."*
If the sentence will not complete, it is not a decision and any metric
supporting it is decoration. Then declare, per decision, the **semantic roles
its subject requires** — a revenue decision requires a monetary role. This is
what stops a revenue persona being served survival flags.

### 3. Profile the dataset  → `assets/profile_schema.py`
```bash
python3 assets/profile_schema.py <SCHEMA> --json card.json
```
Produces a **schema card**: every column's semantic role, additivity class and
the evidence for both; each table's role and grain; an inferred and
data-verified join graph; capabilities and gaps. It re-types text columns from
their contents, because uploaded files routinely carry numbers and dates as
strings. Read `references/semantic-roles.md` to interpret it.

**The card is the only thing you may consult about a dataset.** Not table names,
not your memory of a similar schema.

### 4. Derive and check coverage  → `assets/derive_metrics.py`
```bash
python3 assets/derive_metrics.py --card card.json --persona persona.json
```
Composes candidate metrics from the grammar, refuses what the data cannot
support, and enforces the additivity legality matrix so an illegal aggregation
cannot be emitted. Exit code 3 means refused. Then apply
`references/coverage-checklist.md` yourself.

### 5. Validate signal  → `references/signal-check.md`
Run each surviving metric against the data. A metric that is flat across every
dimension and every period is noise. Cut it, and report the finding.

### 6. Build  → `assets/prelude.py`, and the `dash-server` skill
Scaffold with `app_create_exasol_dashboard` **before** writing the built
files: the builder does not emit `dash_server_exasol.py` and app creation
fails without it. Prerequisites and the full recipe → `DEPLOY.md`.
Shared design tokens and helpers so every dashboard reads as one system.

## Non-negotiables

- **Refuse rather than substitute.** If the persona's subject is not in the
  data, stop and say so. → `references/refusal.md`
- **Additivity decides aggregation.** Never sum a rate, a level across time, or
  an attribute across a join. The matrix in `derive_metrics.py` is the authority.
- **State the gaps.** A derivation that cannot list what the dataset cannot
  answer has not finished.
- **Anything guessed is labelled.** Low-confidence classifications carry the
  check a human needs to make. Never launder them into confident output.
- **Scale changes the query, never the metric.** → `references/scale-patterns.md`
