#!/bin/sh
# get.sh -- one line from nothing to ready, on macOS, Linux and WSL.
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.sh)"
#
# PowerShell users want get.ps1 instead:
#
#   irm https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.ps1 | iex
#
# Why this file exists at all: `git clone` cannot run anything. Git has no
# post-clone hook, by design -- it would make every clone remote code
# execution. So the key cannot be collected "during" a plain clone; the clone
# has to happen inside something that can also ask. That is this script.
#
# It stays deliberately thin. Everything after the clone lives in install.py,
# which runs identically on every platform, so there is one implementation to
# fix rather than one per shell.

set -e
REPO="https://github.com/yuvi-ex/dashserverskills"
DEST="${DASHSERVER_DIR:-$HOME/dashserverskills}"

# python3 on macOS/Linux/WSL; fall back to python where that is the only name.
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "Python 3 is required but was not found on PATH." >&2; exit 1; }

if [ -d "$DEST/.git" ]; then
    printf 'Updating %s ... ' "$(basename "$DEST")"
    git -C "$DEST" pull --quiet --ff-only >/dev/null 2>&1 || true
    printf 'done\n'
else
    printf 'Cloning %s ... ' "$(basename "$DEST")"
    git clone --quiet "$REPO" "$DEST"
    printf 'done\n'
fi

# The key prompt needs the terminal, so install.py is not wrapped or piped.
exec "$PY" "$DEST/install.py" "$@"
