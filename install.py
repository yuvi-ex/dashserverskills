#!/usr/bin/env python3
"""Clone-to-ready in one step: skill, model key, verification.

Prints two lines. Pass --verbose for every step, --quiet for none.

The key prompt reads the terminal directly, so it works even when this script
arrives through a pipe. Where there is no controlling terminal -- an agent or
editor console -- pass the key by a route that keeps it out of the transcript;
a key pasted into one has to be rotated:

    <paste> | python install.py           copy the key first, then run this
    python install.py --clipboard         read the clipboard directly
    python install.py --key-file PATH     read it from a file

Those flags are forwarded to setup_llm_key.py untouched.

This replaces install.sh so that macOS, Linux, WSL and PowerShell all run the
same implementation rather than two that drift apart.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY = ["SKILL.md", "DEPLOY.md", "README.md", "references", "assets"]
# Shipped alongside the skill so the dashboard's "add a key" hint resolves.
COPY_FILES = ["setup_llm_key.py"]


def skill_name() -> str:
    """The `name:` field from SKILL.md's frontmatter."""
    for line in (HERE / "SKILL.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return "persona-metrics"


def skills_dir() -> Path:
    override = os.environ.get("CLAUDE_SKILLS_DIR")
    return Path(override) if override else Path.home() / ".claude" / "skills"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--clipboard", action="store_true")
    parser.add_argument("--key-file", metavar="PATH")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    say = (lambda *a: None) if args.quiet else print
    step = (lambda m: print(f"==> {m}")) if args.verbose else (lambda m: None)

    # ---- 1. the skill itself ----------------------------------------------
    name = skill_name()
    dest = skills_dir() / name
    step(f"Installing skill {name!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for item in COPY:
        source = HERE / item
        if not source.exists():
            continue
        if source.is_dir():
            # __pycache__ would otherwise ship a previous platform's bytecode.
            shutil.copytree(source, dest / item,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, dest / item)
    for item in COPY_FILES:
        if (HERE / item).exists():
            shutil.copy2(HERE / item, dest / item)
    if args.verbose:
        print(f"    -> {dest}")

    # ---- 2. the model key --------------------------------------------------
    step("Model key for the Ask-the-data panel")
    home = os.environ.get("EXAKIT_HOME") or str(Path.home() / ".exasol-starter-kit")
    key_file = Path(home) / "credentials" / "anthropic_api_key"
    key_state = "already set"
    if not key_file.exists():
        forwarded = []
        if args.clipboard:
            forwarded.append("--clipboard")
        if args.key_file:
            forwarded += ["--key-file", args.key_file]
        if args.force:
            forwarded.append("--force")
        # setup_llm_key.py picks its own route -- an explicit flag, piped stdin,
        # the terminal -- and draws the hidden prompt itself, so its output is
        # deliberately not captured.
        status = subprocess.run(
            [sys.executable, str(HERE / "setup_llm_key.py"), "--quiet"] + forwarded
        ).returncode
        if key_file.exists():
            key_state = "stored"
        elif status == 2:
            key_state = "skipped (no terminal; use --clipboard)"
        elif status == 3:
            key_state = "not stored (that value is not an sk-ant- key)"
        else:
            key_state = "skipped"

    # ---- 3. verification ---------------------------------------------------
    step("Preflight")
    if args.verbose:
        subprocess.run([sys.executable, str(HERE / "preflight.py")])
        checks = "see above"
    else:
        # preflight exits 0 on a warning, so the exit status alone would report
        # a missing key as "all checks passed". Count the lines instead.
        proc = subprocess.run([sys.executable, str(HERE / "preflight.py")],
                              capture_output=True, text=True)
        n = sum(1 for line in (proc.stdout or "").splitlines()
                if line.startswith("  FAIL") or line.startswith("  WARN"))
        checks = "all checks passed" if n == 0 else f"{n} to fix -- run preflight.py"

    say(f"Installed {name} - key {key_state} - {checks}")
    if key_state in ("stored", "already set"):
        say("Ready -- ask a question in the dashboard chat panel.")
    else:
        say("Ready -- chat uses keyword matching until a key is added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
