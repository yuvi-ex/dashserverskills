#!/usr/bin/env python3
"""Verify every prerequisite this skill depends on, before a demo.

Each check prints PASS, WARN or FAIL with the exact command that fixes it.
Exit 0 = safe to demo. Exit 1 = something will break.

Ported from preflight.sh so it runs the same under bash, zsh, WSL and
PowerShell. Two checks were not merely unportable but actively wrong on
Windows and are fixed here:

  * `command -v exakit` fails in Git Bash because the launcher is `exakit.cmd`;
    `shutil.which` applies PATHEXT and finds it.
  * the key's permissions were read with `ls -l` and compared to `-rw-------`,
    which no Windows file ever reports. Mode bits are not how NTFS protects a
    file, so that check is skipped there rather than warning forever.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PORT = 5100

fails: list[str] = []
warns: list[str] = []


def pass_(message: str) -> None:
    print(f"  PASS  {message}")


def warn(message: str, fix: str) -> None:
    print(f"  WARN  {message}\n        fix: {fix}")
    warns.append(message)


def fail(message: str, fix: str) -> None:
    print(f"  FAIL  {message}\n        fix: {fix}")
    fails.append(message)


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def http_ok(url: str, data: bytes | None = None,
            headers: dict | None = None, timeout: int = 8) -> bool:
    request = urllib.request.Request(url, data=data, headers=headers or {},
                                     method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def dash_server_port() -> int:
    """Ask exakit which port dash-server was recorded on; 5100 is only default.

    Only lines that name dash-server are searched. Scanning the whole output for
    "a port-shaped number" finds the database's 8563 first and then reports
    dash-server as down on a machine where it is running perfectly.

    `exakit status` is tried before `exakit info` because on current versions
    only status prints the dash-server row at all.
    """
    exakit = shutil.which("exakit")
    if not exakit:
        return DEFAULT_PORT
    for subcommand in ("status", "info"):
        proc = run([exakit, subcommand], timeout=90)
        if not proc or not proc.stdout:
            continue
        for line in proc.stdout.splitlines():
            if "dash" not in line.lower():
                continue
            for token in re.findall(r"\d{4,5}", line):
                if 1024 <= int(token) <= 65535:
                    return int(token)
    return DEFAULT_PORT


def main() -> int:
    print("Preflight: persona-metrics dashboards")
    print(f"  platform: {platform.system()} {platform.release()}"
          f"  python {platform.python_version()}")
    if os.name == "nt":
        print("  NOTE: at deploy time, skip app_deploy_draft (its sql_smoke")
        print("        check cannot pass on Windows) -- use app_build then")
        print("        app_run_healthcheck then app_promote_revision instead.")
        print("        See DEPLOY.md, 'The deploy recipe', step 3.")
    print()

    # 1. exapump -- every query in stages 3 and 5 goes through it.
    exapump = shutil.which("exapump")
    if exapump:
        pass_(f"exapump on PATH ({exapump})")
    else:
        fail("exapump not on PATH",
             "install the Exasol Personal Local Starter Kit")

    # 2. the database actually answers.
    if exapump:
        proc = run([exapump, "sql", "-f", "json", "SELECT 1"], timeout=60)
        if proc and proc.returncode == 0:
            pass_("database reachable through exapump's default profile")
        else:
            fail("exapump cannot query the database", "exakit start")

    # 3 + 4. dash-server's two halves, which fail independently: the control
    # plane can answer while the page a user opens returns 500.
    port = dash_server_port()
    if http_ok(f"http://127.0.0.1:{port}/"):
        pass_(f"dash-server answering on port {port}")
    else:
        fail(f"dash-server not answering on port {port}",
             "exakit start   (or: exakit update dash-server)")

    payload = json.dumps({
        "jsonrpc": "2.0", "id": "1", "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "preflight", "version": "1"}},
    }).encode("utf-8")
    if http_ok(f"http://127.0.0.1:{port}/mcp", data=payload,
               headers={"Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"}):
        pass_("dash-server MCP control plane responding")
    else:
        fail(f"MCP control plane not responding on port {port}",
             "exakit stop && exakit start")

    # 5. the model key -- optional, but the demo question is keyword-matched
    #    without it.
    home = os.environ.get("EXAKIT_HOME") or str(Path.home() / ".exasol-starter-kit")
    key_file = Path(home) / "credentials" / "anthropic_api_key"
    setup = f"{sys.executable} {HERE / 'setup_llm_key.py'}"
    if key_file.is_file():
        if os.name == "nt":
            # Mode bits are synthesised on Windows; NTFS uses ACLs. Checking
            # them here would warn on every machine, forever, with a fix
            # (chmod) that cannot change anything.
            pass_("model key present (Windows: protected by ACL, not mode bits)")
        else:
            mode = key_file.stat().st_mode & 0o777
            if mode == 0o600:
                pass_("model key present and owner-only")
            else:
                warn(f"model key present but mode is {mode:o}",
                     f"chmod 600 {key_file}")
    else:
        warn("no model key: Ask-the-data falls back to keyword matching",
             f"copy the key, then: {setup} --clipboard")

    # 6. Python itself. Already proven by running, so report the version that
    #    will actually run the pipeline rather than probing for "python3",
    #    which on Windows can resolve to the Microsoft Store stub.
    if sys.version_info >= (3, 9):
        pass_(f"python {platform.python_version()} ({sys.executable})")
    else:
        fail(f"python {platform.python_version()} is too old", "install Python 3.9+")

    print()
    if fails:
        print(f"NOT READY: {len(fails)} blocking, {len(warns)} warning(s).")
        return 1
    if warns:
        print(f"READY with {len(warns)} warning(s) -- the dashboards work; "
              f"see the fixes above.")
        return 0
    print("READY: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())