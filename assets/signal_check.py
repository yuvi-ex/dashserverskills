#!/usr/bin/env python3
"""Stage 5: does each derived metric actually carry signal?

    python3 signal_check.py --card card.json --plan plan.json

A metric can be correctly derived, legally aggregated and still worthless
because the column does not vary. Shipping it implies a signal that is not
there. This groups each metric by the dimensions available and across time, and
reports the spread. Anything flat is cut, with its numbers, so the flatness can
be reported as a finding rather than hidden.
"""
from __future__ import annotations
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  -- batching executor, see assets/db.py

FLAT_THRESHOLD = 0.05  # spread below 5% of the mean carries nothing


class _Batch:
    """Run the whole check twice: once to collect SQL, once to read answers.

    Every probe here is one process otherwise, and on a wide plan that is most
    of the runtime. The two-pass trick avoids restructuring the loops: which
    queries get issued depends only on the card and the plan, never on what a
    previous query returned, so walking the same code twice asks for exactly the
    same SQL both times. The first walk records it and returns nothing; one
    batch runs it all; the second walk gets the real rows.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cache: dict[str, db.Result] = {}
        self.pending: list[str] = []
        self.mode = "replay"
        self.live_fetches = 0

    def sql(self, statement: str) -> list[dict]:
        if self.mode == "collect" and statement not in self.cache:
            if statement not in self.pending:
                self.pending.append(statement)
            return []
        result = self.cache.get(statement)
        if result is None:
            # Safety net: the replay walk asked for something the collect walk
            # never reached. Fetch it rather than silently reporting "no rows",
            # which would read as a flat metric and cut it for the wrong reason.
            self.live_fetches += 1
            result = db.run_many([statement])[0]
            self.cache[statement] = result
        if not result.ok:
            # Callers already treat a failed probe as "this dimension is not
            # comparable" and carry on; keep that contract exactly.
            raise RuntimeError(result.error)
        return result.rows

    def flush(self) -> None:
        if not self.pending:
            return
        for statement, result in zip(self.pending, db.run_many(self.pending)):
            self.cache[statement] = result
        self.pending = []


_BATCH = _Batch()


def run_sql(sql: str) -> list[dict]:
    return _BATCH.sql(sql)


def q(*parts: str) -> str:
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts)


def column_expr(card: dict, table: str, column: str) -> str:
    for t in card["tables"]:
        if t["name"] != table:
            continue
        for c in t["columns"]:
            if c["name"] == column:
                return c.get("cast_expression") or q(column)
    return q(column)


def spread_of(values: list[float]) -> tuple[float, float]:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return 0.0, 0.0
    mean = sum(clean) / len(clean)
    if mean == 0:
        return 0.0, 0.0
    return (max(clean) - min(clean)) / abs(mean), mean


def check_derived(card: dict, plan: dict, dim_refs: list) -> list:
    """Test the persona's own composite measures, not just the card's columns.

    A derived measure is what the dashboard actually plots. Checking only the raw
    columns lets a flat composite -- a late-delivery rate that is identical in
    every group -- reach the page unexamined.
    """
    schema = card["schema"]
    facts = [t for t in card["tables"] if t["role"] in ("fact_like", "flat")]
    fact = max(facts or card["tables"], key=lambda t: t["row_count"])
    source = f'{q(schema, fact["name"])} {q(fact["name"])}'
    verdicts = []
    for measure in plan.get("derived_measures", []):
        if measure.get("requires_tables") or measure.get("kpi_only"):
            continue  # needs a join or an as-of bound; not comparable this way
        if measure["expr"].strip().isdigit():
            continue  # a plain count: its spread is group size, tested elsewhere
        worst, worst_dim, samples = None, None, []
        for dim_table, dim_column in dim_refs:
            if dim_table != fact["name"]:
                continue
            expr = f'{q(fact["name"])}.{q(dim_column)}'
            try:
                rows = run_sql(f'SELECT {expr} AS K, AVG({measure["expr"]}) AS V '
                               f'FROM {source} GROUP BY {expr} ORDER BY 1 LIMIT 60')
            except RuntimeError as exc:
                samples.append(f"{dim_column}: query failed ({str(exc)[:50]})")
                continue
            values = [float(r["V"]) for r in rows if r.get("V") is not None]
            spread, _ = spread_of(values)
            samples.append(f"{dim_column}: spread {spread:.1%} over {len(values)} groups")
            if worst is None or spread > worst:
                worst, worst_dim = spread, dim_column
        if worst is None:
            continue
        verdicts.append({
            "aggregation": "AVG", "measure": measure["name"], "shape": "derived",
            "signal": "CUT" if worst < FLAT_THRESHOLD else "keep",
            "detail": (f"flat across every dimension tested -- best was {worst_dim} at "
                       f"{worst:.1%}. Report the flatness, do not chart it. "
                       if worst < FLAT_THRESHOLD else
                       f"varies {worst:.0%} across {worst_dim}. ") + "; ".join(samples)})
    return verdicts


def _walk(card: dict, plan: dict) -> dict:
    schema = card["schema"]
    dims = [c for t in card["tables"] for c in t["columns"]
            if c["semantic_role"] in ("categorical_dim", "state_flag")
            and not c.get("high_cardinality")]
    dim_refs = [(t["name"], c["name"]) for t in card["tables"] for c in t["columns"]
                if c in dims][:4]

    verdicts = []
    for metric in plan.get("headline", []):
        if metric["aggregation"] in ("ROWS_TOP_N", "HISTOGRAM"):
            verdicts.append({**metric, "signal": "n/a", "detail": "row or histogram output"})
            continue
        if metric["measure"] == "rows":
            verdicts.append({**metric, "signal": "keep", "detail": "row count"})
            continue
        table, column = metric["measure"].split(".", 1)
        expr = column_expr(card, table, column)
        agg = "AVG" if metric["aggregation"] not in ("SUM", "AVG", "COUNT") else metric["aggregation"]
        worst_spread, worst_dim, samples = None, None, []

        for dim_table, dim_column in dim_refs:
            if dim_table != table:
                continue
            try:
                rows = run_sql(
                    f'SELECT {q(dim_column)} AS K, {agg}({expr}) AS V '
                    f'FROM {q(schema, table)} GROUP BY 1 ORDER BY 1 LIMIT 60')
            except RuntimeError as exc:
                samples.append(f"{dim_column}: query failed ({str(exc)[:60]})")
                continue
            values = [float(r["V"]) for r in rows if r.get("V") is not None]
            spread, mean = spread_of(values)
            samples.append(f"{dim_column}: spread {spread:.1%} over {len(values)} groups")
            if worst_spread is None or spread > worst_spread:
                worst_spread, worst_dim = spread, dim_column

        if worst_spread is None:
            verdicts.append({**metric, "signal": "keep",
                             "detail": "no comparable dimension on this table; not testable"})
        elif worst_spread < FLAT_THRESHOLD:
            verdicts.append({**metric, "signal": "CUT",
                             "detail": f"flat across every dimension tested -- best was "
                                       f"{worst_dim} at {worst_spread:.1%}. "
                                       f"Report the flatness, do not chart it. "
                                       + "; ".join(samples)})
        else:
            verdicts.append({**metric, "signal": "keep",
                             "detail": f"varies {worst_spread:.0%} across {worst_dim}. "
                                       + "; ".join(samples)})
    verdicts += check_derived(card, plan, dim_refs)
    return {"verdicts": verdicts,
            "kept": [v for v in verdicts if v["signal"] != "CUT"],
            "cut": [v for v in verdicts if v["signal"] == "CUT"]}


def check(card: dict, plan: dict) -> dict:
    """Collect every probe, run them in one batch, then read the answers."""
    _BATCH.reset()
    _BATCH.mode = "collect"
    try:
        _walk(card, plan)          # output discarded; this pass only records SQL
    except RuntimeError:
        pass                       # nothing can legitimately fail while collecting
    _BATCH.flush()
    _BATCH.mode = "replay"
    return _walk(card, plan)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--json")
    args = ap.parse_args()
    card = json.load(open(args.card, encoding="utf-8"))
    card = card[0] if isinstance(card, list) else card
    result = check(card, json.load(open(args.plan, encoding="utf-8")))
    for v in result["verdicts"]:
        mark = "CUT " if v["signal"] == "CUT" else "keep"
        print(f"  [{mark}] {v['aggregation']}({v['measure']}) <{v['shape']}>")
        print(f"         {v['detail'][:190]}")
    print(f"\n{len(result['kept'])} kept, {len(result['cut'])} cut for lack of signal")
    if args.json:
        json.dump(result, open(args.json, "w", encoding="utf-8"),
                  indent=2, default=str)


if __name__ == "__main__":
    main()
