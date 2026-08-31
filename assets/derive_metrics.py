#!/usr/bin/env python3
"""Schema card + persona spec -> a metric plan, or a refusal.

    python3 derive_metrics.py --card card.json --persona cfo.json

The division of labour is deliberate. Reading a persona onto axes and writing
down the decisions they make is judgement, and is done by the agent following
references/persona-axes.md. Everything downstream of that is mechanical and
lives here, because these are the steps where a plausible-looking wrong answer
is easy to produce and hard to notice:

  gate       a decision whose data is not present is refused, never approximated
  legality   an aggregation illegal for a measure's additivity cannot be emitted
  coverage   decisions with no metric, and metric shapes never used, are reported
  negatives  what the dataset cannot answer is output, not silently omitted
"""

from __future__ import annotations

import argparse
import json
import sys

# --------------------------------------------------------------------------
# The legality matrix. This is the heart of it: what may be done with a measure
# is decided by its additivity class, never by what would look reasonable.
# --------------------------------------------------------------------------
LEGAL_AGGREGATIONS = {
    "additive": {
        "allow": ["SUM", "AVG", "MIN", "MAX", "COUNT"],
        "forbid": {},
        "note": "totals freely across every dimension including time",
    },
    "semi_additive": {
        "allow": ["SUM_AT_POINT_IN_TIME", "AVG", "MIN", "MAX", "LAST"],
        "forbid": {"SUM": "summing a level across time double counts it: a stock of 100 "
                          "held for 30 days is 100, not 3,000"},
        "note": "totals across entities at one instant; never across time",
    },
    "non_additive": {
        "allow": ["AVG", "MIN", "MAX", "MEDIAN", "PERCENTILE", "WEIGHTED_AVG"],
        "forbid": {"SUM": "adding rates or measurements together produces a number with no "
                          "meaning; re-derive the ratio from its numerator and denominator"},
        "note": "compare and average; recompute ratios from their parts",
    },
    "attribute": {
        "allow": ["AVG", "MIN", "MAX", "MEDIAN"],
        "forbid": {"SUM": "this describes a row rather than measuring an event; summing it "
                          "across a join repeats it once per matched row"},
        "note": "an attribute of the entity, not a quantity of anything",
    },
    "binary_indicator": {
        "allow": ["SUM", "AVG", "COUNT"],
        "forbid": {},
        "note": "SUM counts the positives, AVG is the rate; label which one is shown",
    },
    "count_or_rate": {
        "allow": ["SUM", "AVG", "COUNT"],
        "forbid": {},
        "note": "SUM counts the positives, AVG is the rate; label which one is shown",
    },
    "count_only": {
        "allow": ["COUNT", "COUNT_DISTINCT"],
        "forbid": {"SUM": "an identifier is a name, not a quantity; adding keys together is "
                          "arithmetic on labels"},
        "note": "count rows or distinct entities",
    },
    "not_applicable": {"allow": ["COUNT"], "forbid": {}, "note": "not a measure"},
}

# What a metric shape needs from the data before it can be built at all.
SHAPE_REQUIREMENTS = {
    "level":        {"tier": 0, "roles": []},
    "distribution": {"tier": 0, "roles": []},
    "outlier":      {"tier": 0, "roles": []},
    "trend":        {"tier": 1, "roles": ["temporal"]},
    "period_change":{"tier": 1, "roles": ["temporal"]},
    "composition":  {"tier": 2, "roles": ["categorical"]},
    "mix_shift":    {"tier": 2, "roles": ["temporal", "categorical"]},
    "per_entity":   {"tier": 3, "roles": ["entity"]},
    "concentration":{"tier": 3, "roles": ["entity"]},
    "worklist":     {"tier": 3, "roles": ["entity"]},
    "cohort":       {"tier": 3, "roles": ["temporal", "entity"]},
    "drill_path":   {"tier": 4, "roles": ["hierarchy"]},
}

# Altitude decides metric form, and whether individual rows belong on the page.
ALTITUDE_PROFILE = {
    "ic":       {"max_headline": 6, "prefer": ["level", "worklist", "outlier"],
                 "rows_allowed": True,  "prefer_ratios": False},
    "manager":  {"max_headline": 5, "prefer": ["level", "trend", "worklist", "composition"],
                 "rows_allowed": True,  "prefer_ratios": False},
    "director": {"max_headline": 5, "prefer": ["trend", "period_change", "composition",
                                               "concentration"],
                 "rows_allowed": True,  "prefer_ratios": True},
    "exec":     {"max_headline": 3, "prefer": ["trend", "period_change", "outlier"],
                 "rows_allowed": False, "prefer_ratios": True},
}

CADENCE_GRAIN = {"live": "minute", "hourly": "hour", "daily": "day",
                 "weekly": "week", "monthly": "month", "ad_hoc": "native"}


# --------------------------------------------------------------------------
def index_card(card: dict) -> dict:
    """Flatten a schema card into the role buckets the grammar composes from."""
    buckets = {"measures": [], "temporal": [], "categorical": [], "entity": [],
               "label": [], "binary": []}
    for table in card["tables"]:
        for column in table["columns"]:
            ref = {
                "table": table["name"], "column": column["name"],
                "role": column["semantic_role"], "additivity": column["additivity"],
                "confidence": column.get("confidence", "high"),
                "distinct": column.get("distinct"),
                "high_cardinality": column.get("high_cardinality", False),
                "cast": column.get("cast_expression"),
                "table_role": table["role"], "grain": table["grain"],
                "evidence": column.get("evidence", []),
            }
            role, additivity = column["semantic_role"], column["additivity"]
            if role in ("temporal_event", "temporal_scd"):
                buckets["temporal"].append(ref)
            elif role == "binary_indicator":
                buckets["binary"].append(ref)
                buckets["measures"].append(ref)
            elif role == "categorical_dim" or role == "state_flag":
                buckets["categorical"].append(ref)
            elif role == "entity_key":
                buckets["entity"].append(ref)
            elif role == "entity_label":
                buckets["label"].append(ref)
            elif additivity in ("additive", "semi_additive", "non_additive", "attribute"):
                buckets["measures"].append(ref)
    return buckets


def roles_present(card: dict) -> set[str]:
    """Every semantic role the dataset actually contains."""
    return {column["semantic_role"]
            for table in card["tables"] for column in table["columns"]}


def available_shapes(card: dict, buckets: dict) -> dict:
    """Which metric shapes this dataset can support, and why not when it cannot."""
    have = {
        "temporal": bool(buckets["temporal"]),
        "categorical": bool(buckets["categorical"]),
        "entity": bool(buckets["entity"]),
        "hierarchy": card["capabilities"].get("hierarchy_candidates", False),
    }
    result = {}
    for shape, need in SHAPE_REQUIREMENTS.items():
        missing = [role for role in need["roles"] if not have.get(role)]
        if missing:
            result[shape] = (False, f"no {' or '.join(missing)} column available")
        else:
            result[shape] = (True, "")
    return result


# --------------------------------------------------------------------------
def compose_metrics(decision: dict, buckets: dict, shapes: dict, profile: dict,
                    grain: str) -> list[dict]:
    """Generate candidate metrics for one decision from the grammar.

    <aggregation> of <measure> [per <entity>] [over <grain>] [by <dimension>]
                   [against <baseline>]
    """
    wanted_shapes = [s for s in decision.get("shapes", profile["prefer"])
                     if shapes.get(s, (False, ""))[0]]
    candidates = []
    measures = buckets["measures"] or [None]
    ROW_SHAPES = {"worklist", "outlier"}
    DISTRIBUTION_SHAPES = {"distribution"}

    for shape in wanted_shapes:
        if shape in ROW_SHAPES:
            if not profile["rows_allowed"]:
                continue
            order_by = next((m for m in measures if m and m["additivity"]
                             not in ("count_or_rate", "binary_indicator", "count_only")),
                            next((m for m in measures if m), None))
            label = next(iter(buckets["label"] or buckets["entity"] or []), None)
            candidates.append({
                "decision": decision["id"], "shape": shape,
                "aggregation": "ROWS_TOP_N",
                "measure": (f"{order_by['table']}.{order_by['column']}" if order_by
                            else "rows"),
                "additivity": order_by["additivity"] if order_by else "count_only",
                "grain": "row", "slice": None,
                "baseline": "ranked tail" if shape == "outlier" else "oldest first",
                "confidence": order_by["confidence"] if order_by else "high",
                "cast": None,
                "identified_by": (f"{label['table']}.{label['column']}" if label else None),
                "warnings": ["row-level output: only appropriate because this persona acts "
                             "on individual records"],
                "forbidden": {},
            })
            continue
        if shape in DISTRIBUTION_SHAPES:
            for measure in [m for m in measures if m]:
                candidates.append({
                    "decision": decision["id"], "shape": shape, "aggregation": "HISTOGRAM",
                    "measure": f"{measure['table']}.{measure['column']}",
                    "additivity": measure["additivity"], "grain": "binned",
                    "slice": None, "baseline": None,
                    "confidence": measure["confidence"], "cast": measure["cast"],
                    "warnings": [], "forbidden": {},
                })
            continue
        for measure in measures:
            if measure is None:
                candidates.append({
                    "decision": decision["id"], "shape": shape, "aggregation": "COUNT",
                    "measure": "rows", "additivity": "count_only", "grain": grain,
                    "slice": None, "baseline": "prior period" if shape in
                    ("trend", "period_change", "mix_shift") else None,
                    "confidence": "high", "warnings": [],
                })
                continue
            rules = LEGAL_AGGREGATIONS.get(measure["additivity"], LEGAL_AGGREGATIONS["not_applicable"])
            aggregation = decision.get("prefer_aggregation")
            if aggregation not in rules["allow"]:
                aggregation = rules["allow"][0]
            warnings = []
            if measure["confidence"] == "low":
                warnings.append(f"{measure['column']} was classified with low confidence: "
                                + "; ".join(measure["evidence"][-1:]))
            if measure["additivity"] == "attribute":
                warnings.append(f"{measure['column']} describes a row; it is averaged, never "
                                f"totalled, and must not be summed across a join")
            if measure["additivity"] == "semi_additive":
                warnings.append(f"{measure['column']} is a level: totalled across entities at "
                                f"one instant, never across {grain}s")
            slices = [None]
            if shape in ("composition", "mix_shift") and buckets["categorical"]:
                slices = [c for c in buckets["categorical"] if not c["high_cardinality"]] or \
                         buckets["categorical"][:1]
            for slice_column in slices:
                candidates.append({
                    "decision": decision["id"], "shape": shape, "aggregation": aggregation,
                    "measure": f"{measure['table']}.{measure['column']}",
                    "additivity": measure["additivity"],
                    "grain": grain if shape in ("trend", "period_change", "mix_shift", "cohort")
                             else "as-of",
                    "slice": f"{slice_column['table']}.{slice_column['column']}"
                             if slice_column else None,
                    "baseline": "prior period" if shape in ("trend", "period_change", "mix_shift")
                                else ("threshold" if shape == "outlier" else None),
                    "confidence": measure["confidence"],
                    "cast": measure["cast"], "warnings": warnings,
                    "forbidden": rules["forbid"],
                })
    return candidates


def rank_and_prune(candidates: list[dict], profile: dict) -> list[dict]:
    """Keep the persona's headline budget, preferring their shapes and sure measures."""
    order = {shape: index for index, shape in enumerate(profile["prefer"])}

    def score(metric):
        return (order.get(metric["shape"], 99),
                0 if metric["confidence"] == "high" else 1,
                0 if metric["slice"] is None else 1)

    seen, kept = set(), []
    for metric in sorted(candidates, key=score):
        key = (metric["shape"], metric["measure"], metric["slice"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(metric)
    return kept


# --------------------------------------------------------------------------
def derive(card: dict, persona: dict) -> dict:
    axes = persona["axes"]
    profile = ALTITUDE_PROFILE.get(axes.get("altitude", "manager"),
                                   ALTITUDE_PROFILE["manager"])
    grain = CADENCE_GRAIN.get(axes.get("cadence", "monthly"), "month")
    buckets = index_card(card)
    shapes = available_shapes(card, buckets)

    have_roles = roles_present(card)
    supported, refused = [], []
    for decision in persona["decisions"]:
        # Subject gate first: no amount of chart-shape availability substitutes for
        # the thing the decision is about not being in the data.
        missing_subject = [role for role in decision.get("requires_roles", [])
                           if role not in have_roles]
        if missing_subject:
            refused.append({"decision": decision, "reasons": [
                (role, f"no column in this dataset carries the role '{role}', which this "
                       f"decision is about") for role in missing_subject]})
            continue
        needed = decision.get("shapes", profile["prefer"])
        blocked = [(shape, shapes[shape][1]) for shape in needed
                   if not shapes.get(shape, (False, "unknown shape"))[0]]
        if blocked and len(blocked) == len(needed):
            refused.append({"decision": decision, "reasons": blocked})
        else:
            supported.append((decision, blocked))

    plan = []
    for decision, blocked in supported:
        metrics = rank_and_prune(compose_metrics(decision, buckets, shapes, profile, grain),
                                 profile)
        plan.append({"decision": decision, "partial": blocked, "metrics": metrics})

    headline, depth = [], 0
    while len(headline) < profile["max_headline"]:
        added = False
        for entry in plan:
            if depth < len(entry["metrics"]) and len(headline) < profile["max_headline"]:
                headline.append(entry["metrics"][depth])
                added = True
        if not added:
            break
        depth += 1

    # Coverage: every decision must move at least one number, and shapes the
    # dataset supports but nothing uses are reported as unexploited.
    uncovered = [entry["decision"]["id"] for entry in plan if not entry["metrics"]]
    used_shapes = {m["shape"] for entry in plan for m in entry["metrics"]}
    unused = [shape for shape, (ok, _) in shapes.items() if ok and shape not in used_shapes]

    return {
        "persona": persona["persona"], "axes": axes, "grain": grain,
        "derived_measures": persona.get("derived_measures", []),
        "prefer_slices": persona.get("prefer_slices", []),
        "prefer_entities": persona.get("prefer_entities", []),
        "prefer_time": persona.get("prefer_time", []),
        "show_measures": persona.get("show_measures"),
        "dataset": {"schema": card["schema"], "tier": card["tier"]},
        "refused_decisions": refused,
        "plan": plan,
        "headline": headline,
        "coverage": {
            "decisions_total": len(persona["decisions"]),
            "decisions_refused": len(refused),
            "decisions_uncovered": uncovered,
            "shapes_available_unused": unused,
        },
        "negative_coverage": [
            f"{shape}: {why}" for shape, (ok, why) in sorted(shapes.items()) if not ok
        ],
        "buildable": len(refused) < len(persona["decisions"]),
    }


# --------------------------------------------------------------------------
def render(result: dict) -> str:
    out = [f"PERSONA   {result['persona']}",
           f"DATASET   {result['dataset']['schema']} (tier {result['dataset']['tier']})",
           f"GRAIN     {result['grain']}", ""]

    if not result["buildable"]:
        out.append("REFUSED -- this dataset cannot support this persona.")
        out.append("")
        for item in result["refused_decisions"]:
            out.append(f"  decision: {item['decision']['statement']}")
            for shape, why in item["reasons"]:
                out.append(f"    x {shape}: {why}")
        out.append("")
        out.append("  Nothing is substituted. Building a lookalike dashboard from whatever")
        out.append("  columns happen to exist would answer a question nobody asked.")
        owned = result["axes"].get("owned_object")
        if owned:
            out.append("")
            out.append(f"  This persona owns: {owned}. That subject is not represented in")
            out.append(f"  {result['dataset']['schema']}. Point them at a dataset that carries it,")
            out.append("  or pick a persona whose subject this data actually holds.")
        return "\n".join(out)

    out.append(f"HEADLINE METRICS ({len(result['headline'])})")
    for metric in result["headline"]:
        slice_text = f" by {metric['slice']}" if metric["slice"] else ""
        base = f" vs {metric['baseline']}" if metric["baseline"] else ""
        flag = "  [!]" if metric["confidence"] == "low" else ""
        out.append(f"  - {metric['aggregation']}({metric['measure']}){slice_text}"
                   f" over {metric['grain']}{base}   <{metric['shape']}>{flag}")
        for warning in metric.get("warnings", []):
            out.append(f"      ! {warning}")
        for aggregation, reason in (metric.get("forbidden") or {}).items():
            out.append(f"      x {aggregation} is illegal here: {reason}")
    out.append("")

    if result["refused_decisions"]:
        out.append("REFUSED DECISIONS (the rest of the persona is still buildable)")
        for item in result["refused_decisions"]:
            out.append(f"  - {item['decision']['statement']}")
            for shape, why in item["reasons"]:
                out.append(f"      x {shape}: {why}")
        out.append("")

    coverage = result["coverage"]
    out.append("COVERAGE")
    out.append(f"  decisions: {coverage['decisions_total'] - coverage['decisions_refused']}"
               f"/{coverage['decisions_total']} answerable")
    if coverage["decisions_uncovered"]:
        out.append(f"  NOT COVERED: {', '.join(coverage['decisions_uncovered'])}")
    if coverage["shapes_available_unused"]:
        out.append(f"  available but unused: {', '.join(coverage['shapes_available_unused'])}")
    out.append("")
    out.append("WHAT THIS DATASET CANNOT DO")
    for line in result["negative_coverage"]:
        out.append(f"  - {line}")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--json", metavar="PATH")
    args = parser.parse_args()

    card = json.load(open(args.card, encoding="utf-8"))
    if isinstance(card, list):
        card = card[0]
    persona = json.load(open(args.persona, encoding="utf-8"))
    result = derive(card, persona)
    print(render(result))
    if args.json:
        json.dump(result, open(args.json, "w", encoding="utf-8"),
                  indent=2, default=str)
    sys.exit(0 if result["buildable"] else 3)


if __name__ == "__main__":
    main()
