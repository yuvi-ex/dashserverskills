#!/usr/bin/env python3
"""One place where SQL leaves this skill, and it leaves in batches.

Every query in the pipeline used to be its own `exapump` process. Measured on
TPCH: 63 processes, 8.5s of wall clock, of which 8.0s -- 91% -- was process
startup. The median query took 0.12s against a bare `SELECT 1` baseline of
0.13s, so the queries themselves were free and the spawning was the entire
cost. Batched, 200 statements run in 1.1s.

The awkward part is failure. `exapump` stops at the first failing statement:
a batch of three whose second statement is bad reports "2 statements executed,
1 failed", exits non-zero, and never runs the third. Callers rely on per-query
failure being survivable -- signal_check.py probes dimensions that may not be
comparable and expects a single failure, not a dead run. So `run_many` resumes:
it records the failed index, re-invokes with the remainder, and repeats. A
batch where everything fails costs exactly what the old one-process-per-query
code cost; a batch where nothing fails costs one process.

Portable by construction: no shell, no here-doc quoting, no platform-specific
paths. `shutil.which` finds `exapump.exe` on Windows and `exapump` elsewhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# Resolved once. `shutil.which` is the portable form: on Windows it applies
# PATHEXT and finds exapump.exe, which a bare "exapump" string would not.
EXAPUMP = shutil.which("exapump") or "exapump"
TIMEOUT = 900

# No profile is passed by default, which is what the pipeline has always done:
# exapump resolves its own default from ~/.exapump/config.toml. Naming a profile
# here would break anyone whose profile is not called "starter-kit" -- likely on
# a machine that carries more than one. Set this to opt into a specific one.
PROFILE = os.environ.get("PERSONA_METRICS_EXAPUMP_PROFILE") or None

# exapump announces a failure as "Error in statement N:" (1-based).
_ERROR_MARKER = "Error in statement "


@dataclass
class Result:
    """One statement's outcome. Exactly one of `rows` / `error` is meaningful."""

    rows: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _invoke(sqls: list[str]) -> tuple[str, str]:
    """Run one exapump process over `sqls`, returning (stdout, stderr)."""
    # Statements go in on stdin rather than argv: argv has length limits (worst
    # on Windows) and a 200-statement batch would blow past them.
    script = "".join(s.rstrip().rstrip(";") + ";\n" for s in sqls)
    command = [EXAPUMP, "sql", "-f", "json"]
    if PROFILE:
        command[2:2] = ["-p", PROFILE]
    proc = subprocess.run(
        command,
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
    )
    return proc.stdout or "", proc.stderr or ""


def _parse(stdout: str, stderr: str) -> tuple[list[list[dict]], int | None, str]:
    """Split one batch's output into result sets plus any failure.

    Returns (result_sets, failed_index, error_text). `failed_index` is 0-based
    and None when the whole batch ran.

    exapump keeps the two streams cleanly apart, which makes this far less
    fragile than it could be: stdout carries nothing but one JSON array per
    statement, in order, while every progress line ("[1/3] SELECT ...") and the
    whole error report go to stderr. So results are parsed positionally from
    stdout and never have to be told apart from chatter.
    """
    results: list[list[dict]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(parsed, list):
            results.append(parsed)

    failed_index: int | None = None
    error_lines: list[str] = []
    collecting = False
    for line in stderr.splitlines():
        stripped = line.strip()
        if _ERROR_MARKER in stripped:
            # "Error in statement 2:" -> 0-based index 1.
            tail = stripped.split(_ERROR_MARKER, 1)[1]
            digits = ""
            for ch in tail:
                if not ch.isdigit():
                    break
                digits += ch
            if digits:
                failed_index = int(digits) - 1
            collecting = True
            continue
        if collecting and stripped:
            # The report repeats the statement, then explains. Keep the
            # explanation, drop the echoed SQL and the trailing tally.
            if stripped.startswith("Query execution failed") or stripped.startswith("Hint:"):
                error_lines.append(stripped)
            elif "statements executed" in stripped:
                collecting = False

    return results, failed_index, " ".join(error_lines).strip()


def run_many(sqls: list[str]) -> list[Result]:
    """Run every statement, batching as far as each failure allows.

    One process when nothing fails; one extra process per failure. Results come
    back positionally aligned with `sqls`, so a caller can zip them against
    whatever it was collecting SQL for.
    """
    out: list[Result] = [Result(error="not executed") for _ in sqls]
    pending = list(range(len(sqls)))

    while pending:
        stdout, stderr = _invoke([sqls[i] for i in pending])
        results, failed, error_text = _parse(stdout, stderr)

        # Statements before the failure ran and returned in order.
        for offset, rows in enumerate(results):
            if offset < len(pending):
                out[pending[offset]] = Result(rows=rows)

        if failed is None:
            # Whole batch ran. Anything exapump returned no result set for --
            # it should not happen for SELECTs -- stays as its default error.
            for offset in range(len(results), len(pending)):
                out[pending[offset]] = Result(rows=[])
            return out

        if failed >= len(pending):
            # Defensive: an index we cannot map back. Fail the remainder rather
            # than loop forever.
            for index in pending[len(results):]:
                out[index] = Result(error=error_text or stderr.strip()[:300]
                                    or "unknown batch failure")
            return out

        out[pending[failed]] = Result(
            error=error_text or stderr.strip()[:300] or "query failed")
        # Everything after the failure never ran: retry it as a fresh batch.
        pending = pending[failed + 1:]

    return out


def run_sql(sql: str) -> list[dict]:
    """Single-statement convenience, raising on failure.

    Kept so call sites that have not been converted to `run_many` behave
    exactly as they did when each one owned a process.
    """
    result = run_many([sql])[0]
    if not result.ok:
        raise RuntimeError(result.error)
    return result.rows


def rows_or_raise(result: Result) -> list[dict]:
    if not result.ok:
        raise RuntimeError(result.error)
    return result.rows


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    for r in run_many(sys.argv[1:] or ["SELECT 1 AS A"]):
        print(("ok   " + json.dumps(r.rows)) if r.ok else ("FAIL " + str(r.error)))
