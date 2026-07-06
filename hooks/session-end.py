#!/usr/bin/env python3
"""SessionEnd hook — stage a post recommendation if this session was post-worthy.

Contract: cheap, deterministic (NO model call), idempotent, once per session end.
It never generates a post — it only decides "was there post-worthy work here?" and
stages a lightweight recommendation for the SessionStart hook to surface later.

Reads the hook payload on stdin:
  { "session_id", "transcript_path", "cwd", "reason", ... }

Must never break the session: everything is wrapped so we always exit 0 and print
nothing to stdout (SessionEnd stdout is not shown anyway).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import postcommit_state as st  # noqa: E402

# --- tunables ---------------------------------------------------------------

POST_WORTHY_THRESHOLD = 5
MAX_TRANSCRIPT_LINES = 8000  # cap work so the hook stays cheap on huge sessions
IDLE_GAP_SECONDS = 15 * 60   # a gap longer than this counts as idle, not work

_META_PREFIXES = (
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
    "<system-reminder>",
)
_STORY_KEYWORDS = (
    "bug", "error", "crash", "fail", "broke", "broken", "fix", "fixed",
    "refactor", "race", "deadlock", "timeout", "leak", "slow", "regression",
    "flaky", "deploy", "ship", "shipped", "root cause", "stack trace",
    "segfault", "panic", "exception", "null", "undefined", "stuck",
)
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


# --- transcript signals -----------------------------------------------------


def parse_transcript(path):
    """Extract cheap signals from a session JSONL. Returns a dict of counts."""
    sig = {
        "n_user_prompts": 0,
        "n_edits": 0,
        "duration_min": 0,
        "keywords": set(),
        "first_ts": None,
    }
    if not path or not os.path.exists(path):
        return sig

    # "Active" minutes = sum of gaps between consecutive events, but only gaps
    # shorter than IDLE_GAP_SECONDS. A session left open all day is mostly one
    # giant idle gap, so it no longer reads as hours of work (false positive).
    first = None
    prev = None
    active_seconds = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= MAX_TRANSCRIPT_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue

                ts = st.parse_iso(rec.get("timestamp"))
                if ts:
                    if first is None:
                        first = ts
                    if prev is not None:
                        gap = (ts - prev).total_seconds()
                        if 0 < gap <= IDLE_GAP_SECONDS:
                            active_seconds += gap
                    prev = ts

                rtype = rec.get("type")
                if rtype == "user":
                    msg = rec.get("message") or {}
                    content = msg.get("content")
                    if (
                        isinstance(content, str)
                        and not rec.get("isMeta")
                        and not content.lstrip().startswith(_META_PREFIXES)
                    ):
                        sig["n_user_prompts"] += 1
                        low = content.lower()
                        for kw in _STORY_KEYWORDS:
                            if kw in low:
                                sig["keywords"].add(kw)
                elif rtype == "assistant":
                    msg = rec.get("message") or {}
                    for block in msg.get("content") or []:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") in _EDIT_TOOLS
                        ):
                            sig["n_edits"] += 1
    except OSError:
        return sig

    sig["first_ts"] = first
    sig["duration_min"] = int(active_seconds // 60)
    return sig


# --- git signals ------------------------------------------------------------


def git_signals(cwd, last_posted_head):
    """Commit count + diff size since the last post (or last 24h as a fallback)."""
    sig = {"n_commits": 0, "files": 0, "insertions": 0, "deletions": 0,
           "has_uncommitted": False, "window_hint": "1d", "range": None}

    if last_posted_head and st.is_ancestor(cwd, last_posted_head):
        rng = "%s..HEAD" % last_posted_head
        sig["window_hint"] = rng
        sig["range"] = rng
        log = st.git(cwd, "log", "--oneline", rng)
        diffstat = st.git(cwd, "diff", "--shortstat", rng)
    else:
        log = st.git(cwd, "log", "--oneline", "--since=1 day ago")
        diffstat = st.git(cwd, "diff", "--shortstat", "--since=1 day ago")

    if log:
        sig["n_commits"] = len([l for l in log.splitlines() if l.strip()])
    _parse_shortstat(diffstat, sig)

    # uncommitted work counts toward "there is something to talk about"
    status = st.git(cwd, "status", "--porcelain")
    sig["has_uncommitted"] = bool(status)
    if status and not sig["insertions"] and not sig["deletions"]:
        # no committed diff in window but dirty tree — measure that instead
        _parse_shortstat(st.git(cwd, "diff", "--shortstat"), sig)
        _parse_shortstat_add(st.git(cwd, "diff", "--staged", "--shortstat"), sig)
    return sig


def _parse_shortstat(text, sig):
    """`N files changed, N insertions(+), N deletions(-)` -> fill sig (replace)."""
    files = ins = dels = 0
    if text:
        for part in text.split(","):
            part = part.strip()
            n = "".join(ch for ch in part if ch.isdigit())
            if not n:
                continue
            n = int(n)
            if "file" in part:
                files = n
            elif "insertion" in part:
                ins = n
            elif "deletion" in part:
                dels = n
    sig["files"] = files
    sig["insertions"] = ins
    sig["deletions"] = dels


def _parse_shortstat_add(text, sig):
    """Same, but add onto existing counts (for staged + unstaged)."""
    tmp = {"files": 0, "insertions": 0, "deletions": 0}
    _parse_shortstat(text, tmp)
    sig["files"] += tmp["files"]
    sig["insertions"] += tmp["insertions"]
    sig["deletions"] += tmp["deletions"]


# --- scoring ----------------------------------------------------------------


def score(git_sig, tx_sig):
    """Deterministic post-worthiness score + human-readable reasons."""
    pts = 0
    reasons = []

    if git_sig["n_commits"] > 0:
        c = min(git_sig["n_commits"], 2) * 3  # +3/commit, capped at +6
        pts += c
        reasons.append("%d new commit%s" % (git_sig["n_commits"],
                                            "" if git_sig["n_commits"] == 1 else "s"))

    churn = git_sig["insertions"] + git_sig["deletions"]
    if churn >= 30 and git_sig["files"] >= 2:
        pts += 2
        reasons.append("%d files touched (+%d/-%d)" % (
            git_sig["files"], git_sig["insertions"], git_sig["deletions"]))
        if churn >= 150:
            pts += 1
    elif git_sig["has_uncommitted"] and churn > 0:
        pts += 1
        reasons.append("uncommitted work in progress (+%d/-%d)" % (
            git_sig["insertions"], git_sig["deletions"]))

    if tx_sig["n_edits"] >= 3:
        pts += 1
    if tx_sig["n_user_prompts"] >= 3:
        pts += 1
        reasons.append("%d real prompts this session" % tx_sig["n_user_prompts"])
    if tx_sig["duration_min"] >= 15:
        pts += 1
        reasons.append("~%d min of active work" % tx_sig["duration_min"])
    if tx_sig["keywords"]:
        pts += 1
        reasons.append("debugging-story signal (%s)" %
                       ", ".join(sorted(tx_sig["keywords"])[:3]))

    # trivial-change guard: no commits AND barely any churn -> not a story
    if git_sig["n_commits"] == 0 and churn < 10:
        pts = min(pts, POST_WORTHY_THRESHOLD - 2)

    return pts, reasons


# --- drafts (did the user already act?) -------------------------------------


def fresh_draft_since(cwd, first_ts):
    """True if a /post draft was written during this session."""
    drafts_dir = os.path.join(cwd, ".postcommit", "drafts")
    if not os.path.isdir(drafts_dir) or first_ts is None:
        return False
    cutoff = first_ts.timestamp()
    try:
        for name in os.listdir(drafts_dir):
            if not name.endswith(".md"):
                continue
            if os.path.getmtime(os.path.join(drafts_dir, name)) >= cutoff:
                return True
    except OSError:
        return False
    return False


# --- main -------------------------------------------------------------------


def run():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or "unknown"
    transcript_path = payload.get("transcript_path")

    if not st.is_git_repo(cwd):
        return  # nothing to talk about outside a repo

    wm = st.read_watermark(cwd)
    if session_id in wm["processed_sessions"]:
        return  # idempotent: already handled this session

    tx = parse_transcript(transcript_path)

    # If the user already ran /post this session, that work is spent. Pin the
    # watermark to HEAD, drop any stale rec, and don't nudge about it later.
    if fresh_draft_since(cwd, tx["first_ts"]):
        wm["last_posted_head"] = st.git_head(cwd)
        wm["posted_at"] = st.iso(st.now_utc())
        try:
            os.remove(st.recommendation_path(cwd))
        except FileNotFoundError:
            pass
    else:
        gsig = git_signals(cwd, wm["last_posted_head"])
        pts, reasons = score(gsig, tx)
        if pts >= POST_WORTHY_THRESHOLD:
            rec = {
                "created_at": st.iso(st.now_utc()),
                "session_id": session_id,
                "cwd": cwd,
                "repo": os.path.basename(cwd),
                "branch": st.git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "?",
                "head": st.git_head(cwd),
                "score": pts,
                "verdict": "post-worthy",
                "reasons": reasons,
                "window_hint": gsig["window_hint"],
                "summary_line": _summary_line(gsig, tx),
            }
            st.write_json(st.recommendation_path(cwd), rec)
        # if not post-worthy, we leave any prior pending rec untouched

    wm["processed_sessions"].append(session_id)
    wm["last_end_head"] = st.git_head(cwd)
    st.write_watermark(cwd, wm)


def _summary_line(gsig, tx):
    bits = []
    if gsig["n_commits"]:
        bits.append("%d commit%s" % (gsig["n_commits"],
                                     "" if gsig["n_commits"] == 1 else "s"))
    if gsig["files"]:
        bits.append("%d file%s touched" % (gsig["files"],
                                            "" if gsig["files"] == 1 else "s"))
    if tx["duration_min"]:
        bits.append("~%d min" % tx["duration_min"])
    return ", ".join(bits) or "recent work"


if __name__ == "__main__":
    try:
        run()
    except Exception:  # never let a hook break the session
        pass
    sys.exit(0)
