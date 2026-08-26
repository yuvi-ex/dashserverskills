# Refusal: when not to build

## The rule

If a persona's subject is not in the data, **stop**. Do not build the nearest
available thing. State what is missing, name the role, and suggest a dataset or
a persona that would work.

A catalogue-driven tool with a `support.md` file will happily render five
plausible charts from a schema containing no support data. That output is worse
than nothing, because it looks like an answer.

## Two kinds

**Whole-persona refusal** — every decision fails the subject gate.
`derive_metrics.py` exits 3. Report it and stop. Real example: a Revenue
Operations Lead against a passenger manifest — no monetary role exists, so the
persona cannot be served, however many charts the data could technically draw.

**Partial refusal** — some decisions survive. Build those, and list the refused
ones *on the dashboard*, with the reason. Real example: a casualty investigator
against a passenger manifest can compare survival by class and by sex, but the
question "how did survival shift across the voyage timeline?" is refused,
because there is no temporal column.

## Wording

Say what is missing and why it matters. Never apologise, never hedge, never
imply the data is nearly good enough.

> Refused: no column carries a monetary amount, which every decision for this
> persona is about. This dataset describes passengers, not transactions. Point
> this persona at a dataset with revenue, or ask for a persona whose subject
> this data holds — a casualty investigator works well here.

## What is not a refusal

- A dataset with fewer capabilities is not a failure. Build the shapes it
  supports and list the rest under "what this dataset cannot do".
- A low-confidence classification is not a refusal. It is a check to resolve.
