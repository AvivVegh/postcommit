"""postcommit — command-line entry point.

    postcommit extract <window>          emit a work bundle to stdout
    postcommit state [show|snooze [N]|unsnooze|mark-posted|drafts-dir|reset]
    postcommit cloud [status|login [TOKEN] [--browser]|logout|sync [--dry-run]]
    postcommit hook session-end          run the SessionEnd logic (payload on stdin)
    postcommit hook session-start        run the SessionStart logic (payload on stdin)
    postcommit --version

The `hook` verbs read the Claude Code hook payload as JSON on stdin. They are
wrapped so they never raise — a broken hook must never break a user's session.
"""

import argparse
import json
import os
import sys

from . import __version__


def _read_payload():
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def cmd_extract(args):
    from . import extract
    try:
        bundle = extract.build_bundle(args.window, os.getcwd())
    except extract.WindowError as exc:
        print("postcommit extract: %s" % exc, file=sys.stderr)
        return 2
    except extract.NotARepoError as exc:
        print("postcommit extract: %s" % exc, file=sys.stderr)
        return 1
    sys.stdout.write(bundle)
    if not bundle.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_state(args):
    from . import state as st
    cwd = os.getcwd()
    verb = args.verb or "show"
    if verb == "show":
        return st.state_show(cwd)
    if verb == "snooze":
        return st.state_snooze(cwd, args.days)
    if verb == "unsnooze":
        return st.state_unsnooze(cwd)
    if verb == "mark-posted":
        return st.state_mark_posted(cwd)
    if verb == "drafts-dir":
        return st.state_drafts_dir(cwd)
    if verb == "reset":
        return st.state_reset(cwd)
    print("unknown state verb: %s" % verb, file=sys.stderr)
    return 2


def cmd_hook(args):
    # Hooks must never break a session: swallow everything and exit 0.
    try:
        from . import hooks
        payload = _read_payload()
        if args.event == "session-end":
            hooks.handle_session_end(payload)
        elif args.event == "session-start":
            context = hooks.handle_session_start(payload)
            if context:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": context,
                    }
                }))
    except Exception:
        pass
    return 0


def cmd_cloud(args):
    """Cloud auth verbs, on the *main* CLI so the launcher can reach them.

    `postcommit-cloud-mcp` is a separate console script, and the launcher the
    SessionStart hook writes runs `python3 -m postcommit` — so before this existed
    the /post-login command could not reach cloud auth through the plugin at all
    and had to hunt for a source checkout. cloud_login is stdlib-only, so hanging
    these verbs here costs the dependency-free core nothing.
    """
    from . import cloud_login
    verb = args.verb or "status"

    # `sync` is the one non-auth verb here: it lives on this parser for the same
    # reason the auth verbs do — the launcher runs `python3 -m postcommit`, so a
    # verb anywhere else is unreachable from a slash command.
    if verb == "sync":
        from . import cloud_sync
        return cloud_sync.cmd_sync(os.getcwd(), dry_run=args.dry_run)

    try:
        if verb == "status":
            return cloud_login.status()[1]
        if verb == "login":
            if args.token:
                cloud_login.login_paste(blob=args.token)
            elif args.browser:
                cloud_login.login()
            else:
                cloud_login.login_paste()
            return 0
        if verb == "logout":
            cloud_login.logout()
            return 0
    except cloud_login.LoginError as exc:
        print("Login failed: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 1
    print("unknown cloud verb: %s" % verb, file=sys.stderr)
    return 2


def build_parser():
    p = argparse.ArgumentParser(prog="postcommit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version",
                   version="postcommit %s" % __version__)
    sub = p.add_subparsers(dest="command")

    pc = sub.add_parser("cloud",
                        help="cloud: status / login / logout / sync")
    pc.add_argument("verb", nargs="?", default="status",
                    choices=["status", "login", "logout", "sync"])
    pc.add_argument("token", nargs="?", default=None,
                    help="paste bundle for `login` (omit to be prompted)")
    pc.add_argument("--browser", action="store_true",
                    help="`login` via the loopback browser flow instead of a paste")
    pc.add_argument("--dry-run", action="store_true",
                    help="`sync`: list what would be pushed, touching no network")
    pc.set_defaults(func=cmd_cloud)

    pe = sub.add_parser("extract", help="emit a work bundle for a window")
    pe.add_argument("window", help="1d | 4h | 30m | today | <sha>..<sha> | since=YYYY-MM-DD")
    pe.set_defaults(func=cmd_extract)

    ps = sub.add_parser("state", help="inspect/adjust per-repo nudge state")
    ps.add_argument("verb", nargs="?", default="show",
                    choices=["show", "snooze", "unsnooze", "mark-posted",
                             "drafts-dir", "reset"])
    ps.add_argument("days", nargs="?", default=None, help="days for `snooze`")
    ps.set_defaults(func=cmd_state)

    ph = sub.add_parser("hook", help="run hook logic (payload on stdin)")
    ph.add_argument("event", choices=["session-end", "session-start"])
    ph.set_defaults(func=cmd_hook)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
