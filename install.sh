#!/bin/sh
# install.sh -- clone-to-ready in one step: skill, model key, verification.
#
# Prints four lines. Pass --verbose for every step, --quiet for none.
#
# The key prompt reads /dev/tty, so it works in a terminal even when this script
# arrives through a pipe. Where there is no controlling terminal (an agent or
# editor console) pass the key by a route that keeps it out of the transcript --
# a key pasted into one has to be rotated:
#
#   pbpaste | ./install.sh            copy the key first, then run this
#   ./install.sh --clipboard          read the clipboard directly
#   ./install.sh --key-file PATH      read it from a file
#
# Those flags are forwarded to setup-llm-key.sh untouched.

set -e
HERE=$(cd "$(dirname "$0")" && pwd)

# Key-intake flags are not interpreted here, only forwarded, so the two scripts
# never drift on what they accept.
KEY_ARGS=""
VERBOSE=0
QUIET=0
while [ $# -gt 0 ]; do
    case "$1" in
        --clipboard|--force) KEY_ARGS="$KEY_ARGS $1" ;;
        --key-file)
            shift
            [ -n "$1" ] || { echo "--key-file needs a path." >&2; exit 1; }
            KEY_ARGS="$KEY_ARGS --key-file $1" ;;
        --verbose) VERBOSE=1 ;;
        --quiet) QUIET=1 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
step() { [ "$VERBOSE" -eq 1 ] && printf '==> %s\n' "$*"; return 0; }
run()  { if [ "$VERBOSE" -eq 1 ]; then "$@"; else "$@" >/dev/null 2>&1; fi; }
SKILL_NAME=$(sed -n 's/^name: *//p' "$HERE/SKILL.md" | head -1)
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/$SKILL_NAME"

step "Installing skill '$SKILL_NAME'"
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
mkdir -p "$DEST"
for item in SKILL.md DEPLOY.md README.md references assets; do
    [ -e "$HERE/$item" ] && cp -R "$HERE/$item" "$DEST/"
done
cp "$HERE/setup-llm-key.sh" "$DEST/" 2>/dev/null || true
[ "$VERBOSE" -eq 1 ] && echo "    -> $DEST"

step "Model key for the Ask-the-data panel"
KEYFILE="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}/credentials/anthropic_api_key"
KEY_STATE="already set"
if [ ! -f "$KEYFILE" ]; then
    # One call for every case. setup-llm-key.sh picks its own route: an explicit
    # flag, piped stdin, /dev/tty, or plain stdin -- and prints the hidden prompt
    # itself, which is why this is not wrapped in run().
    KEY_STATUS=0
    # shellcheck disable=SC2086
    "$HERE/setup-llm-key.sh" --quiet $KEY_ARGS || KEY_STATUS=$?
    if [ -f "$KEYFILE" ]; then
        KEY_STATE="stored"
    elif [ "$KEY_STATUS" -eq 2 ]; then
        KEY_STATE="skipped (no terminal; use --clipboard)"
    elif [ "$KEY_STATUS" -eq 3 ]; then
        KEY_STATE="not stored (that value is not an sk-ant- key)"
    else
        KEY_STATE="skipped"
    fi
fi

step "Preflight"
if [ "$VERBOSE" -eq 1 ]; then
    "$HERE/preflight.sh" || true
    CHECKS="see above"
else
    # preflight exits 0 on a warning, so the exit status alone would report a
    # missing key as "all checks passed". Count the lines instead, one run.
    PF=$("$HERE/preflight.sh" 2>&1) || true
    N=$(printf '%s\n' "$PF" | grep -Ec '^  (FAIL|WARN)' || true)
    if [ "${N:-0}" -eq 0 ]; then
        CHECKS="all checks passed"
    else
        CHECKS="$N to fix -- run ./preflight.sh"
    fi
fi

say "Installed $SKILL_NAME · key $KEY_STATE · $CHECKS"
if [ "$KEY_STATE" = "stored" ] || [ "$KEY_STATE" = "already set" ]; then
    say "Ready -- ask a question in the dashboard chat panel."
else
    say "Ready -- chat uses keyword matching until a key is added."
fi
