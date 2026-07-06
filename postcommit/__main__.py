"""postcommit — command-line entry point.

    postcommit extract <window>          emit a work bundle to stdout
    postcommit state [show|snooze [N]|unsnooze|mark-posted|stage-fake|reset]
    postcommit hook session-end          run the SessionEnd logic (payload on stdin)
    postcommit hook session-start        run the SessionStart logic (payload on stdin)
    postcommit install [--claude]        write the skill adapter into ~/.claude
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
    if verb == "stage-fake":
        return st.state_stage_fake(cwd)
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


def cmd_install(args):
    from . import install
    return install.install(claude=args.claude or not args.no_claude)


def build_parser():
    p = argparse.ArgumentParser(prog="postcommit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version",
                   version="postcommit %s" % __version__)
    sub = p.add_subparsers(dest="command")

    pe = sub.add_parser("extract", help="emit a work bundle for a window")
    pe.add_argument("window", help="1d | 4h | 30m | today | <sha>..<sha> | since=YYYY-MM-DD")
    pe.set_defaults(func=cmd_extract)

    ps = sub.add_parser("state", help="inspect/adjust per-repo nudge state")
    ps.add_argument("verb", nargs="?", default="show",
                    choices=["show", "snooze", "unsnooze", "mark-posted",
                             "stage-fake", "reset"])
    ps.add_argument("days", nargs="?", default=None, help="days for `snooze`")
    ps.set_defaults(func=cmd_state)

    ph = sub.add_parser("hook", help="run hook logic (payload on stdin)")
    ph.add_argument("event", choices=["session-end", "session-start"])
    ph.set_defaults(func=cmd_hook)

    pi = sub.add_parser("install", help="write the skill adapter into a host")
    pi.add_argument("--claude", action="store_true",
                    help="install into ~/.claude (default)")
    pi.add_argument("--no-claude", action="store_true",
                    help="skip the Claude Code install")
    pi.set_defaults(func=cmd_install)

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
