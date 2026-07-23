"""Shared forwarding logic for the thin SessionEnd / SessionStart hook shims.

Resolves the `postcommit` CLI and pipes the hook's stdin payload to
`postcommit hook <event>`, passing the CLI's stdout straight through (that is
how the SessionStart nudge JSON reaches Claude Code). Everything is best-effort:
a missing CLI or a subprocess error is swallowed so the hook never breaks a
session.

Resolution order: a standalone-installed `postcommit` on PATH wins (it stays
authoritative). Otherwise fall back to `python -m postcommit` resolved from the
plugin-bundled package, with PYTHONPATH pointed at the plugin root — so the
plugin works with no separate pip/uv install.
"""

import os
import shutil
import subprocess
import sys

# Per-event subprocess timeout. session-start is a file-read-only path that must
# feel instant, so it is bounded tightly — a pathological hang can't stall
# session startup for long. session-end does git work and may legitimately take
# longer. The default covers any future event.
_TIMEOUTS = {"session-start": 8, "session-end": 30}
_DEFAULT_TIMEOUT = 30


def _plugin_root():
    """The plugin/repo root holding the bundled `postcommit` package.

    Claude Code sets CLAUDE_PLUGIN_ROOT for plugin hooks; fall back to two levels
    up from this file (`hooks/` -> repo root) for a source checkout.
    """
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _command(event):
    """Prefer a standalone-installed console script; else `python -m postcommit`
    resolved from the plugin-bundled package."""
    exe = shutil.which("postcommit")
    if exe:
        return [exe, "hook", event]
    return [sys.executable, "-m", "postcommit", "hook", event]


def _child_env(root):
    """Environment for the `python -m postcommit` fallback: make the bundled
    package importable and expose the plugin root to the hook logic (which uses
    it to write the launcher)."""
    env = dict(os.environ)
    if root:
        env.setdefault("CLAUDE_PLUGIN_ROOT", root)
        prev = env.get("PYTHONPATH")
        env["PYTHONPATH"] = root + (os.pathsep + prev if prev else "")
    return env


def forward(event):
    payload = sys.stdin.buffer.read()
    cmd = _command(event)
    # The module fallback needs PYTHONPATH/CLAUDE_PLUGIN_ROOT to reach the bundled
    # package; a PATH `postcommit` is self-contained, so inherit env unchanged.
    env = _child_env(_plugin_root()) if cmd[0] == sys.executable else None
    try:
        # No capture: the child's stdout (the nudge JSON, for session-start)
        # inherits this process's stdout and reaches Claude Code directly.
        subprocess.run(cmd, input=payload,
                       timeout=_TIMEOUTS.get(event, _DEFAULT_TIMEOUT),
                       env=env, check=False)  # env=None inherits current env
    except Exception:
        # Never let a hook failure surface to the user's session.
        pass
