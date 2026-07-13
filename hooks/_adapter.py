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

# Per-event subprocess timeout. session-start is a file-read-only path that must
# feel instant, so it is bounded tightly — a pathological hang can't stall
# session startup for long. session-end does git work and may legitimately take
# longer. The default covers any future event.
_TIMEOUTS = {"session-start": 8, "session-end": 30}
_DEFAULT_TIMEOUT = 30


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
        subprocess.run(_command(event), input=payload,
                       timeout=_TIMEOUTS.get(event, _DEFAULT_TIMEOUT),
                       check=False)
    except Exception:
        # Never let a hook failure surface to the user's session.
        pass
