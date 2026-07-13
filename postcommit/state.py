"""postcommit.state — local-only state for the habit-loop hooks.

Dependency-free (stdlib). Shared by the SessionEnd / SessionStart hook logic and
exposed through the `postcommit state ...` CLI verbs. Also the home for the
small time and git helpers the rest of the package builds on.

State lives in three places:

  <repo>/.postcommit/state/recommendation.json   per-repo staged nudge
  <repo>/.postcommit/state/watermark.json        per-repo "what's processed/posted"
  ~/.postcommit/nudge-state.json                 global once-per-day cooldown

The `.postcommit/` dir is gitignored, so per-repo state never leaks.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# --- time -------------------------------------------------------------------


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    """UTC ISO-8601 with a trailing Z, seconds precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO timestamp (with or without trailing Z). None on failure.

    Always returns a timezone-aware datetime: a value that parses without an
    offset is assumed UTC. This keeps every downstream comparison/subtraction
    tz-safe — mixing a naive and an aware datetime raises TypeError, which the
    transcript loops (guarded only by `except OSError`) would not catch.
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def today_local():
    """Calendar date in the user's local tz — the unit of the daily cooldown."""
    return datetime.now().strftime("%Y-%m-%d")


# --- paths ------------------------------------------------------------------


def state_dir(cwd):
    return os.path.join(cwd, ".postcommit", "state")


def recommendation_path(cwd):
    return os.path.join(state_dir(cwd), "recommendation.json")


def watermark_path(cwd):
    return os.path.join(state_dir(cwd), "watermark.json")


def global_dir():
    return os.path.join(os.path.expanduser("~"), ".postcommit")


def nudge_state_path():
    return os.path.join(global_dir(), "nudge-state.json")


# --- json io ----------------------------------------------------------------


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return default


def write_json(path, data):
    """Atomic write: temp file in the same dir, then os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --- watermark --------------------------------------------------------------


def default_watermark():
    return {
        "last_posted_head": None,   # git HEAD at the last time work here was posted
        "posted_at": None,          # ISO timestamp of that post
        "snooze_until": None,       # ISO; nudges suppressed until this instant
        "processed_sessions": [],   # session_ids already handled by session-end
        "last_end_head": None,      # git HEAD at the last processed session end
    }


def read_watermark(cwd):
    wm = default_watermark()
    wm.update(read_json(watermark_path(cwd), {}))
    # keep the processed-session list bounded; only recency matters
    if isinstance(wm.get("processed_sessions"), list):
        wm["processed_sessions"] = wm["processed_sessions"][-200:]
    else:
        wm["processed_sessions"] = []
    return wm


def write_watermark(cwd, wm):
    write_json(watermark_path(cwd), wm)


# --- git helpers ------------------------------------------------------------


def git(cwd, *args):
    """Run a git command in cwd; return stripped stdout, or None on error."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def is_git_repo(cwd):
    return git(cwd, "rev-parse", "--is-inside-work-tree") == "true"


def git_head(cwd):
    return git(cwd, "rev-parse", "HEAD")


def is_ancestor(cwd, sha):
    """True if `sha` is a valid ancestor of HEAD."""
    if not sha:
        return False
    try:
        out = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
            cwd=cwd,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def parse_shortstat(text):
    """Parse `git diff --shortstat` output into (files, insertions, deletions).

    Returns zeros for empty or unrecognized input. Shared by the extractor and
    the scorer so git's wording is tracked in exactly one place.
    """
    files = insertions = deletions = 0
    for part in (text or "").split(","):
        part = part.strip()
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            continue
        n = int(digits)
        if "file" in part:
            files = n
        elif "insertion" in part:
            insertions = n
        elif "deletion" in part:
            deletions = n
    return files, insertions, deletions


# --- state verbs (backing the `postcommit state ...` CLI) -------------------


def state_show(cwd):
    print("repo:", cwd)
    print("head:", git_head(cwd))
    print("\nwatermark:")
    print(json.dumps(read_watermark(cwd), indent=2, sort_keys=True))
    print("\nrecommendation:")
    print(json.dumps(read_json(recommendation_path(cwd), None), indent=2, sort_keys=True))
    print("\nglobal nudge-state:")
    print(json.dumps(read_json(nudge_state_path(), None), indent=2, sort_keys=True))
    return 0


def state_snooze(cwd, days_arg=None):
    days = 3
    if days_arg is not None:
        try:
            days = max(1, int(days_arg))
        except (ValueError, TypeError):
            print("usage: postcommit state snooze [DAYS]", file=sys.stderr)
            return 2
    wm = read_watermark(cwd)
    until = now_utc() + timedelta(days=days)
    wm["snooze_until"] = iso(until)
    write_watermark(cwd, wm)
    print("snoozed postcommit nudges for %d day(s), until %s" % (days, iso(until)))
    return 0


def state_unsnooze(cwd):
    wm = read_watermark(cwd)
    wm["snooze_until"] = None
    write_watermark(cwd, wm)
    print("snooze cleared")
    return 0


def state_mark_posted(cwd):
    wm = read_watermark(cwd)
    head = git_head(cwd)
    wm["last_posted_head"] = head
    wm["posted_at"] = iso(now_utc())
    write_watermark(cwd, wm)
    # a posted rec is spent
    try:
        os.remove(recommendation_path(cwd))
    except FileNotFoundError:
        pass
    print("marked posted at HEAD", head)
    return 0


def state_stage_fake(cwd):
    rec = {
        "created_at": iso(now_utc()),
        "session_id": "fake-session",
        "cwd": cwd,
        "repo": os.path.basename(cwd),
        "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "head": git_head(cwd),
        "score": 8,
        "verdict": "post-worthy",
        "reasons": ["fake recommendation staged for testing"],
        "window_hint": "1d",
        "summary_line": "fake: 2 commits, 1 session, 5 files touched",
    }
    write_json(recommendation_path(cwd), rec)
    print("staged fake recommendation at", recommendation_path(cwd))
    return 0


def state_reset(cwd):
    for p in (recommendation_path(cwd), watermark_path(cwd)):
        try:
            os.remove(p)
            print("removed", p)
        except FileNotFoundError:
            pass
    return 0
