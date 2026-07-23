"""postcommit.hooks — SessionEnd / SessionStart hook logic.

The thin scripts under `hooks/` forward their stdin payload to
`postcommit hook session-end|session-start`, which calls the functions here.

Contracts (unchanged from the original stdlib hooks):

  handle_session_end(payload)
      Cheap, deterministic (NO model call), idempotent, once per session end.
      Never generates a post — only decides "was there post-worthy work?" and
      stages a lightweight recommendation for SessionStart to surface.

  handle_session_start(payload) -> str | None
      INSTANT. File reads only. Returns the additionalContext string to inject
      (and stamps the daily cooldown) when all gates pass, else None.
"""

import os

from . import scoring
from . import state as st

FRESH_SOURCES = {"startup", "clear"}

# Written to ~/.postcommit/bin/postcommit so the model-run /post path (which
# cannot see ${CLAUDE_PLUGIN_ROOT}) can invoke the plugin-bundled package with no
# separate pip/uv install. PYTHONPATH points at the plugin root so `python3 -m
# postcommit` imports the bundled copy.
_LAUNCHER_TEMPLATE = (
    "#!/bin/sh\n"
    "# postcommit launcher — auto-written by the SessionStart hook. Lets the\n"
    "# /post command and extract skill reach the plugin-bundled package without a\n"
    "# separate install. Regenerated whenever the plugin root changes.\n"
    "export PYTHONPATH=\"%s${PYTHONPATH:+:$PYTHONPATH}\"\n"
    "exec python3 -m postcommit \"$@\"\n"
)


def _ensure_launcher(plugin_root):
    """Best-effort: write ~/.postcommit/bin/postcommit pointing at plugin_root.

    No-op when plugin_root is unknown (source checkout / standalone install) or
    doesn't actually bundle the package, and when the launcher is already current
    — so an upgrade that moves the plugin root is picked up but a steady state
    isn't rewritten every session. Never raises: a hook must not break a session.
    """
    if not plugin_root:
        return
    try:
        if not os.path.isfile(
                os.path.join(plugin_root, "postcommit", "__main__.py")):
            return  # plugin_root doesn't bundle the package — nothing to launch
        path = st.launcher_path()
        desired = _LAUNCHER_TEMPLATE % plugin_root
        try:
            with open(path, encoding="utf-8") as fh:
                if fh.read() == desired:
                    return  # already current
        except OSError:
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(desired)
        os.chmod(path, 0o755)
    except Exception:
        pass


# --- SessionEnd -------------------------------------------------------------


def handle_session_end(payload):
    """Stage a post recommendation if this session was post-worthy."""
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or "unknown"
    transcript_path = payload.get("transcript_path")

    if not st.is_git_repo(cwd):
        return  # nothing to talk about outside a repo

    wm = st.read_watermark(cwd)
    if session_id in wm["processed_sessions"]:
        return  # idempotent: already handled this session

    tx = scoring.parse_transcript(transcript_path)

    # If the user already ran /post this session, that work is spent. Pin the
    # watermark to HEAD, drop any stale rec, and don't nudge about it later.
    if scoring.fresh_draft_since(cwd, tx["first_ts"]):
        wm["last_posted_head"] = st.git_head(cwd)
        wm["posted_at"] = st.iso(st.now_utc())
        try:
            os.remove(st.recommendation_path(cwd))
        except FileNotFoundError:
            pass
    else:
        gsig = scoring.git_signals(cwd, wm["last_posted_head"])
        pts, reasons = scoring.score(gsig, tx)
        if pts >= scoring.POST_WORTHY_THRESHOLD:
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
                "summary_line": scoring.summary_line(gsig, tx),
            }
            st.write_json(st.recommendation_path(cwd), rec)
        # if not post-worthy, we leave any prior pending rec untouched

    wm["processed_sessions"].append(session_id)
    wm["last_end_head"] = st.git_head(cwd)
    st.write_watermark(cwd, wm)


# --- SessionStart -----------------------------------------------------------


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


def handle_session_start(payload):
    """Return the nudge context string when all gates pass, else None.

    Side effect on success: stamps the global once-per-day cooldown.
    """
    # Bootstrap the plugin launcher on every start (any source), before the
    # nudge gates — this is how the /post path reaches the bundled package.
    _ensure_launcher(os.environ.get("CLAUDE_PLUGIN_ROOT"))

    # Gate 1: only on a genuine fresh start.
    source = payload.get("source")
    if source not in FRESH_SOURCES:
        return None

    cwd = payload.get("cwd") or os.getcwd()

    # Gate 2: a recommendation must be staged for this repo.
    rec = st.read_json(st.recommendation_path(cwd), None)
    if not rec or rec.get("verdict") != "post-worthy":
        return None

    wm = st.read_watermark(cwd)

    # Gate 3: the work must be unposted.
    if rec.get("head") and rec.get("head") == wm.get("last_posted_head"):
        return None
    posted_at = st.parse_iso(wm.get("posted_at"))
    rec_at = st.parse_iso(rec.get("created_at"))
    if posted_at and rec_at and posted_at >= rec_at:
        return None

    # Gate 4: snooze.
    snooze_until = st.parse_iso(wm.get("snooze_until"))
    if snooze_until and st.now_utc() < snooze_until:
        return None

    # Gate 5: global once-per-day cooldown.
    nudge_state = st.read_json(st.nudge_state_path(), {})
    today = st.today_local()
    if nudge_state.get("last_nudge_date") == today:
        return None

    # All gates passed — stamp the cooldown and return the nudge.
    context = build_nudge(rec)
    st.write_json(st.nudge_state_path(), {
        "last_nudge_date": today,
        "last_nudge_at": st.iso(st.now_utc()),
        "last_nudge_repo": cwd,
    })
    return context
