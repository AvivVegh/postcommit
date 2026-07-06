"""Shared helpers for the postcommit test suite.

Zero third-party deps — stdlib `unittest` only, mirroring the hooks themselves.
Two jobs live here:

  1. Load the hook modules. Two of them have hyphenated filenames
     (`session-end.py`, `session-start.py`) that a plain `import` can't reach,
     so we load every hook by path via importlib.
  2. Build throwaway git repos and transcript JSONLs for the tests that need
     real git output or a real session file.
"""

import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "hooks")


def _load(name, filename):
    """Import a hook module by file path (handles hyphenated filenames)."""
    # The hooks do `import postcommit_state`, so their dir must be importable.
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


state = _load("postcommit_state", "postcommit_state.py")
session_end = _load("session_end", "session-end.py")
session_start = _load("session_start", "session-start.py")


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


def edit_msg(tool_name, ts=None):
    rec = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": tool_name}]},
    }
    if ts:
        rec["timestamp"] = ts
    return rec


# --- subprocess runner for the hooks ----------------------------------------


def run_hook(script_basename, payload, home):
    """Run a hook script end-to-end via subprocess.

    Feeds `payload` on stdin as JSON and points HOME at `home` so the global
    once-per-day cooldown file lands in a throwaway dir. Returns the
    CompletedProcess (hooks always exit 0).
    """
    env = dict(os.environ, HOME=home, **_GIT_ENV)
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, script_basename)],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env,
    )
