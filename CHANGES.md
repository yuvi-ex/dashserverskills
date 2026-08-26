# persona-metrics — changes, 2026-08-26

Eleven fixes to the metric-derivation pipeline, found while building three
dashboards (Global Superstore sales, Global Superstore fulfilment, Titanic).
Every one is a defect in the generator, not in a single dashboard, so each
applies to whatever is built next.

## Correctness — wrong numbers reached the page

1. **`build_dashboard.py` — a derived rate was summed.**
   Persona-declared measures were pushed into `self.measures` regardless of
   additivity, so a `non_additive` measure emitted `SUM("Profit"/"Sales")` —
   the one aggregation the skill's own additivity matrix forbids. Non-additive
   derived measures now route to `self.rates` and are averaged.

2. **`build_dashboard.py` — the margin insight divided by a subset of revenue.**
   `revenue` was chosen by first name containing "sales", which matched
   `Loss-making sales` before `Sales`, reporting margin as 62.2% instead of
   11.7%. Selection now prefers an exact name, then the largest candidate.

3. **`build_dashboard.py` — every rate was formatted as a percentage.**
   Rate tiles were hardcoded to `:.1%`, so an average of 4.24 *days* displayed
   as "424.4%". Rates now format by their declared kind; the `monetary_rate`
   role maps to percent so discounts still read 14.3%, not 0.14.

## The chat panel produced broken or misleading SQL

4. **`build_dashboard.py` — derived measures were quoted as columns.**
   The fallback built `SUM("Slow shipments")`, but that measure is an
   expression, not a column: the database answered *object not found* and the
   panel showed nothing. It now aggregates the measure's real SQL via a new
   `MEASURE_SQL` map.

5. **`profile_schema.py` + `build_dashboard.py` — questions naming a value were
   answered as if they had not.** "what is apac region sales" matched the
   measure and the dimension and silently discarded "apac", answering a
   different question under a caption claiming otherwise. The profiler now
   records each listable dimension's actual values (`index_dimension_values`,
   ≤200 distinct, high-cardinality columns skipped) and the fallback turns a
   named value into a `WHERE` clause.

6. **`build_dashboard.py` — unused words are now reported.** When the template
   cannot account for part of a question, an amber note names the dropped words
   and says to check the SQL. Silently narrowing the question was the real
   defect; matching more of it is only half the fix.

7. **`build_dashboard.py` — substring collisions.** `Category` is a substring of
   `Sub-Category`, so first-match order answered sub-category questions with
   categories. Measure and dimension matching now take the longest name.

8. **`build_dashboard.py` — the chat could name a column it could not query.**
   The fallback emits a single-table query, but `DIMS` may include columns from
   joined tables. A new `CHAT_DIMS` restricts the fallback's vocabulary to the
   fact table so it can never generate an unresolvable reference.

9. **`build_dashboard.py` — an empty result rendered as silence.** Zero rows
   drew nothing, indistinguishable from a hang. It now says so.

## Persona intent was being dropped between stages

10. **`derive_metrics.py` — builder hints never crossed the stage boundary.**
    `derive()` assembles its output from an explicit key list, so
    `prefer_entities`, `prefer_time` and `show_measures` were silently absent
    and the builder read them as unset. Consequences seen in practice: the
    concentration entity was Postal Code instead of Customer ID, and a
    fulfilment dashboard carried Profit and Shipping Cost, which that persona
    has no lever over. All three now pass through. (`prefer_entities` is also
    new — see 11.)

11. **`build_dashboard.py` — `prefer_slices` was applied after truncation.**
    Dimensions were cut to six in column order *before* preference was read, so
    `Category` and `Sub-Category` — named third and fourth by the persona — were
    dropped from a sales dashboard entirely. Truncation now happens after
    ranking. A matching `prefer_entities` knob was added, because cardinality
    alone picks the wrong entity often enough to need overriding.

## Shareable HTML

12. **`build_dashboard.py` — Download PDF in the shared snapshot.**
    The Share page gained a Download button calling `window.print()`, plus the
    print stylesheet that makes the output usable: `@page` A4 landscape,
    `print-color-adjust: exact` (browsers strip backgrounds by default),
    `break-inside: avoid` on cards, tiles, insight blocks and table rows,
    repeating table headers, `overflow: visible` so wide tables are not clipped,
    the button hidden in print, and a `beforeprint` hook that re-runs
    `Plotly.Plots.resize()` so charts do not keep their screen width.
    Output is vector with selectable text; it is not a silent download — the
    browser's print dialog appears and "Save as PDF" is the destination.

## What was verified

Against the live database, not by inspection:

- Global Superstore, 51,291 rows, single table with time and money.
  Trailing 12 months: Sales $4.30M, Profit $504K (11.7% margin), loss-making
  sales $811K, 1,590 customers, 25,035 orders.
- Titanic, 891 rows, single table with **no temporal column and no additive
  measure**. The pipeline degrades rather than failing: `HAS_TIME=False`, trend
  and period_change are refused with reasons, six queries instead of seven.
  Chat returns female survival 74.2% and by class 63%/47%/24%.
- Generated chat SQL was executed for both, and the fulfilment cycle by ship
  mode (Standard 5.00 days, Second 3.23, First 2.18, Same Day 0.04) matches the
  190% spread the signal check independently reported.

## Known limits — read before assuming dataset independence

- **The chat fallback is English keyword matching**, not language understanding.
  `QUESTION_NOISE`, measure/dimension name matching and value matching all
  assume English word order and Latin word boundaries. Real natural language
  requires `ANTHROPIC_API_KEY` in the dash-server process environment, which
  switches on the model path in `llm_sql.py`; the guard there already restricts
  whatever the model writes to one bounded, schema-qualified, read-only SELECT.
- **The value index covers dimensions with ≤200 distinct values** and skips
  high-cardinality ones. A question naming a City, State or Ticket value will
  not filter on it.
- **A derived rate should declare `kind` explicitly.** Without it, formatting
  falls back to a name heuristic over English money words.
- **The margin insight keys off English commercial naming** ("profit",
  "revenue", "sales"). On a dataset without them it does not fire at all, which
  is the intended degradation, not an error.
- **The chat fallback queries the fact table only** (see 8). Dimensions on
  joined tables are available to the charts and to the model path, not to the
  template fallback.
- **SQL is Exasol dialect** (`TO_DATE`, `ADD_MONTHS`, `DAYS_BETWEEN`). Portable
  across datasets, not across databases.
- **Multi-table joins were not re-tested** after these changes. Both datasets
  used for verification are single flat tables; the TPC-H dashboards built
  before these fixes have not been rebuilt.

## Semantic chat (added after the first packaging)

13. **`build_dashboard.py` — the fallback no longer guesses a measure.**
    With no measure named, it defaulted to `MEASURES[0]`, so "revenue by market"
    reported *loss-making sales* — a confident number against the wrong measure.
    It now refuses, names the measures it does have, and lists the words it
    could not match. Guessing was worse than answering nothing.

14. **`llm_sql.py` — rewritten onto the official Anthropic SDK, and reachable.**
    - Uses `anthropic.Anthropic` rather than hand-rolled `urllib`, with
      `anthropic>=1.0` added to each app's `requirements.txt` (dash-server
      installs per-app requirements; the shared venv now carries 1.0.0).
    - Model moved from `claude-sonnet-4-5` to **`claude-opus-5`**, with
      server-side refusal fallbacks (`server-side-fallback-2026-07-01`,
      `fallbacks: "default"`) and an explicit `stop_reason == "refusal"` check
      before the response content is read.
    - Typed error handling (rate limit / auth / status / connection) instead of
      one broad catch, each mapped to a message a dashboard reader can act on.
    - **Key resolution now has two steps**: `ANTHROPIC_API_KEY`, then
      `~/.exasol-starter-kit/credentials/anthropic_api_key`. The second exists
      because dash-server is started by a launchd boot entry carrying no
      `EnvironmentVariables` — a key exported in a login shell never reaches it.
      This mirrors how the kit already resolves the database password. The file
      is refused if it is group- or world-readable, and the key is never logged,
      echoed, or written into app source. `read_key()` runs per question, so a
      key added later takes effect without restarting dash-server.
    - **A model failure is no longer silent.** `propose_sql`'s error was
      discarded, so a misconfigured key looked identical to no key at all. The
      panel now says the model path was configured but did not answer, and why,
      above the template result.

    Neither the launcher (`~/.local/bin/dash-server`) nor the LaunchAgent plist
    was edited: `exakit update dash-server` regenerates both, so a change there
    would be silently reverted on the next kit update.

## Second sweep — found while demo-testing on Walmart weekly sales

15. **`build_dashboard.py` — names were matched raw but displayed prettified.**
    The column is `Weekly_Sales`; the panel prints "Weekly Sales". Matching
    compared the question against the raw name, so "what is the overall weekly
    sales" could never match — and the refusal then listed the prettified names,
    asking the reader to type the words they had just typed. Names are now
    compared on their words, padded so `Sales` cannot match inside `wholesales`.

16. **`build_dashboard.py` — "top 5" was read as a dimension value.**
    `Store` runs 1-45 and `Pclass` 1-3, so "top 5 store by weekly sales"
    filtered to store 5 ($45M) instead of ranking (store 20, $301M); "top 3
    survived by pclass" returned Pclass 3. Four of six dashboards. A row limit
    is now stripped before value matching, and a bare number counts as a value
    only when the question also names its column ("store 5" yes, "top 5" no).

17. **`build_dashboard.py` — the cards and the chat used different windows.**
    KPI cards report a trailing twelve months; the chat panel answered over all
    history. On the Walmart set that put **$2.5B** on a card and **$6.7B** in the
    panel under the same label, with nothing on screen to explain the gap. Both
    numbers were correct and the page was incoherent. The chat now applies the
    same window, says so, and the reconciled figure is $2,544,229,137.75.

18. **`build_dashboard.py` — the period now travels with the number.**
    Each KPI card carries its own window ("Nov 2011 - Oct 2012") under the
    label, rather than the page header alone carrying it. Year rollover
    verified; a dataset with no temporal column shows no period rather than an
    invented one.

19. **`build_dashboard.py` — the concentration insight called everything
    "accounts".** A Walmart dashboard read "the ten largest of 45 accounts".
    The noun is now derived from the entity in play — stores, customers,
    orders, cabins — preferring a dimension with enough members for a ranking
    to mean anything.
