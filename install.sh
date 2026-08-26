#!/bin/sh
# install.sh -- one command to go from a fresh clone to a demo-ready machine.
#
# Run this in a real terminal immediately after cloning. It installs the skill
# where the agent will find it, then collects the model key. The key step must
# be interactive: a hidden prompt cannot be read from an editor or agent
# console, and a key pasted into a chat transcript has to be rotated.

set -e
HERE=$(cd "$(dirname "$0")" && pwd)
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
elif [ ! -t 0 ]; then
    echo "    SKIPPED -- not a terminal, so the hidden prompt cannot be read."
    echo "    Run this in Terminal to finish:"
    echo "        $HERE/setup-llm-key.sh"
else
    "$HERE/setup-llm-key.sh"
fi

echo
echo "==> Preflight"
"$HERE/preflight.sh" || true
