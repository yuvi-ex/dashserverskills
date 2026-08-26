# Query discipline by size

Scale changes the query, never the metric. Read the row-count class from the
schema card and pick accordingly.

| Rows | Approach |
|---|---|
| < 1M | Straightforward queries. Exact `COUNT(DISTINCT)`. |
| 1M–100M | Push the date predicate down before any join. Aggregate before joining. Approximate distinct counts. |
| > 100M | Pre-aggregate to the persona's grain. Never scan the fact for a dashboard tile. Bound every worklist. |

Always, at any size:

- Filter on the time column first — it is the cheapest reduction available.
- Aggregate before joining, never after.
- No cross join against a full fact table.
- Every row-level output carries a `LIMIT`.
- Profile from the catalogue first; sample only when statistics are insufficient.

`profile_schema.py` already follows this: it reads `EXA_ALL_*` before touching
data, profiles a bounded subquery above `--sample-rows`, and switches to
approximate distinct counts on large tables. The card records `sampled: true`
whenever it did.
