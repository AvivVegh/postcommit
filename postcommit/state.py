"""postcommit.state — local-only state for the habit-loop hooks.

Dependency-free (stdlib). Shared by the SessionEnd / SessionStart hook logic and
exposed through the `postcommit state ...` CLI verbs. Also the home for the
small time and git helpers the rest of the package builds on.

State lives in three places:

  <repo>/.postcommit/state/recommendation.json   per-repo staged nudge
  <repo>/.postcommit/state/watermark.json        per-repo "what's processed/posted"
  ~/.postcommit/nudge-state.json                 global once-per-day cooldown

The per-repo `.postcommit/` dir ignores itself (see `ensure_repo_dir`), so state
and drafts never leak into the user's git history and they never have to add an
ignore rule of their own.
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


def repo_dir(cwd):
    return os.path.join(cwd, ".postcommit")


def state_dir(cwd):
    return os.path.join(repo_dir(cwd), "state")


def drafts_dir(cwd):
    return os.path.join(repo_dir(cwd), "drafts")


def recommendation_path(cwd):
    return os.path.join(state_dir(cwd), "recommendation.json")


def synced_path(cwd):
    """Ledger of which draft candidates have already been pushed to the cloud.

    Lives under .postcommit/ so it inherits the self-ignoring .gitignore — it
    records draft filenames, which are transcript-derived, so it must not be
    committable by accident either.
    """
    return os.path.join(state_dir(cwd), "synced.json")


def watermark_path(cwd):
    return os.path.join(state_dir(cwd), "watermark.json")


def global_dir():
    return os.path.join(os.path.expanduser("~"), ".postcommit")


def nudge_state_path():
    return os.path.join(global_dir(), "nudge-state.json")


def bin_dir():
    return os.path.join(global_dir(), "bin")


def launcher_path():
    """Fixed path to the plugin launcher the SessionStart hook writes.

    The model-run /post path can't see ${CLAUDE_PLUGIN_ROOT}, so it reaches the
    plugin-bundled package through this stable location instead.
    """
    return os.path.join(bin_dir(), "postcommit")


# --- the self-ignoring repo dir ---------------------------------------------

GITIGNORE_BODY = (
    "# Created automatically by postcommit.\n"
    "# Everything here is local-only: drafts and nudge state, derived from your\n"
    "# git history and Claude Code sessions. Ignoring `*` (including this file)\n"
    "# keeps it out of git without touching your own .gitignore.\n"
    "# To commit a draft anyway: git add -f .postcommit/drafts/<file>.md\n"
    "*\n"
)


def ensure_repo_dir(cwd):
    """Create <cwd>/.postcommit/ and make it ignore itself. Returns the path.

    The drafts in here are distilled from session transcripts, so "the user has
    to remember a .gitignore rule" is a privacy hole, not just an annoyance. A
    `.gitignore` containing `*` makes the whole tree — the ignore file included —
    invisible to git with no action from the user; git honours ignore files
    whether or not they are tracked. Same trick as .pytest_cache/ and
    .ruff_cache/.

    Best-effort: a failure here must never break a hook or /post, so OSError is
    swallowed. An existing .gitignore is left alone — the user may have edited it
    to un-ignore something deliberately.
    """
    d = repo_dir(cwd)
    try:
        os.makedirs(d, exist_ok=True)
        gitignore = os.path.join(d, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w", encoding="utf-8") as fh:
                fh.write(GITIGNORE_BODY)
    except OSError:
        pass
    return d


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
    ensure_repo_dir(cwd)
    write_json(watermark_path(cwd), wm)


# --- git helpers ------------------------------------------------------------

# git's canonical empty-tree hash. Diffing against it yields "everything since
# the beginning", which is what both the extractor and the scorer need on a
# repo whose first commit is inside the window.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


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


# --- transcript constants ---------------------------------------------------

# Both `scoring.parse_transcript` (cheap, capped, produces signals) and
# `extract.distill_session` (thorough, uncapped, produces narrative) walk the
# same Claude Code JSONL records. The walks are deliberately separate — the hook
# must stay cheap — but the record vocabulary they filter on is one thing, so it
# is tracked here rather than in both.

# Wrapper tags Claude Code injects into user records. A record whose text starts
# with one of these is harness plumbing, not something the human typed.
META_PREFIXES = (
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
    "<system-reminder>",
)

# Tool names that mean the assistant actually changed a file.
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


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


def state_drafts_dir(cwd):
    """Create the drafts dir (self-ignoring) and print it. Used by /post.

    The command layer used to `mkdir -p .postcommit/drafts` itself, which meant
    a draft could land in a repo dir that had never been made self-ignoring.
    Routing it through here keeps that guarantee in one place.
    """
    ensure_repo_dir(cwd)
    d = drafts_dir(cwd)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as exc:
        print("could not create %s: %s" % (d, exc), file=sys.stderr)
        return 1
    print(d)
    return 0


def state_reset(cwd):
    for p in (recommendation_path(cwd), watermark_path(cwd)):
        try:
            os.remove(p)
            print("removed", p)
        except FileNotFoundError:
            pass
    return 0
