"""Shared forwarding logic for the thin SessionEnd / SessionStart hook shims.

Resolves the `postcommit` CLI and pipes the hook's stdin payload to
`postcommit hook <event>`, passing the CLI's stdout straight through (that is
how the SessionStart nudge JSON reaches Claude Code). Everything is best-effort:
a missing CLI or a subprocess error is swallowed so the hook never breaks a
session.
"""

import shutil
import subprocess
import sys


def _command(event):
    """Prefer the installed console script; fall back to `python -m postcommit`."""
    exe = shutil.which("postcommit")
    if exe:
        return [exe, "hook", event]
    return [sys.executable, "-m", "postcommit", "hook", event]


def forward(event):
    payload = sys.stdin.buffer.read()
    try:
        # No capture: the child's stdout (the nudge JSON, for session-start)
        # inherits this process's stdout and reaches Claude Code directly.
        subprocess.run(_command(event), input=payload, timeout=30, check=False)
    except Exception:
        # Never let a hook failure surface to the user's session.
        pass
