#!/bin/sh
# get.sh -- one line from nothing to ready, anywhere there is a POSIX shell.
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.sh)"
#
# That single line covers macOS, Linux, WSL *and* Windows under Git Bash, which
# ships its own sh, git and curl. There is nothing Windows-specific to do if you
# already work in Git Bash.
#
# get.ps1 exists for people who only have PowerShell:
#
#   irm https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.ps1 | iex
#
# Do not run the curl line above *in* PowerShell: there, `curl` is an alias for
# Invoke-WebRequest, which does not understand -fsSL and fails confusingly.
# Either use get.ps1, or spell it `curl.exe` to get the real binary.
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
# DASHSERVER_REPO overrides the source, which is what lets this bootstrap
# be exercised against a branch or a local clone before it is published.
REPO="${DASHSERVER_REPO:-https://github.com/yuvi-ex/dashserverskills}"
DEST="${DASHSERVER_DIR:-$HOME/dashserverskills}"

# Each candidate is *run* rather than merely found, because a name existing on
# PATH does not mean it is an interpreter. Under Git Bash on Windows,
# ~/AppData/Local/Microsoft/WindowsApps/python3 is a Microsoft Store stub on any
# machine without Python installed: it opens the Store and exits, so `command -v`
# finds it and the install then fails with nothing useful on screen. Asking it
# for its major version tells the two apart. On Linux the same probe rejects a
# `python` that is still Python 2.
PY=""
for candidate in python3 python py; do
    path=$(command -v "$candidate" 2>/dev/null) || continue
    major=$("$path" -c 'import sys; print(sys.version_info[0])' 2>/dev/null) || continue
    if [ "$major" = "3" ]; then PY="$path"; break; fi
done
if [ -z "$PY" ]; then
    echo "Python 3 is required but no working interpreter was found on PATH." >&2
    echo "Tried: python3, python, py" >&2
    exit 1
fi

command -v git >/dev/null 2>&1 || {
    echo "git is required but was not found on PATH." >&2; exit 1
}

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
