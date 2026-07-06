"""Shared helpers for the postcommit test suite.

Zero third-party deps — stdlib `unittest` only, mirroring the package itself.
Two jobs live here:

  1. Import the package modules under test (postcommit.*). The repo root is put
     on sys.path so an editable install isn't required to run the suite.
  2. Build throwaway git repos and transcript JSONLs for the tests that need
     real git output or a real session file, plus a subprocess runner that
     drives the thin hook shims end-to-end.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "hooks")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from postcommit import (  # noqa: E402,F401  (re-exported)
    extract,
    hooks,
    scoring,
    state,  # noqa: E402,F401  (re-exported)
)

# Back-compat aliases so tests can read naturally.
session_end = hooks
session_start = hooks


# --- git fixtures -----------------------------------------------------------

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    # keep a user's global git config from leaking into the fixture repo
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _run_git(cwd, *args):
    env = dict(os.environ, **_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env,
        capture_output=True, text=True, check=True,
    )


def init_repo(path):
    """Create an empty git repo at `path` with a deterministic identity."""
    os.makedirs(path, exist_ok=True)
    _run_git(path, "init", "-q")
    _run_git(path, "config", "user.email", "test@example.com")
    _run_git(path, "config", "user.name", "Test")
    return path


def commit(path, filename, contents, message):
    """Write a file and commit it; return the new HEAD sha."""
    with open(os.path.join(path, filename), "w", encoding="utf-8") as fh:
        fh.write(contents)
    _run_git(path, "add", "-A")
    _run_git(path, "commit", "-q", "-m", message)
    return _run_git(path, "rev-parse", "HEAD").stdout.strip()


# --- transcript fixtures ----------------------------------------------------


def write_transcript(path, records):
    """Serialize a list of dicts as a session JSONL file at `path`."""
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def user_msg(content, ts=None, is_meta=False):
    rec = {"type": "user", "message": {"content": content}}
    if ts:
        rec["timestamp"] = ts
    if is_meta:
        rec["isMeta"] = True
    return rec


def assistant_text(text, ts=None):
    rec = {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    if ts:
        rec["timestamp"] = ts
    return rec


def tool_use_msg(tool_name, tool_input=None, ts=None):
    rec = {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": tool_name, "input": tool_input or {}}]},
    }
    if ts:
        rec["timestamp"] = ts
    return rec


def edit_msg(tool_name, ts=None):
    return tool_use_msg(tool_name, {}, ts)


# --- subprocess runner for the thin hook shims ------------------------------


def run_hook(script_basename, payload, home):
    """Run a thin hook shim end-to-end via subprocess.

    Feeds `payload` on stdin as JSON, points HOME at `home` so the global daily
    cooldown file lands in a throwaway dir, and sets PYTHONPATH so the shim's
    `python -m postcommit` fallback resolves the package from this checkout.
    Returns the CompletedProcess (hooks always exit 0).
    """
    env = dict(os.environ, HOME=home, PYTHONPATH=ROOT, **_GIT_ENV)
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, script_basename)],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env,
    )
