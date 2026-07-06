#!/usr/bin/env python3
"""SessionStart hook — surface a staged post recommendation as an ambient nudge.

Contract: INSTANT. File reads only. Never runs git, never parses transcripts,
never generates anything. The heavy thinking already happened at SessionEnd.

Hard gates (all must pass or we stay silent):
  1. source is a fresh start — `startup` or `clear`, never `resume`/`compact`
  2. a post-worthy recommendation is staged for this repo
  3. that work is unposted (rec.head != watermark.last_posted_head)
  4. not snoozed (now >= watermark.snooze_until)
  5. global cooldown — at most one nudge per calendar day across all repos

On success it emits SessionStart additionalContext (Claude injects it into the
session) and stamps the global cooldown so it won't fire again today.

Reads the hook payload on stdin:
  { "session_id", "source", "cwd", ... }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import postcommit_state as st  # noqa: E402

FRESH_SOURCES = {"startup", "clear"}


def build_nudge(rec):
    window = rec.get("window_hint") or "1d"
    summary = rec.get("summary_line") or "recent work"
    reasons = rec.get("reasons") or []
    reason_txt = ("; ".join(reasons)) if reasons else "looked post-worthy"
    return (
        "[postcommit] Ambient reminder — surface this to the user in your first "
        "reply, then continue normally.\n\n"
        "You did post-worthy work in this repo (%s) but haven't drafted anything "
        "about it yet.\n"
        "- Run `/post %s` to turn it into 3 LinkedIn draft candidates.\n"
        "- Or run `/post-snooze` to hush these nudges for a few days.\n"
        "Why it flagged: %s.\n"
        "(This nudge is rate-limited to at most once per day.)"
        % (summary, window, reason_txt)
    )


def run():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}

    # Gate 1: only on a genuine fresh start.
    source = payload.get("source")
    if source not in FRESH_SOURCES:
        return

    cwd = payload.get("cwd") or os.getcwd()

    # Gate 2: a recommendation must be staged for this repo.
    rec = st.read_json(st.recommendation_path(cwd), None)
    if not rec or rec.get("verdict") != "post-worthy":
        return

    wm = st.read_watermark(cwd)

    # Gate 3: the work must be unposted.
    if rec.get("head") and rec.get("head") == wm.get("last_posted_head"):
        return
    posted_at = st.parse_iso(wm.get("posted_at"))
    rec_at = st.parse_iso(rec.get("created_at"))
    if posted_at and rec_at and posted_at >= rec_at:
        return

    # Gate 4: snooze.
    snooze_until = st.parse_iso(wm.get("snooze_until"))
    if snooze_until and st.now_utc() < snooze_until:
        return

    # Gate 5: global once-per-day cooldown.
    nudge_state = st.read_json(st.nudge_state_path(), {})
    today = st.today_local()
    if nudge_state.get("last_nudge_date") == today:
        return

    # All gates passed — emit the nudge and stamp the cooldown.
    context = build_nudge(rec)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))

    st.write_json(st.nudge_state_path(), {
        "last_nudge_date": today,
        "last_nudge_at": st.iso(st.now_utc()),
        "last_nudge_repo": cwd,
    })


if __name__ == "__main__":
    try:
        run()
    except Exception:  # a broken nudge must never block a session start
        pass
    sys.exit(0)
