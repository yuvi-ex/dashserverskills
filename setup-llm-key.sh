#!/bin/sh
# setup-llm-key.sh — store an Anthropic API key where dash-server can read it.
#
# Why a file and not an environment variable: dash-server is started by a
# launchd/systemd boot entry that carries no environment, so a key exported in a
# login shell never reaches it. The starter kit resolves its database password
# the same way.
#
# The key is never echoed, never passed as an argument (arguments are visible in
# `ps` and land in shell history), never logged. It is written with umask 077 and
# verified owner-only afterwards.
#
# Four intake routes, so an agent or editor console is not a dead end:
#
#   setup-llm-key.sh                  hidden prompt        (needs a real TTY)
#   setup-llm-key.sh --clipboard      read the clipboard   (works anywhere)
#   setup-llm-key.sh --key-file PATH  read that file       (works anywhere)
#   pbpaste | setup-llm-key.sh        read piped stdin     (works anywhere)
#
# The three non-TTY routes exist because the key must not transit a chat
# transcript — a key pasted into one has to be rotated. None of them requires
# the key to be typed where it would be captured.
#
# Add --force to replace an existing key without a confirmation prompt.

set -e
DIR="${EXAKIT_HOME:-$HOME/.exasol-starter-kit}/credentials"
FILE="$DIR/anthropic_api_key"

SOURCE=""
KEY_FILE_ARG=""
FORCE=0
QUIET=0
PROMPT='Anthropic API key for text-to-SQL (hidden, Enter to skip): '

while [ $# -gt 0 ]; do
    case "$1" in
        --clipboard) SOURCE="clipboard" ;;
        --key-file)
            shift
            [ -n "$1" ] || { echo "--key-file needs a path." >&2; exit 1; }
            SOURCE="file"; KEY_FILE_ARG="$1" ;;
        --force) FORCE=1 ;;
        --quiet) QUIET=1 ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

# Piped stdin is a key source in its own right: `pbpaste | setup-llm-key.sh`.
# Require an actual pipe or regular file: "not a TTY" alone also covers a closed
# or empty descriptor, where `cat` blocks forever instead of returning.
if [ -z "$SOURCE" ] && [ ! -t 0 ] && { [ -p /dev/stdin ] || [ -f /dev/stdin ]; }; then
    SOURCE="stdin"
fi

# A controlling terminal can be opened directly even when stdin is a pipe, which
# is what lets `sh -c "$(curl ...)"` still ask for the key interactively. Where
# there is no controlling terminal -- an agent or editor console -- opening it
# fails immediately with ENXIO rather than blocking, so this is safe to attempt.
has_tty() { { : < /dev/tty; } 2>/dev/null; }

if [ -f "$FILE" ]; then
    if [ "$FORCE" -eq 1 ]; then
        :
    elif [ -t 0 ] && [ -z "$SOURCE" ]; then
        printf 'A key is already stored at %s\n' "$FILE"
        printf 'Replace it? [y/N] '
        read -r reply
        case "$reply" in [Yy]*) ;; *) echo "Left unchanged."; exit 0 ;; esac
    else
        # No terminal to confirm on, so refuse rather than silently overwrite a
        # working key.
        printf 'A key is already stored at %s\n' "$FILE"
        echo "Re-run with --force to replace it."
        exit 0
    fi
fi

mkdir -p "$DIR"

key=""
case "$SOURCE" in
    clipboard)
        command -v pbpaste >/dev/null 2>&1 || {
            echo "No pbpaste on this system; use --key-file PATH instead." >&2
            exit 1
        }
        key=$(pbpaste)
        [ -n "$key" ] || { echo "The clipboard is empty." >&2; exit 1; }
        ;;
    file)
        [ -f "$KEY_FILE_ARG" ] || { echo "No such file: $KEY_FILE_ARG" >&2; exit 1; }
        key=$(cat "$KEY_FILE_ARG")
        ;;
    stdin)
        key=$(cat)
        [ -n "$key" ] || {
            echo "Nothing arrived on standard input." >&2
            echo "Try: pbpaste | $0" >&2
            exit 1
        }
        ;;
    *)
        # Interactive. Prefer /dev/tty over stdin so the prompt survives being
        # piped; fall back to stdin when it is itself a terminal.
        if has_tty; then
            # Echo goes off before the prompt is drawn: anything already typed
            # ahead of it would otherwise be echoed in the clear.
            stty -echo < /dev/tty 2>/dev/null || true
            printf '%s' "$PROMPT" > /dev/tty
            # `read` returns non-zero at EOF (Ctrl-D). Under `set -e` that would
            # abort here with a bare exit 1 and no explanation, so treat EOF as
            # the same thing as an empty line: a skip.
            read -r key < /dev/tty || key=""
            stty echo < /dev/tty 2>/dev/null || true
            printf '\n' > /dev/tty
        elif [ -t 0 ]; then
            stty -echo 2>/dev/null || true
            printf '%s' "$PROMPT"
            read -r key || key=""
            stty echo 2>/dev/null || true
            printf '\n'
        else
            if [ "$QUIET" -eq 0 ]; then
                SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
                echo "No terminal for the hidden prompt, and nothing on stdin."
                echo "Any of these work without a terminal:"
                echo "    pbpaste | $SELF          # copy the key first"
                echo "    $SELF --clipboard"
                echo "    $SELF --key-file /path/to/key.txt"
            fi
            exit 2
        fi
        if [ -z "$key" ]; then
            [ "$QUIET" -eq 1 ] || echo "Skipped -- chat falls back to keyword matching."
            exit 0
        fi
        ;;
esac

# Trim whitespace and newlines: a clipboard or file copy usually carries a
# trailing newline, and read_key() would otherwise compare a padded string.
key=$(printf '%s' "$key" | tr -d '\r\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')

case "$key" in
    sk-ant-*) ;;
    *) if [ "$QUIET" -eq 0 ]; then
           echo "That does not look like an Anthropic key (expected sk-ant-...)." >&2
           echo "Nothing was written." >&2
       fi
       exit 3 ;;
esac

( umask 077; printf '%s' "$key" > "$FILE" )
chmod 600 "$FILE"
key=""

if [ "$QUIET" -eq 0 ]; then
    echo "Stored at $FILE (owner-only)."
    echo "No restart needed: the key is read per question."
fi
