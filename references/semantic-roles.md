# Stage 3: reading a schema card

## Semantic roles

Roles describe what a column *means*, so the same reasoning works on an order
line, a meter reading and a passenger manifest.

| Role | What it is | Typical use |
|---|---|---|
| `temporal_event` | when something happened | the time axis |
| `temporal_scd` | a validity window (`valid_from`/`valid_to`) | as-of joins |
| `monetary_amount` | an extended money amount | totals |
| `monetary_unit_price` | a per-unit price or cost | multiply by a quantity |
| `monetary_rate` | a fraction or ratio | average, never total |
| `quantity` | a countable amount | totals |
| `level` | a stock or balance | never total across time |
| `measurement` | a physical reading or intensity | average |
| `binary_indicator` | a 0/1 flag | `SUM` = count, `AVG` = rate |
| `numeric_attribute` | a number describing a row | average; fans out across joins |
| `entity_key` | identifies or references a thing | count distinct, join |
| `entity_label` | names a row | display only |
| `categorical_dim` | groups rows | slices and filters |
| `state_flag` | lifecycle state | slices, funnels |
| `free_text` | prose | not a metric |
| `constant` | one value only | never a filter or a series |

## Additivity — the rule that keeps numbers right

The single most common way a dashboard lies is aggregating a measure in a way
its meaning does not permit.

| Class | May | Must never | Because |
|---|---|---|---|
| `additive` | SUM, AVG, MIN, MAX | — | totals across every dimension |
| `semi_additive` | SUM at a point in time, AVG, LAST | SUM across time | a stock of 100 held 30 days is 100, not 3,000 |
| `non_additive` | AVG, MIN, MAX, MEDIAN | SUM | adding rates yields a meaningless number; rebuild ratios from numerator and denominator |
| `attribute` | AVG, MIN, MAX | SUM across a join | it describes a row; joining repeats it per matched row |
| `binary_indicator` | SUM (count), AVG (rate) | unlabelled SUM | say which one is on screen |
| `count_only` | COUNT, COUNT DISTINCT | SUM | adding identifiers is arithmetic on labels |

`derive_metrics.py` enforces this. Do not work around it.

## Structural rules the profiler applies

These replace dataset-specific column names, which must never appear in the
rules:

- **A fact records events, and events happen in time.** A table with no temporal
  column is reference data however many keys it holds — so its numerics are
  attributes of a key, not quantities to sum. This is what makes a price list a
  price list.
- **One row per entity, no time column** → the numerics describe the entity.
  Whether one is extensive (a fare, which totals to revenue) or intensive (an
  age, which does not) is **not decidable from structure**. It defaults to
  "do not sum" and names the check. A missing total is recoverable; a wrong one
  is not.
- **Values beat names.** A non-integral numeric inside [0,1] with few distinct
  steps is a rate whatever it is called. Exactly two values, 0 and 1, is a flag.
- **Cardinality settles false friends.** "State" with 1,094 values is geography,
  not a lifecycle status.
- **Text is re-typed from its contents.** Uploads carry numbers and dates as
  strings; the card records the inferred type, the detected date format and a
  cast expression to use in generated SQL.

## Confidence

`<-- UNCONFIRMED` means the profiler guessed and the evidence string names the
check to make. Resolve it — by looking at the data, or by asking — before that
metric reaches a headline tile. Never silently promote a guess.
