#!/usr/bin/env python3
"""Catalog-first schema profiler: any Exasol schema -> a schema card.

The schema card is the only thing the persona derivation is allowed to read
about a dataset. It deliberately describes data by *semantic role* and
*additivity*, never by table or column name, so the derivation cannot become
shaped around one particular dataset.

    python3 profile_schema.py TPCH ENERGY WEATHER
    python3 profile_schema.py TPCH --json card.json

Design rules:
  - Catalog first. Row counts, types, keys and comments come from EXA_ALL_*,
    which is free. Only then does it touch data.
  - Bounded. Above --sample-rows the profile runs on a bounded subquery and
    the card records `sampled: true`. Distinct counts switch to approximate.
  - Honest. Every classification carries the evidence that produced it, so a
    reviewer can overrule it. The card is an input to judgement, not an oracle.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict

EXAPUMP = "exapump"

# Above this row count, profile a bounded subquery instead of the whole table.
DEFAULT_SAMPLE_ROWS = 200_000
# Above this row count, use APPROXIMATE_COUNT_DISTINCT instead of exact.
APPROX_DISTINCT_ABOVE = 1_000_000
# Text is only re-typed when nearly every value agrees; one stray row must not
# turn a genuine text column into a broken measure.
TYPE_INFERENCE_AGREEMENT = 0.95
TYPE_INFERENCE_SAMPLE = 2000
# Delimited formats only: a bare integer must stay a number, not become a date.
DATE_FORMATS = [
    "YYYY-MM-DD HH24:MI:SS", "YYYY-MM-DD", "DD-MM-YYYY", "MM-DD-YYYY",
    "DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "DD.MM.YYYY",
]

# A column with at most this many distinct values is a candidate dimension.
CATEGORICAL_MAX_DISTINCT = 200
# ...or at most this share of rows, whichever is stricter on big tables.
CATEGORICAL_MAX_RATIO = 0.05
# A lifecycle status has a handful of values. Anything wider that merely happens
# to contain a status word -- "State" as in geography -- is an ordinary dimension.
STATE_FLAG_MAX_DISTINCT = 50
# Above CATEGORICAL_MAX_DISTINCT a dimension is still usable, but only ranked and
# truncated -- never as a full axis or a filter listing every value.
HIGH_CARDINALITY_DIM_MAX = 20_000


# --------------------------------------------------------------------------
# name hints -- weak signals only, never decisive on their own
# --------------------------------------------------------------------------
HINTS = {
    "rate": r"(_|^)(rate|pct|percent|ratio|share|margin|discount|factor|index|score)(_|$)",
    "level": r"(_|^)(balance|level|onhand|on_hand|stock|inventory|"
             r"headcount|capacity|position|backlog)(_|$)",
    # Explicit per-unit wording only.
    "unit_price": r"(_|^)(unit_price|unit_cost|rate_per|per_unit|price_each|"
                  r"list_price|standard_cost)(_|$)",
    # Bare price/cost: could be either, so it is resolved as an amount and flagged.
    "price_or_cost": r"(_|^)(price|cost|amount_paid|fee|charge_amount)(_|$)",
    "amount": r"(_|^)(amount|amt|revenue|sales|total|value|spend|charge|"
              r"subtotal|gross|net|profit|earnings|income|turnover)(_|$)",
    "quantity": r"(_|^)(qty|quantity|units|count|volume|weight)(_|$)",
    "key": r"(_|^)(id|key|code|no|num|number|sk|uuid|guid)(_|$)|(key|id|sk|uuid|guid)$",
    # Descriptive text that names a row rather than grouping rows.
    "label_name": r"(_|^)(name|address|addr|phone|email|title|label|url|postcode|zip)(_|$)|"
                  r"(name|address|phone|email)$",
    "text_blob": r"(_|^)(comment|comments|description|desc|notes|note|remarks|body|text)(_|$)|"
                 r"(comment|description|notes)$",
    "measurement": r"(_|^)(temp|temperature|humidity|pressure|speed|lat|latitude|lon|"
                   r"longitude|altitude|reading|celsius|fahrenheit)(_|$)",
    # Unit suffixes that denote an intensity (a per-something), which is never
    # summable however it is named: kmh, mph, rpm, psi, degrees C/F, per_hour.
    "intensity_unit": r"(_|^)(kmh|kph|mph|rpm|psi|bpm|hz|mbar|c|f|k|deg|degrees|"
                      r"per_hour|per_day|per_capita|per_unit)$",
    # Genuine lifecycle words only. category/segment/type/priority are ordinary
    # business dimensions and already classify as categorical on cardinality.
    "status": r"(_|^)(status|state|flag|stage|phase|disposition)(_|$)",
    "effective_from": r"(_|^)(effective_from|valid_from|start_date|startdate|from_date|"
                      r"eff_from|dbt_valid_from)(_|$)",
    "effective_to": r"(_|^)(effective_to|valid_to|end_date|enddate|to_date|expiry|"
                    r"expires|eff_to|dbt_valid_to)(_|$)",
}


MONEY_WORDS = ("price", "cost", "amount", "revenue", "sales", "charge", "fee",
               "profit", "spend", "payment", "billing", "invoice", "turnover")


def carries_money_word(name: str) -> bool:
    """Substring match: money vocabulary is often glued into a compound name."""
    return any(word in normalise_name(name).replace("_", "") for word in MONEY_WORDS)


def normalise_name(name: str) -> str:
    """Spaces, hyphens, dots and camelCase all become underscore-separated.

    Uploaded files rarely use snake_case. Without this, "Postal Code",
    "Sub-Category" and "shippingCost" match none of the rules below.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[\s\-.]+", "_", spaced).strip("_").lower()


def hits(hint: str, name: str) -> bool:
    return bool(re.search(HINTS[hint], normalise_name(name)))


# --------------------------------------------------------------------------
# SQL plumbing
# --------------------------------------------------------------------------
def run_sql(sql: str) -> list[dict]:
    """Run one SELECT through exapump and return rows as dicts."""
    proc = subprocess.run(
        [EXAPUMP, "sql", "-f", "json", sql],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"query failed: {proc.stderr.strip()[:400]}\nSQL: {sql[:400]}")
    text = proc.stdout
    start = text.find("\n[")
    if start == -1:
        start = text.find("[")
        if start == -1:
            return []
    try:
        return json.loads(text[start:].strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse exapump output: {exc}\n{text[-400:]}") from exc


def q(*parts: str) -> str:
    """Quote an identifier path: q('S','T') -> "S"."T"."""
    return ".".join('"' + p.replace('"', '""') + '"' for p in parts)


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------
# type helpers
# --------------------------------------------------------------------------
def type_family(column_type: str) -> str:
    upper = column_type.upper()
    if upper.startswith(("DECIMAL", "NUMBER", "INTEGER", "BIGINT", "SMALLINT", "DOUBLE", "FLOAT")):
        return "numeric"
    if upper.startswith(("TIMESTAMP", "DATE")):
        return "temporal"
    if upper.startswith(("VARCHAR", "CHAR", "CLOB")):
        return "text"
    if upper.startswith("BOOLEAN"):
        return "boolean"
    if upper.startswith("INTERVAL"):
        return "interval"
    return "other"


def column_is_integral(column: dict) -> bool:
    """Integrality of the values, whatever the column is declared as."""
    if column.get("inferred_family") == "numeric":
        values = [column.get("min"), column.get("max")]
        return all(v is not None and float(v) == int(float(v)) for v in values if v is not None)
    return is_integral(column["type"])


def is_integral(column_type: str) -> bool:
    match = re.match(r"DECIMAL\((\d+),\s*(\d+)\)", column_type.upper())
    if match:
        return int(match.group(2)) == 0
    return column_type.upper().startswith(("INTEGER", "BIGINT", "SMALLINT"))


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------
def load_catalog(schema: str) -> dict:
    tables = {
        row["TABLE_NAME"]: {
            "name": row["TABLE_NAME"],
            "row_count": int(row["TABLE_ROW_COUNT"] or 0),
            "comment": row.get("TABLE_COMMENT") or "",
            "columns": {},
            "primary_key": [],
        }
        for row in run_sql(
            "SELECT TABLE_NAME, TABLE_ROW_COUNT, TABLE_COMMENT FROM SYS.EXA_ALL_TABLES "
            f"WHERE TABLE_SCHEMA = {sql_str(schema)}"
        )
    }
    for row in run_sql(
        "SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_ORDINAL_POSITION, "
        "COLUMN_IS_NULLABLE, COLUMN_COMMENT FROM SYS.EXA_ALL_COLUMNS "
        f"WHERE COLUMN_SCHEMA = {sql_str(schema)} ORDER BY COLUMN_TABLE, COLUMN_ORDINAL_POSITION"
    ):
        table = tables.get(row["COLUMN_TABLE"])
        if table is None:
            continue
        table["columns"][row["COLUMN_NAME"]] = {
            "name": row["COLUMN_NAME"],
            "type": row["COLUMN_TYPE"],
            "type_family": type_family(row["COLUMN_TYPE"]),
            "nullable": str(row.get("COLUMN_IS_NULLABLE")).lower() == "true",
            "comment": row.get("COLUMN_COMMENT") or "",
            "position": int(row["COLUMN_ORDINAL_POSITION"]),
        }
    for row in run_sql(
        "SELECT CONSTRAINT_TABLE, CONSTRAINT_TYPE, COLUMN_NAME, ORDINAL_POSITION, "
        "REFERENCED_TABLE, REFERENCED_COLUMN FROM SYS.EXA_ALL_CONSTRAINT_COLUMNS "
        f"WHERE CONSTRAINT_SCHEMA = {sql_str(schema)} AND CONSTRAINT_TYPE <> 'NOT NULL' "
        "ORDER BY CONSTRAINT_TABLE, ORDINAL_POSITION"
    ):
        table = tables.get(row["CONSTRAINT_TABLE"])
        if table is None:
            continue
        if row["CONSTRAINT_TYPE"] == "PRIMARY KEY":
            table["primary_key"].append(row["COLUMN_NAME"])
        elif row["CONSTRAINT_TYPE"] == "FOREIGN KEY" and row.get("REFERENCED_TABLE"):
            table.setdefault("declared_foreign_keys", []).append({
                "column": row["COLUMN_NAME"],
                "references_table": row["REFERENCED_TABLE"],
                "references_column": row["REFERENCED_COLUMN"],
            })
    return tables


# --------------------------------------------------------------------------
# data profiling
# --------------------------------------------------------------------------
def profile_table(schema: str, table: dict, sample_rows: int) -> None:
    columns = list(table["columns"].values())
    if not columns:
        return
    row_count = table["row_count"]
    sampled = row_count > sample_rows
    source = (f"(SELECT * FROM {q(schema, table['name'])} LIMIT {sample_rows})"
              if sampled else q(schema, table["name"]))
    distinct_fn = "APPROXIMATE_COUNT_DISTINCT" if row_count > APPROX_DISTINCT_ABOVE else "COUNT"
    distinct_arg = "{col}" if distinct_fn.startswith("APPROX") else "DISTINCT {col}"
    table["sampled"] = sampled

    # Batch so a 400-column table does not build one enormous statement.
    for batch_start in range(0, len(columns), 12):
        batch = columns[batch_start:batch_start + 12]
        selects = ["COUNT(*) AS N_ROWS"]
        for index, column in enumerate(batch):
            col = q(column["name"])
            selects.append(f"COUNT({col}) AS NN_{index}")
            selects.append(f"{distinct_fn}({distinct_arg.format(col=col)}) AS ND_{index}")
            if column["type_family"] in ("numeric", "temporal"):
                selects.append(f"CAST(MIN({col}) AS VARCHAR(64)) AS MN_{index}")
                selects.append(f"CAST(MAX({col}) AS VARCHAR(64)) AS MX_{index}")
            if column["type_family"] == "numeric":
                selects.append(f"CAST(AVG({col}) AS VARCHAR(64)) AS AV_{index}")
                selects.append(f"SUM(CASE WHEN {col} < 0 THEN 1 ELSE 0 END) AS NEG_{index}")
            if column["type_family"] == "text":
                selects.append(f"CAST(AVG(LENGTH({col})) AS VARCHAR(64)) AS AL_{index}")
        rows = run_sql("SELECT " + ", ".join(selects) + " FROM " + source)
        if not rows:
            continue
        stats = rows[0]
        observed = int(stats["N_ROWS"] or 0)
        table["profiled_rows"] = observed
        for index, column in enumerate(batch):
            non_null = int(stats.get(f"NN_{index}") or 0)
            distinct = int(stats.get(f"ND_{index}") or 0)
            column["non_null"] = non_null
            column["distinct"] = distinct
            column["null_rate"] = round(1 - non_null / observed, 4) if observed else None
            column["distinct_ratio"] = round(distinct / observed, 4) if observed else None
            column["unique"] = observed > 0 and distinct == observed and non_null == observed
            for key, field in (("MN", "min"), ("MX", "max"), ("AV", "mean"),
                               ("AL", "avg_length"), ("NEG", "negatives")):
                value = stats.get(f"{key}_{index}")
                if value is not None:
                    column[field] = value


def infer_text_types(schema: str, table: dict, sample_rows: int) -> None:
    """Re-type text columns from their contents.

    JSON, CSV and spreadsheet uploads routinely carry every value as a string.
    Without this pass a file whose sales, quantity and dates are all quoted text
    profiles as tier 0 -- no measures, no trends -- which is both useless and
    wrong. Storage type is kept alongside the inferred one, and a cast expression
    is recorded so generated SQL converts explicitly rather than by accident.
    """
    text_columns = [c for c in table["columns"].values() if c["type_family"] == "text"]
    if not text_columns:
        return
    source = q(schema, table["name"])

    for batch_start in range(0, len(text_columns), 8):
        batch = text_columns[batch_start:batch_start + 8]
        selects, sources = [], []
        for index, column in enumerate(batch):
            col = q(column["name"])
            sub = (f"(SELECT {col} AS V FROM {source} WHERE {col} IS NOT NULL "
                   f"AND LENGTH(TRIM({col})) > 0 LIMIT {TYPE_INFERENCE_SAMPLE})")
            sources.append((index, sub))
        for index, sub in sources:
            parts = ["COUNT(*) AS N", "SUM(CASE WHEN IS_NUMBER(V) THEN 1 ELSE 0 END) AS NUM_OK"]
            for f_index, fmt in enumerate(DATE_FORMATS):
                parts.append(f"SUM(CASE WHEN IS_DATE(V, '{fmt}') THEN 1 ELSE 0 END) AS DT_{f_index}")
            rows = run_sql(f"SELECT {', '.join(parts)} FROM {sub} s")
            if not rows:
                continue
            stats = rows[0]
            total = int(stats["N"] or 0)
            if not total:
                continue
            column = batch[index]
            scores = {fmt: int(stats.get(f"DT_{i}") or 0) / total
                      for i, fmt in enumerate(DATE_FORMATS)}
            best_format, best_score = max(scores.items(), key=lambda kv: kv[1])
            numeric_score = int(stats["NUM_OK"] or 0) / total

            if best_score >= TYPE_INFERENCE_AGREEMENT:
                column["inferred_family"] = "temporal"
                column["stored_as"] = "text"
                column["date_format"] = best_format
                column["cast_expression"] = f"TO_DATE({q(column['name'])}, '{best_format}')"
                column["inference_note"] = (
                    f"stored as text; {best_score:.0%} of sampled values parse as "
                    f"{best_format}, so it is read as a date")
                rivals = [f for f, sc in scores.items()
                          if sc >= TYPE_INFERENCE_AGREEMENT and f != best_format
                          and set(f) == set(best_format)]
                if rivals:
                    column["ambiguous_date_format"] = rivals
                    column["inference_note"] += (
                        f" -- WARNING: also parses as {rivals[0]}; day/month order "
                        f"could not be settled from the data")
            elif numeric_score >= TYPE_INFERENCE_AGREEMENT:
                column["inferred_family"] = "numeric"
                column["stored_as"] = "text"
                column["cast_expression"] = f"CAST({q(column['name'])} AS DOUBLE)"
                column["inference_note"] = (
                    f"stored as text; {numeric_score:.0%} of sampled values parse as "
                    f"numbers, so it is read as a measure")

    # Numeric statistics for the re-typed columns, guarded so an unparseable row
    # cannot abort the whole profile.
    retyped = [c for c in text_columns if c.get("inferred_family") == "numeric"]
    for batch_start in range(0, len(retyped), 8):
        batch = retyped[batch_start:batch_start + 8]
        selects = []
        for index, column in enumerate(batch):
            col = q(column["name"])
            safe = f"CASE WHEN IS_NUMBER({col}) THEN CAST({col} AS DOUBLE) END"
            selects.append(f"CAST(MIN({safe}) AS VARCHAR(64)) AS MN_{index}")
            selects.append(f"CAST(MAX({safe}) AS VARCHAR(64)) AS MX_{index}")
            selects.append(f"CAST(AVG({safe}) AS VARCHAR(64)) AS AV_{index}")
            selects.append(f"SUM(CASE WHEN {safe} < 0 THEN 1 ELSE 0 END) AS NEG_{index}")
        rows = run_sql("SELECT " + ", ".join(selects) + " FROM " + source)
        if not rows:
            continue
        for index, column in enumerate(batch):
            for key, field in (("MN", "min"), ("MX", "max"), ("AV", "mean"), ("NEG", "negatives")):
                value = rows[0].get(f"{key}_{index}")
                if value is not None:
                    column[field] = value

    retyped_dates = [c for c in text_columns if c.get("inferred_family") == "temporal"]
    for column in retyped_dates:
        col, fmt = q(column["name"]), column["date_format"]
        safe = f"CASE WHEN IS_DATE({col}, '{fmt}') THEN TO_DATE({col}, '{fmt}') END"
        rows = run_sql(f"SELECT CAST(MIN({safe}) AS VARCHAR(32)) AS MN, "
                       f"CAST(MAX({safe}) AS VARCHAR(32)) AS MX FROM {source}")
        if rows:
            column["min"], column["max"] = rows[0].get("MN"), rows[0].get("MX")


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def classify_table_role(table: dict, all_tables: dict) -> None:
    """fact_like | dimension_like | flat | lookup -- decided by shape, not name."""
    row_count = table["row_count"]
    columns = list(table["columns"].values())
    key_like = [c for c in columns if c.get("role_hint_key")]
    temporal = [c for c in columns if c["type_family"] == "temporal"]
    measures = [c for c in columns if c.get("measure_candidate")]
    counts = [t["row_count"] for t in all_tables.values() if t["row_count"] > 0]
    median_rows = sorted(counts)[len(counts) // 2] if counts else 0

    evidence = []
    if len(all_tables) == 1:
        table["role"] = "flat"
        evidence.append("only table in the schema; dimensions are inline")
    elif temporal and row_count >= max(median_rows, 1) and key_like:
        table["role"] = "fact_like"
        evidence.append(f"{len(key_like)} key-like column(s), {len(temporal)} temporal "
                        f"column(s) and {len(measures)} measure(s), at or above the schema "
                        f"median row count: it records events in time")
    elif not temporal and key_like:
        table["role"] = "dimension_like"
        evidence.append("carries keys but no temporal column at all, so it describes things "
                        "rather than recording events; its numerics are attributes of the key, "
                        "not quantities to sum")
    elif row_count < median_rows and table["primary_key"]:
        table["role"] = "dimension_like"
        evidence.append("declared primary key and row count below schema median")
    elif len(columns) <= 3 and row_count < median_rows:
        table["role"] = "lookup"
        evidence.append("narrow and small")
    else:
        table["role"] = "dimension_like"
        evidence.append("no fact signature detected; treated as descriptive")
    table["role_evidence"] = evidence

    if table["primary_key"]:
        table["grain"] = list(table["primary_key"])
        table["grain_evidence"] = "declared primary key"
    else:
        unique = [c["name"] for c in columns if c.get("unique")]
        if unique:
            table["grain"] = [unique[0]]
            table["grain_evidence"] = f"{unique[0]} is unique across profiled rows"
        else:
            table["grain"] = []
            table["grain_evidence"] = "no unique column found; grain unknown"


def looks_binary(column: dict) -> bool:
    """Exactly two values, 0 and 1 -- a flag, whatever it is called."""
    if (column.get("distinct") or 0) != 2:
        return False
    try:
        return float(column.get("min")) == 0.0 and float(column.get("max")) == 1.0
    except (TypeError, ValueError):
        return False


def looks_like_rate(column: dict) -> bool:
    """A fraction, detected from its values rather than from its name."""
    if column_is_integral(column):
        return False
    try:
        low, high = float(column.get("min")), float(column.get("max"))
    except (TypeError, ValueError):
        return False
    distinct = column.get("distinct") or 0
    return 0.0 <= low and high <= 1.0 and 0 < distinct <= 100


def classify_column(column: dict, table: dict) -> None:
    """Assign a semantic role and an additivity class, with evidence."""
    name = column["name"]
    family = column.get("inferred_family", column["type_family"])
    distinct = column.get("distinct") or 0
    ratio = column.get("distinct_ratio")
    evidence = []
    role = "unknown"
    additivity = "not_applicable"
    confidence = "high"

    in_pk = name in table.get("primary_key", [])
    entity_grained = table.get("role") == "flat" and not any(
        c["type_family"] == "temporal" or c.get("inferred_family") == "temporal"
        for c in table["columns"].values())
    dimension_table = table.get("role") in ("dimension_like", "lookup") or entity_grained
    table_rows = table.get("profiled_rows") or table.get("row_count") or 0

    if distinct <= 1 and column.get("non_null"):
        column["semantic_role"] = "constant"
        column["additivity"] = "not_applicable"
        column["confidence"] = "high"
        column["evidence"] = [f"only {distinct} distinct value; carries no information "
                              f"and must not become a filter or a series"]
        column["measure_candidate"] = False
        return

    if family == "temporal":
        if hits("effective_from", name) or hits("effective_to", name):
            role = "temporal_scd"
            evidence.append("name matches an SCD validity-window pattern")
        else:
            role = "temporal_event"
            evidence.append("temporal type")
        if column.get("min") and column.get("max"):
            evidence.append(f"spans {column['min']} to {column['max']}")

    elif family == "boolean":
        role, additivity = "state_flag", "count_only"
        evidence.append("boolean type")

    elif family == "numeric":
        if in_pk or (column.get("unique") and hits("key", name)):
            role, additivity = "entity_key", "count_only"
            evidence.append("part of the primary key" if in_pk else "unique and key-named")
        elif hits("key", name) and column_is_integral(column):
            role, additivity = "entity_key", "count_only"
            evidence.append("key-named integer identifying a row" if (ratio or 0) > 0.9
                            else "key-named integer with repeating values; likely a foreign key")
        elif looks_binary(column):
            role, additivity = "binary_indicator", "count_or_rate"
            evidence.append("only the values 0 and 1 occur: a yes/no flag. Its total is a "
                            "count of positives and its mean is a rate -- never report it "
                            "as an ordinary sum")
        elif hits("rate", name):
            role, additivity = "monetary_rate", "non_additive"
            evidence.append("name denotes a rate or ratio; sums are meaningless")
        elif looks_like_rate(column):
            role, additivity = "monetary_rate", "non_additive"
            evidence.append(f"values lie within [0,1] across only {distinct} distinct "
                            f"non-integral steps; a rate, whatever it is named")
        elif hits("measurement", name) or hits("intensity_unit", name):
            role, additivity = "measurement", "non_additive"
            evidence.append("physical measurement or an intensity unit; "
                            "averageable, never summable")
        elif hits("level", name):
            role, additivity = "level", "semi_additive"
            evidence.append("stock or level measure; sum across entities, never across time")
        elif hits("unit_price", name):
            role = "monetary_unit_price"
            additivity = "attribute" if dimension_table else "non_additive"
            evidence.append("per-unit price or cost; must be multiplied by a quantity, not summed")
        elif hits("price_or_cost", name):
            if dimension_table:
                role, additivity = "monetary_unit_price", "attribute"
                evidence.append("price or cost on a descriptive table; a per-unit rate that "
                                "fans out if summed across a join")
            else:
                role, additivity, confidence = "monetary_amount", "additive", "low"
                evidence.append("bare 'price'/'cost' on a fact-like table is ambiguous -- read "
                                "as an extended amount, but CONFIRM it is not a unit rate")
        elif dimension_table and distinct <= CATEGORICAL_MAX_DISTINCT and column_is_integral(column):
            role, additivity = "categorical_dim", "count_only"
            evidence.append(f"only {distinct} distinct integer values on a descriptive table; "
                            f"behaves as a category")
        elif dimension_table:
            role, additivity = "numeric_attribute", "attribute"
            evidence.append("numeric column on a descriptive table; summing it across a join "
                            "to a finer-grain table fans out and overstates the total")
            if not any(c["type_family"] == "temporal" or c.get("inferred_family") == "temporal"
                       for c in table["columns"].values()):
                confidence = "low"
                evidence.append("its table carries no time column, so this is a state that "
                                "happens to be true now -- it has no period to be summed over")
            if entity_grained:
                confidence = "low"
                evidence.append("one row per entity and no time column, so this describes the "
                                "entity. CONFIRM which it is: an extensive amount (money, a "
                                "count) totals meaningfully; an intensive property (an age, a "
                                "score, a rating) must be averaged instead")
        elif hits("amount", name) or carries_money_word(name):
            role, additivity = "monetary_amount", "additive"
            evidence.append("monetary vocabulary in the name and an additive numeric on a "
                            "fact-like table: an extended amount")
        elif hits("quantity", name):
            role, additivity = "quantity", "additive"
            evidence.append("quantity measure on a fact-like table")
        elif distinct <= CATEGORICAL_MAX_DISTINCT and column_is_integral(column):
            role, additivity = "categorical_dim", "count_only"
            evidence.append(f"only {distinct} distinct integer values and no measure rule "
                            f"matched; read as a code rather than a quantity")
        else:
            role, additivity = "quantity", "additive"
            wide = (ratio or 0) > 0.5 and str(column.get("negatives", "0")) == "0"
            if wide:
                confidence = "medium"
                evidence.append("high-cardinality, strictly positive numeric on a fact-like "
                                "table; consistent with an amount, so treated as additive")
            else:
                confidence = "low"
                evidence.append("no rule matched; assumed additive because it is a numeric on "
                                "a fact-like table -- CONFIRM before trusting any total of it")

    elif family == "text":
        threshold = max(CATEGORICAL_MAX_DISTINCT, 1)
        low_card = distinct <= threshold or (ratio is not None and ratio <= CATEGORICAL_MAX_RATIO)
        if hits("key", name) and not hits("label_name", name):
            role, additivity = "entity_key", "count_only"
            evidence.append("key-named text column; an identifier to join or count on")
        elif hits("text_blob", name):
            role = "free_text"
            evidence.append("name denotes prose; not a category and not an identifier")
        elif hits("label_name", name) and not in_pk:
            role, additivity = "entity_label", "count_only"
            evidence.append("name denotes a label for a row rather than a grouping of rows")
        elif dimension_table and not in_pk and distinct <= CATEGORICAL_MAX_DISTINCT:
            role, additivity = "categorical_dim", "count_only"
            evidence.append(f"{distinct} distinct values on a descriptive table; slices the "
                            f"fact even though it repeats only once per row here")
            if table_rows and distinct >= table_rows:
                confidence = "low"
                evidence.append("one value per row of its own table, so it may be a label "
                                "rather than a grouping -- confirm it is worth slicing by")
        elif column.get("unique") and not in_pk and dimension_table:
            role, additivity = "entity_label", "count_only"
            evidence.append("high-cardinality unique text on a descriptive table; "
                            "a display label, not a slice")
        elif column.get("unique"):
            role, additivity = "entity_key", "count_only"
            evidence.append("unique text value; an identifier")
        elif hits("status", name) and distinct <= STATE_FLAG_MAX_DISTINCT:
            role, additivity = "state_flag", "count_only"
            evidence.append(f"status-like name with only {distinct} distinct values")
        elif low_card:
            role, additivity = "categorical_dim", "count_only"
            evidence.append(f"{distinct} distinct values; usable as a slice")
        elif distinct <= HIGH_CARDINALITY_DIM_MAX and float(column.get("avg_length") or 0) <= 40:
            role, additivity = "categorical_dim", "count_only"
            column["high_cardinality"] = True
            evidence.append(f"{distinct} distinct values -- a real dimension, but too many to "
                            f"list or plot; rank and truncate it (top N, rest as Other)")
        elif float(column.get("avg_length") or 0) > 40:
            role = "free_text"
            evidence.append(f"average length {float(column['avg_length']):.0f}; prose, not a category")
        else:
            role, additivity = "identifier_opaque", "count_only"
            evidence.append("high-cardinality short text; an identifier or label")

    column["semantic_role"] = role
    column["additivity"] = additivity
    column["confidence"] = confidence
    column["evidence"] = evidence
    column["measure_candidate"] = additivity in ("additive", "semi_additive")


def pre_mark_keys(table: dict) -> None:
    for column in table["columns"].values():
        column["role_hint_key"] = (
            column["name"] in table.get("primary_key", [])
            or (hits("key", column["name"]) and column["type_family"] in ("numeric", "text"))
        )
        column["measure_candidate"] = (
            column["type_family"] == "numeric" and not column["role_hint_key"]
        )


# --------------------------------------------------------------------------
# join inference
# --------------------------------------------------------------------------
def key_aliases(name: str) -> set[str]:
    """Forms a key column might be written in, without assuming a convention.

    Some schemas prefix columns with a table abbreviation (L_ORDERKEY, O_ORDERKEY);
    most do not. Rather than asserting either, both the raw and the de-prefixed
    form are offered and a join is only kept if the data confirms it.
    """
    upper = normalise_name(name).upper()
    forms = {upper}
    stripped = re.sub(r"^[A-Z]{1,3}_", "", upper)
    if stripped and stripped != upper:
        forms.add(stripped)
    return forms


def infer_joins(schema: str, tables: dict, verify: bool) -> list[dict]:
    parents = defaultdict(list)
    for table in tables.values():
        primary_key = table.get("primary_key", [])
        # Single-column primary key: the whole identity of a row.
        if len(primary_key) == 1:
            for alias in key_aliases(primary_key[0]):
                parents[alias].append((table["name"], primary_key[0]))
        for column in table["columns"].values():
            if column.get("unique") and column["semantic_role"] == "entity_key":
                pair = (table["name"], column["name"])
                for alias in key_aliases(column["name"]):
                    if pair not in parents[alias]:
                        parents[alias].append(pair)

    edges = []
    # Composite keys: a table whose whole primary key is present on another table
    # is joinable on the full set, even though no single column identifies it.
    for parent in tables.values():
        primary_key = parent.get("primary_key", [])
        if len(primary_key) < 2:
            continue
        # Compare alias sets on both sides: PS_PARTKEY and L_PARTKEY only meet
        # once each is reduced to PARTKEY.
        wanted = [(pk_column, key_aliases(pk_column)) for pk_column in primary_key]
        for child in tables.values():
            if child["name"] == parent["name"]:
                continue
            matched, claimed = {}, set()
            for column in child["columns"].values():
                aliases = key_aliases(column["name"])
                for pk_column, pk_aliases in wanted:
                    if pk_column in claimed or not (aliases & pk_aliases):
                        continue
                    matched[column["name"]] = pk_column
                    claimed.add(pk_column)
                    break
            if len(matched) == len(primary_key):
                edges.append({
                    "from_table": child["name"],
                    "from_column": list(matched)[0], "to_table": parent["name"],
                    "to_column": matched[list(matched)[0]],
                    "composite_on": [{"from": k, "to": v} for k, v in matched.items()],
                    "basis": "composite_name_match", "verified": None, "orphan_rows": None,
                })

    for table in tables.values():
        for column in table["columns"].values():
            if column["semantic_role"] != "entity_key":
                continue
            candidates = []
            for alias in key_aliases(column["name"]):
                candidates.extend(parents.get(alias, []))
            for parent_table, parent_column in dict.fromkeys(candidates):
                if parent_table == table["name"]:
                    continue
                edges.append({
                    "from_table": table["name"], "from_column": column["name"],
                    "to_table": parent_table, "to_column": parent_column,
                    "basis": "declared" if column.get("declared") else "name_match",
                    "verified": None, "orphan_rows": None,
                })

    if verify:
        for edge in edges:
            child = q(schema, edge["from_table"])
            parent = q(schema, edge["to_table"])
            if edge.get("composite_on"):
                pairs = edge["composite_on"]
                on = " AND ".join(f'p.{q(pair["to"])} = c.{q(pair["from"])}' for pair in pairs)
                cols = ", ".join(q(pair["from"]) for pair in pairs)
                try:
                    rows = run_sql(
                        f"SELECT COUNT(*) AS ORPHANS FROM (SELECT DISTINCT {cols} FROM {child} "
                        f"LIMIT 50000) c LEFT JOIN {parent} p ON {on} "
                        f"WHERE p.{q(pairs[0]['to'])} IS NULL")
                    orphans = int(rows[0]["ORPHANS"]) if rows else 0
                    edge["orphan_rows"] = orphans
                    edge["verified"] = orphans == 0
                except RuntimeError as exc:
                    edge["verified"] = False
                    edge["error"] = str(exc)[:160]
                continue
            try:
                rows = run_sql(
                    f"SELECT COUNT(*) AS ORPHANS FROM (SELECT DISTINCT {q(edge['from_column'])} AS V "
                    f"FROM {child} WHERE {q(edge['from_column'])} IS NOT NULL LIMIT 50000) c "
                    f"LEFT JOIN {parent} p ON p.{q(edge['to_column'])} = c.V "
                    f"WHERE p.{q(edge['to_column'])} IS NULL"
                )
                orphans = int(rows[0]["ORPHANS"]) if rows else 0
                edge["orphan_rows"] = orphans
                edge["verified"] = orphans == 0
            except RuntimeError as exc:
                edge["verified"] = False
                edge["error"] = str(exc)[:160]
    return edges


# --------------------------------------------------------------------------
# tier + capabilities
# --------------------------------------------------------------------------
def assess(tables: dict, edges: list[dict]) -> dict:
    columns = [c for t in tables.values() for c in t["columns"].values()]
    roles = defaultdict(list)
    for table in tables.values():
        for column in table["columns"].values():
            roles[column["semantic_role"]].append(f"{table['name']}.{column['name']}")

    has_measure = any(c["additivity"] in ("additive", "semi_additive") for c in columns)
    has_time = bool(roles["temporal_event"] or roles["temporal_scd"])
    has_category = bool(roles["categorical_dim"] or roles["state_flag"])
    verified_edges = [e for e in edges if e["verified"]]
    has_entities = bool(roles["entity_key"]) and bool(verified_edges or len(tables) == 1)
    facts = [t for t in tables.values() if t["role"] == "fact_like"]
    has_scd = bool(roles["temporal_scd"])
    # A hierarchy needs a chain: a non-fact table that itself joins onward to a
    # further table (customer -> nation -> region). Two joins off one fact is a
    # star, not a hierarchy, and gives no drill path.
    has_hierarchy = any(
        tables[edge["from_table"]]["role"] != "fact_like"
        and tables[edge["to_table"]]["role"] != "fact_like"
        for edge in verified_edges
    )

    present = []
    if has_time:
        present.append("time")
    if has_category:
        present.append("dimensions")
    if has_entities:
        present.append("joinable entities")
    if len(facts) > 1 or has_scd or has_hierarchy:
        present.append("multiple facts, hierarchy or SCD windows")
    # Independent capabilities, not a ladder: a dataset with dimensions and
    # entities but no dates can still do composition and per-entity work, and
    # must not be pinned at the bottom for lacking one axis.
    tier = len(present)
    reason = ("countable rows only" if not present
              else "carries " + ", ".join(present))

    gaps = []
    if not has_measure:
        gaps.append("No additive measure found: only counts and distributions are derivable.")
    if not has_time:
        gaps.append("No temporal column found: no trend, run rate or period comparison "
                    "is derivable.")
    if not has_category:
        gaps.append("No categorical dimension found: no composition, mix-shift or slicing "
                    "is derivable.")
    if not verified_edges and len(tables) > 1:
        gaps.append("No join could be verified between tables: per-entity metrics that span "
                    "tables are not derivable.")
    return {
        "tier": tier,
        "tier_reason": reason,
        "capabilities": {
            "has_measure": has_measure, "has_time": has_time,
            "has_categoricals": has_category, "has_joinable_entities": has_entities,
            "multiple_facts": len(facts) > 1, "has_scd_windows": has_scd,
            "hierarchy_candidates": has_hierarchy,
        },
        "roles_present": {role: sorted(cols) for role, cols in sorted(roles.items())},
        "gaps": gaps,
    }


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
VALUE_INDEX_MAX = 200


def index_dimension_values(schema: str, table: dict) -> None:
    """Record the actual values of every listable dimension.

    A question names values ("APAC sales"), not just column names. Without this
    a text-to-SQL fallback can only group by a dimension it recognised and will
    silently drop the value the question was actually about -- answering a
    question nobody asked, with no sign that it did so.
    """
    for column in table["columns"].values():
        if column.get("semantic_role") not in ("categorical_dim", "state_flag"):
            continue
        if column.get("high_cardinality"):
            continue
        if (column.get("distinct") or 0) > VALUE_INDEX_MAX:
            continue
        expression = q(column["name"])
        try:
            rows = run_sql(f'SELECT {expression} AS V FROM {q(schema, table["name"])} '
                           f'WHERE {expression} IS NOT NULL GROUP BY {expression} '
                           f'ORDER BY COUNT(*) DESC LIMIT {VALUE_INDEX_MAX}')
        except RuntimeError:
            continue  # a value index is a convenience; never fail the profile for it
        values = [str(r["V"]).strip() for r in rows if r.get("V") not in (None, "")]
        if values:
            column["values"] = values


def build_card(schema: str, sample_rows: int, verify: bool) -> dict:
    tables = load_catalog(schema)
    if not tables:
        raise SystemExit(f"schema {schema!r} has no tables visible to this connection")
    for table in tables.values():
        pre_mark_keys(table)
        profile_table(schema, table, sample_rows)
        infer_text_types(schema, table, sample_rows)
    for table in tables.values():
        classify_table_role(table, tables)
    for table in tables.values():
        for column in table["columns"].values():
            classify_column(column, table)
    for table in tables.values():
        classify_table_role(table, tables)
    for table in tables.values():
        index_dimension_values(schema, table)
    edges = infer_joins(schema, tables, verify)
    assessment = assess(tables, edges)
    return {
        "schema": schema,
        "table_count": len(tables),
        "total_rows": sum(t["row_count"] for t in tables.values()),
        "tables": [
            {
                "name": t["name"], "role": t["role"], "role_evidence": t["role_evidence"],
                "row_count": t["row_count"], "sampled": t.get("sampled", False),
                "grain": t["grain"], "grain_evidence": t["grain_evidence"],
                "comment": t["comment"],
                "columns": [t["columns"][name] for name in sorted(
                    t["columns"], key=lambda n: t["columns"][n]["position"])],
            }
            for t in sorted(tables.values(), key=lambda t: -t["row_count"])
        ],
        "joins": edges,
        **assessment,
    }


def render(card: dict) -> str:
    out = [f"SCHEMA CARD  {card['schema']}   tier {card['tier']}  "
           f"({card['table_count']} tables, {card['total_rows']:,} rows)",
           f"  tier basis: {card['tier_reason']}", ""]
    for table in card["tables"]:
        flag = "  [sampled]" if table["sampled"] else ""
        out.append(f"  {table['name']}  <{table['role']}>  {table['row_count']:,} rows{flag}")
        out.append(f"    grain: {', '.join(table['grain']) or 'unknown'}  ({table['grain_evidence']})")
        for column in table["columns"]:
            additivity = column["additivity"]
            mark = {"additive": "+", "semi_additive": "~", "non_additive": "!",
                    "attribute": "*", "count_only": "#"}.get(additivity, " ")
            warn = "  <-- UNCONFIRMED" if column.get("confidence") == "low" else ""
            if column.get("high_cardinality"):
                warn += "  [top-N only]"
            if column.get("stored_as") == "text":
                warn += "  [text->" + column["inferred_family"]
                warn += "/" + column["date_format"] if column.get("date_format") else ""
                warn += "!AMBIGUOUS" if column.get("ambiguous_date_format") else ""
                warn += "]"
            out.append(f"      {mark} {column['name']:<22} {column['semantic_role']:<20} "
                       f"{additivity:<14} d={column.get('distinct', '?')}{warn}")
        out.append("")
    out.append("  joins")
    if not card["joins"]:
        out.append("    (none inferred)")
    for edge in card["joins"]:
        status = {True: "verified", False: "REJECTED", None: "unverified"}[edge["verified"]]
        orphans = "" if edge["orphan_rows"] in (None, 0) else f" ({edge['orphan_rows']} orphans)"
        out.append(f"    {edge['from_table']}.{edge['from_column']} -> "
                   f"{edge['to_table']}.{edge['to_column']}  [{status}{orphans}]")
    out.append("")
    out.append("  capabilities: " + ", ".join(
        k for k, v in card["capabilities"].items() if v) or "  capabilities: none")
    if card["gaps"]:
        out.append("  gaps")
        for gap in card["gaps"]:
            out.append(f"    - {gap}")
    out.append("")
    out.append("  legend  + additive   ~ semi-additive (never across time)   ! non-additive")
    out.append("          * attribute (fans out if summed across a join)     # count only")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schemas", nargs="+")
    parser.add_argument("--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS)
    parser.add_argument("--no-verify-joins", action="store_true")
    parser.add_argument("--json", metavar="PATH")
    args = parser.parse_args()

    cards = []
    for schema in args.schemas:
        card = build_card(schema, args.sample_rows, not args.no_verify_joins)
        cards.append(card)
        print(render(card))
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(cards if len(cards) > 1 else cards[0], handle, indent=2, default=str)
        print(f"written: {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
