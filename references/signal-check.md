# Stage 5: does the metric carry signal?

A metric can be correctly derived, legally aggregated, and still worthless —
because the column has no variation. Shipping it implies a signal that is not
there.

## The test

Group the metric by two or three dimensions and by time. If the spread across
every one is under about 5% of the mean, it carries no signal.

## What to do

Cut it, and **report the finding with its numbers**. The flatness is often more
useful than the chart would have been.

Real examples from TPC-H, all found this way:

- On-time delivery rate is 63.2% and stays within 63.0–63.6% across every ship
  mode, order priority, supplier nation and year. Commit, ship and receipt dates
  are independent random offsets, so an on-time trend is a flat line and a
  breakdown is five identical bars.
- Ship mode, shipping instruction, lines-per-order and day-of-week are all
  uniform. They are filters, not diagnoses.
- `O_ORDERSTATUS` is assigned against the generator's own fixed cutoff, not any
  reporting date. It reports 14,735 open orders where a date-based as-of test
  finds 1,208.

## Flat is sometimes the answer

Work-in-progress holding between 3,120 and 3,172 lines for 26 weeks is a
finding: the system is in steady state. Say so on the dashboard, so a reader
does not mistake a true flat line for a broken chart.
