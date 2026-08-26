#!/bin/sh
# preflight.sh -- verify every prerequisite this skill depends on, before a demo.
#
# Each check prints PASS, WARN or FAIL with the exact command that fixes it.
# Exit 0 = safe to demo. Exit 1 = something will break.

HERE=$(cd "$(dirname "$0")" && pwd)
FAIL=0
WARN=0
pass() { printf '  PASS  %s\n' "$1"; }
warn() { printf '  WARN  %s\n        fix: %s\n' "$1" "$2"; WARN=$((WARN+1)); }
fail() { printf '  FAIL  %s\n        fix: %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

echo "Preflight: persona-metrics dashboards"
echo

# 1. exapump on PATH -- stages 3 and 5 shell out to it
if command -v exapump >/dev/null 2>&1; then
    pass "exapump on PATH"
else
    fail "exapump not on PATH" "install the Exasol Personal Local Starter Kit"
fi

# 2. the starter-kit profile actually answers
if command -v exapump >/dev/null 2>&1; then
    if exapump sql -p starter-kit 'SELECT 1' >/dev/null 2>&1; then
        pass "database reachable via profile 'starter-kit'"
    else
        fail "profile 'starter-kit' cannot query the database" "exakit start"
    fi
fi

# 3. dash-server running, and on which port
PORT=$(exakit info 2>/dev/null | sed -n 's/.*dash-server.*[^0-9]\([0-9][0-9][0-9][0-9]\).*/\1/p' | head -1)
[ -z "$PORT" ] && PORT=5100
if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
    pass "dash-server answering on port $PORT"
else
    fail "dash-server not answering on port $PORT" "exakit start   (or: exakit update dash-server)"
fi

# 4. the MCP control plane -- the half the agent drives
if curl -fsS -o /dev/null -X POST "http://127.0.0.1:$PORT/mcp" \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"preflight","version":"1"}}}' 2>/dev/null; then
    pass "dash-server MCP control plane responding"
else
    fail "MCP control plane not responding on port $PORT" "exakit stop && exakit start"
fi

# 5. the model key -- optional, but the demo question fails without it
KEYFILE="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}/credentials/anthropic_api_key"
if [ -f "$KEYFILE" ]; then
    MODE=$(ls -l "$KEYFILE" | cut -c1-10)
    if [ "$MODE" = "-rw-------" ]; then
        pass "model key present and owner-only"
    else
        warn "model key present but mode is $MODE" "chmod 600 $KEYFILE"
    fi
else
    warn "no model key: Ask-the-data falls back to keyword matching" \
         "run in a terminal: $HERE/setup-llm-key.sh"
fi

# 6. python3, for the pipeline scripts
if command -v python3 >/dev/null 2>&1; then
    pass "python3 available ($(python3 -V 2>&1 | cut -d' ' -f2))"
else
    fail "python3 not found" "install Python 3"
fi

echo
if [ "$FAIL" -gt 0 ]; then
    echo "NOT READY: $FAIL blocking, $WARN warning(s)."
    exit 1
fi
if [ "$WARN" -gt 0 ]; then
    echo "READY with $WARN warning(s) -- the dashboards work; see the fixes above."
    exit 0
fi
echo "READY: all checks passed."
