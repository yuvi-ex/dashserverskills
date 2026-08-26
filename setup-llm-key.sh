#!/bin/sh
# setup-llm-key.sh — store an Anthropic API key where dash-server can read it.
#
# Why a file and not an environment variable: dash-server is started by a
# launchd/systemd boot entry that carries no environment, so a key exported in a
# login shell never reaches it. The starter kit resolves its database password
# the same way.
#
# The key is read with `read -s` (never echoed, never in shell history), written
# with umask 077, and verified to be owner-only afterwards. It is never printed.

set -e
DIR="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}/credentials"
FILE="$DIR/anthropic_api_key"

if [ -f "$FILE" ]; then
    printf 'A key is already stored at %s\n' "$FILE"
    printf 'Replace it? [y/N] '
    read -r reply
    case "$reply" in [Yy]*) ;; *) echo "Left unchanged."; exit 0 ;; esac
fi

mkdir -p "$DIR"

# A hidden prompt needs a real terminal. Editor and agent consoles hand this
# script a pipe, `read` returns an empty line immediately, and the run looks
# like the user chose to skip -- so say what actually happened instead.
if [ ! -t 0 ]; then
    echo "This needs a real terminal: standard input is not a TTY, so the"
    echo "hidden key prompt cannot be read here (an editor or agent console"
    echo "will do this). Nothing was written."
    echo
    SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
    echo "Open Terminal and run:"
    echo "    $SELF"
    exit 2
fi

printf 'Anthropic API key (input hidden, or press Enter to skip): '
stty -echo 2>/dev/null || true
read -r key
stty echo 2>/dev/null || true
printf '\n'

if [ -z "$key" ]; then
    echo "Skipped. The dashboards still work; the Ask-the-data panel falls back"
    echo "to template matching until a key is present."
    exit 0
fi

case "$key" in
    sk-ant-*) ;;
    *) echo "That does not look like an Anthropic key (expected sk-ant-...)."; exit 1 ;;
esac

( umask 077; printf '%s' "$key" > "$FILE" )
chmod 600 "$FILE"
key=""

echo "Stored at $FILE (owner-only)."
echo "No restart needed: the key is read per question."
