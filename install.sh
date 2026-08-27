#!/bin/sh
# install.sh -- one command to go from a fresh clone to a demo-ready machine.
#
# Run this immediately after cloning. It installs the skill where the agent will
# find it, then collects the model key.
#
# A real terminal gets a hidden prompt. Everywhere else -- editor and agent
# consoles included -- pass the key by a route that keeps it out of the chat
# transcript, since a key pasted into one has to be rotated:
#
#   pbpaste | ./install.sh            copy the key first, then run this
#   ./install.sh --clipboard          read the clipboard directly
#   ./install.sh --key-file PATH      read it from a file
#
# Any of those flags are handed straight to setup-llm-key.sh.

set -e
HERE=$(cd "$(dirname "$0")" && pwd)

# Key-intake flags are not interpreted here, only forwarded, so the two scripts
# never drift on what they accept.
KEY_ARGS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --clipboard|--force) KEY_ARGS="$KEY_ARGS $1" ;;
        --key-file)
            shift
            [ -n "$1" ] || { echo "--key-file needs a path." >&2; exit 1; }
            KEY_ARGS="$KEY_ARGS --key-file $1" ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done
SKILL_NAME=$(sed -n 's/^name: *//p' "$HERE/SKILL.md" | head -1)
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/$SKILL_NAME"

echo "==> Installing skill '$SKILL_NAME'"
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
mkdir -p "$DEST"
for item in SKILL.md DEPLOY.md README.md references assets; do
    [ -e "$HERE/$item" ] && cp -R "$HERE/$item" "$DEST/"
done
cp "$HERE/setup-llm-key.sh" "$DEST/" 2>/dev/null || true
echo "    -> $DEST"

echo
echo "==> Model key for the Ask-the-data panel"
KEYFILE="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}/credentials/anthropic_api_key"
if [ -f "$KEYFILE" ]; then
    echo "    Already configured. Replace it by running:"
    echo "        $HERE/setup-llm-key.sh"
elif [ -n "$KEY_ARGS" ] || [ ! -t 0 ]; then
    # Non-interactive: hand the chosen route (or piped stdin) to the key script
    # rather than skipping, which used to leave text-to-SQL on keyword matching
    # with no way forward from an agent console.
    # shellcheck disable=SC2086
    "$HERE/setup-llm-key.sh" $KEY_ARGS || KEY_STATUS=$?
    if [ "${KEY_STATUS:-0}" != "0" ]; then
        echo "    Key not stored. The dashboards still work; the Ask-the-data"
        echo "    panel stays on keyword matching until a key is present."
    fi
else
    "$HERE/setup-llm-key.sh"
fi

echo
echo "==> Preflight"
"$HERE/preflight.sh" || true
