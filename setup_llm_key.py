#!/usr/bin/env python3
"""Store an Anthropic API key where dash-server can read it.

Why a file and not an environment variable: dash-server is started by a
launchd/systemd/Windows boot entry that carries no environment, so a key
exported in a login shell never reaches it. The starter kit resolves its
database password the same way.

The key is never echoed, never passed as an argument (arguments are visible in
`ps` and land in shell history), never logged. It is written with the tightest
permissions the platform offers.

Four intake routes, so an agent or editor console is not a dead end:

    setup_llm_key.py                  hidden prompt        (needs a real TTY)
    setup_llm_key.py --clipboard      read the clipboard   (works anywhere)
    setup_llm_key.py --key-file PATH  read that file       (works anywhere)
    <paste> | setup_llm_key.py        read piped stdin     (works anywhere)

The three non-TTY routes exist because the key must not transit a chat
transcript -- a key pasted into one has to be rotated. None of them requires the
key to be typed where it would be captured.

Add --force to replace an existing key without a confirmation prompt.

Exit codes, which install.py reads: 0 stored or skipped, 1 usage error,
2 no terminal for the prompt, 3 the value was not an sk-ant- key.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

PROMPT = "Anthropic API key for text-to-SQL (hidden, Enter to skip): "


def key_path() -> Path:
    home = os.environ.get("EXAKIT_HOME") or str(Path.home() / ".exasol-starter-kit")
    return Path(home) / "credentials" / "anthropic_api_key"


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def clipboard_readers() -> list[list[str]]:
    """Every way this platform might hand over the clipboard, best first.

    The shell version knew only pbpaste, so --clipboard was macOS-only and the
    documented escape hatch for agent consoles did not exist anywhere else.
    """
    if os.name == "nt":
        return [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]
    if is_wsl():
        # The clipboard belongs to Windows, reachable through the interop shim.
        return [["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
                ["xclip", "-selection", "clipboard", "-o"]]
    if platform.system() == "Darwin":
        return [["pbpaste"]]
    return [["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"]]


def read_clipboard() -> tuple[str | None, str | None]:
    tried = []
    for command in clipboard_readers():
        tried.append(command[0])
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout, None
    return None, ("Could not read the clipboard (tried: " + ", ".join(tried) +
                  "). Use --key-file PATH instead.")


def has_tty() -> bool:
    """Is there a terminal we could draw a hidden prompt on?

    On POSIX a controlling terminal can be opened even when stdin is a pipe,
    which is what lets `sh -c "$(curl ...)"` still ask. Where there is none --
    an agent or editor console -- the open fails at once rather than blocking.
    """
    if os.name == "nt":
        return sys.stdin.isatty()
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        return sys.stdin.isatty()
    os.close(fd)
    return True


def stdin_is_piped() -> bool:
    """A real pipe or file on stdin, not just "stdin is not a TTY".

    A closed or empty descriptor is also "not a TTY", and reading it blocks
    forever instead of returning.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return False
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)


def write_key(path: Path, key: str) -> str:
    """Write the key as close to owner-only as the platform allows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path.write_text(key, encoding="utf-8")
        # NTFS uses ACLs, not mode bits: drop inheritance and grant only this
        # user. Best effort -- a failure here is not a reason to lose the key.
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", f"{os.environ.get('USERNAME', '')}:F"],
                capture_output=True, text=True, timeout=20, check=False)
            return "current user only"
        except (OSError, subprocess.SubprocessError):
            return "default file permissions"
    # POSIX: create at 0600 so the key is never briefly world-readable.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(str(path), 0o600)
    return "owner-only"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store an Anthropic API key for the Ask-the-data panel.",
        epilog="The key is never echoed, logged, or passed as an argument.")
    parser.add_argument("--clipboard", action="store_true",
                        help="read the key from the system clipboard")
    parser.add_argument("--key-file", metavar="PATH",
                        help="read the key from this file")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing key without confirming")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    path = key_path()
    say = (lambda *a: None) if args.quiet else print

    source = "clipboard" if args.clipboard else "file" if args.key_file else ""
    if not source and stdin_is_piped():
        source = "stdin"

    if path.exists():
        if args.force:
            pass
        elif not source and sys.stdin.isatty():
            print(f"A key is already stored at {path}")
            if input("Replace it? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Left unchanged.")
                return 0
        else:
            # Nothing to confirm on: refuse rather than silently replace a
            # working key.
            print(f"A key is already stored at {path}")
            print("Re-run with --force to replace it.")
            return 0

    if source == "clipboard":
        key, error = read_clipboard()
        if error:
            print(error, file=sys.stderr)
            return 1
    elif source == "file":
        source_path = Path(args.key_file)
        if not source_path.is_file():
            print(f"No such file: {source_path}", file=sys.stderr)
            return 1
        key = source_path.read_text(encoding="utf-8")
    elif source == "stdin":
        key = sys.stdin.read()
        if not key.strip():
            print("Nothing arrived on standard input.", file=sys.stderr)
            return 1
    else:
        if not has_tty():
            if not args.quiet:
                self = f"{sys.executable} {Path(__file__).resolve()}"
                print("No terminal for the hidden prompt, and nothing on stdin.")
                print("Any of these work without a terminal:")
                print(f"    {self} --clipboard")
                print(f"    {self} --key-file /path/to/key.txt")
                print(f"    <paste> | {self}")
            return 2
        try:
            # getpass opens /dev/tty on POSIX and uses the console API on
            # Windows, so one call covers every platform's hidden prompt.
            key = getpass.getpass(PROMPT)
        except (EOFError, KeyboardInterrupt):
            key = ""
        except getpass.GetPassWarning:
            print("Refusing to prompt: the input would be echoed.", file=sys.stderr)
            return 2
        if not key.strip():
            say("Skipped -- chat falls back to keyword matching.")
            return 0

    # A clipboard or file copy usually carries a trailing newline, and the
    # reader would otherwise compare a padded string.
    key = key.replace("\r", "").replace("\n", "").strip()

    if not key.startswith("sk-ant-"):
        if not args.quiet:
            print("That does not look like an Anthropic key (expected sk-ant-...).",
                  file=sys.stderr)
            print("Nothing was written.", file=sys.stderr)
        return 3

    how = write_key(path, key)
    key = ""
    say(f"Stored at {path} ({how}).")
    say("No restart needed: the key is read per question.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
