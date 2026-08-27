#!/bin/sh
# get.sh -- one line from nothing to ready.
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/yuvi-ex/dashserverskills/main/get.sh)"
#
# Clones the repo, asks for the model key with the input hidden, installs the
# skill, verifies, and prints four lines. Everything else is on --verbose.
#
# Why this file exists at all: `git clone` cannot run anything. Git has no
# post-clone hook, by design -- it would make every clone remote code
# execution. So the key cannot be collected "during" a plain clone; the clone
# has to happen inside something that can also ask. That is this script.
#
# The prompt reads /dev/tty, not stdin, so it still works when this script is
# itself arriving through a pipe.

set -e
REPO="https://github.com/yuvi-ex/dashserverskills"
DEST="${DASHSERVER_DIR:-$HOME/dashserverskills}"
VERBOSE=0
for a in "$@"; do [ "$a" = "--verbose" ] && VERBOSE=1; done

quiet() { if [ "$VERBOSE" -eq 1 ]; then "$@"; else "$@" >/dev/null 2>&1; fi; }

# ---- 1. clone, with git's own progress collapsed to one updating line -------
if [ -d "$DEST/.git" ]; then
    printf 'Updating %s ... ' "$(basename "$DEST")"
    git -C "$DEST" pull --quiet --ff-only >/dev/null 2>&1 || true
    printf 'done\n'
else
    printf 'Cloning %s ' "$(basename "$DEST")"
    if [ "$VERBOSE" -eq 1 ]; then
        git clone --progress "$REPO" "$DEST"
    else
        # Keep only the receive percentage, redrawn in place, so a large clone
        # still shows movement without printing git's six-line preamble.
        git clone --progress "$REPO" "$DEST" 2>&1 \
            | tr '\r' '\n' \
            | while IFS= read -r line; do
                  case "$line" in
                      *"Receiving objects:"*)
                          pct=${line#*Receiving objects: }
                          printf '\rCloning %s %s' "$(basename "$DEST")" "${pct%%,*}" ;;
                  esac
              done
        printf '\rCloning %s ... done\033[K\n' "$(basename "$DEST")"
    fi
fi

# ---- 2. key, then install, then verify -------------------------------------
# install.sh owns all three steps so a plain `./install.sh` behaves the same as
# this bootstrap; here we just ask it to stay quiet.
if [ "$VERBOSE" -eq 1 ]; then
    "$DEST/install.sh" --verbose
else
    "$DEST/install.sh" --quiet
fi
