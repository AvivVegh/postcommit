"""postcommit.cloud_sync — push saved draft candidates to postcommit-cloud.

This is the one place besides auth where local content leaves the machine, so
the rules are tight:

* Only files under `.postcommit/drafts/` are read, and only the post bodies
  within them — `postcommit.drafts` strips the `### Post` / `### Candidate`
  labels and the legacy `— why this angle` reviewer notes before anything is sent.
* Every push is recorded in `.postcommit/state/synced.json` keyed by draft file
  and post key (the work item's short sha; a candidate letter for the legacy
  three-candidate drafts), and the ledger is written after *each* successful
  push. A crash or a Ctrl-C mid-run therefore costs at most zero duplicates on
  the next run — re-running is safe.
* `plan()` performs no network I/O at all, so the command layer can show the
  user exactly what would be uploaded before anything is.

Stdlib-only, like the rest of the cloud client core: it imports `cloud_client`
lazily so `postcommit sync --dry-run` works even on a machine that has never
been configured for the cloud.
"""

import os
import sys

from . import state

# The backend caps a post body at 3000 characters. Checking here turns what
# would be an opaque HTTP 400 into a skip with a readable reason, and keeps one
# oversized candidate from aborting a whole run.
MAX_CONTENT_CHARS = 3000

LEDGER_VERSION = 1


def _empty_ledger():
    return {"version": LEDGER_VERSION, "drafts": {}}


def read_ledger(cwd):
    data = state.read_json(state.synced_path(cwd), None)
    if not isinstance(data, dict) or not isinstance(data.get("drafts"), dict):
        return _empty_ledger()
    return data


def write_ledger(cwd, ledger):
    state.ensure_repo_dir(cwd)
    state.write_json(state.synced_path(cwd), ledger)


def draft_files(cwd):
    """Every saved draft, oldest first.

    Filenames are UTC ISO timestamps, so a plain sort is chronological.
    """
    d = state.drafts_dir(cwd)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return [os.path.join(d, n) for n in sorted(names) if n.endswith(".md")]


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def ledger_key(draft_name, cand):
    """The ledger key for one parsed post. The sha↔ledger mapping lives here.

    `/post` names a draft `<UTC-ISO>-<item>.md`, where `<item>` is the work
    item's short sha (or `working`), so the key comes off the filename — stable
    across re-runs, which is what keeps an overlapping `/post` window from
    re-pushing work already synced. A legacy three-candidate draft keeps its
    letter instead, so ledgers written before the split still block re-pushes.
    """
    from . import drafts as drafts_mod

    key = cand.get("key") or drafts_mod.POST_KEY
    if key != drafts_mod.POST_KEY:
        return key
    stem = draft_name[:-3] if draft_name.endswith(".md") else draft_name
    if "Z-" in stem:
        item = stem.rsplit("Z-", 1)[1].strip()
        if item:
            return item
    return drafts_mod.POST_KEY


def plan(cwd):
    """What a sync would do, without touching the network.

    Returns (pending, skipped, already) where `pending` items are dicts with
    draft/key/angle/content/chars, `skipped` items carry a `reason`, and
    `already` is the count of posts the ledger has seen.
    """
    from . import drafts as drafts_mod

    ledger = read_ledger(cwd)
    pending, skipped, already = [], [], 0

    for path in draft_files(cwd):
        name = os.path.basename(path)
        seen = ledger["drafts"].get(name, {})
        candidates = drafts_mod.parse_candidates(_read(path))
        if not candidates:
            skipped.append({"draft": name, "key": None,
                            "reason": "no post blocks found"})
            continue
        for cand in candidates:
            key = ledger_key(name, cand)
            if key in seen:
                already += 1
                continue
            item = {
                "draft": name,
                "key": key,
                "legacy": cand["key"] != drafts_mod.POST_KEY,
                "angle": cand["angle"],
                "content": cand["content"],
                "chars": len(cand["content"]),
            }
            if item["chars"] > MAX_CONTENT_CHARS:
                item["reason"] = ("%d chars exceeds the %d-char cap"
                                  % (item["chars"], MAX_CONTENT_CHARS))
                skipped.append(item)
                continue
            pending.append(item)

    return pending, skipped, already


def _post_id(response):
    if isinstance(response, dict):
        for key in ("id", "post_id", "postId"):
            if response.get(key):
                return str(response[key])
    return None


# The backend gates POST /posts behind an active subscription and answers a
# *machine-readable* 403 body — `{"error": "subscription_required"}` — precisely
# so clients can tell "your token is bad" apart from "your plan is". Both arrive
# as HTTP 403, and the remedies are opposite: re-authenticating does nothing for
# an unsubscribed user, it just loops them back to the same error.
SUBSCRIPTION_REQUIRED = "subscription_required"


class SyncAborted(Exception):
    """A run stopped early. Carries whatever had already been decided.

    AuthRejected and SubscriptionRequired are deliberately *siblings*, not
    parent and child: they are both 403s and catching them in the wrong order
    would silently give the user the wrong instruction.
    """

    def __init__(self, message, pushed, skipped, failed, already):
        super().__init__(message)
        self.pushed = pushed
        self.skipped = skipped
        self.failed = failed
        self.already = already


class AuthRejected(SyncAborted):
    """The server rejected our credentials; the rest was not attempted."""


class SubscriptionRequired(SyncAborted):
    """The credentials are fine — the account has no active plan."""


def _is_subscription_required(exc):
    return exc.status == 403 and SUBSCRIPTION_REQUIRED in str(exc.message or "").lower()


def sync(cwd, client=None, now=None):
    """Push every unsynced candidate. Returns (pushed, skipped, failed, already).

    Aborts the whole run on 401/403 rather than retrying every remaining post
    against credentials the server has already rejected — one clear "sign in
    again" beats N identical auth errors.
    """
    from .cloud_client import CloudApiError

    pending, skipped, already = plan(cwd)
    pushed, failed = [], []
    if not pending:
        return pushed, skipped, failed, already

    if client is None:
        from .cloud_client import CloudClient
        client = CloudClient()

    ledger = read_ledger(cwd)
    stamp = state.iso(now or state.now_utc())

    for item in pending:
        try:
            response = client.create_post(item["content"])
        except CloudApiError as exc:
            if _is_subscription_required(exc):
                failed.append(dict(item, reason=str(exc)))
                raise SubscriptionRequired(str(exc), pushed, skipped,
                                           failed, already) from exc
            if exc.status in (401, 403):
                failed.append(dict(item, reason=str(exc)))
                raise AuthRejected(str(exc), pushed, skipped,
                                   failed, already) from exc
            failed.append(dict(item, reason=str(exc)))
            continue

        entry = ledger["drafts"].setdefault(item["draft"], {})
        entry[item["key"]] = {"post_id": _post_id(response),
                              "synced_at": stamp}
        # Written per push, not once at the end: an interrupted run must not
        # re-upload what already landed.
        write_ledger(cwd, ledger)
        pushed.append(dict(item, post_id=_post_id(response)))

    return pushed, skipped, failed, already


def _describe(item):
    angle = (" — %s" % item["angle"]) if item.get("angle") else ""
    # Legacy drafts hold three candidates, so the letter is what tells them
    # apart in the listing; a current draft is one post and needs no label.
    label = ("Candidate %s" % item["key"]) if item.get("legacy") else "post"
    return "%s  %s%s (%d chars)" % (
        item["draft"], label, angle, item.get("chars", 0))


def cmd_sync(cwd, dry_run=False, client=None):
    """CLI entry point. Prints a plan or a result summary; never a post body.

    `client` is injectable for tests; the CLI never passes it.
    """
    if dry_run:
        pending, skipped, already = plan(cwd)
        if not pending and not skipped:
            print("Nothing to sync — %d post(s) already pushed." % already)
            return 0
        print("Would push %d post(s) to postcommit-cloud:" % len(pending))
        for item in pending:
            print("  + %s" % _describe(item))
        for item in skipped:
            print("  - %s: %s" % (item["draft"], item["reason"]))
        if already:
            print("Already synced: %d post(s)." % already)
        return 0

    try:
        pushed, skipped, failed, already = sync(cwd, client=client)
    except SubscriptionRequired:
        from . import cloud_config
        print("Nothing was pushed: postcommit-cloud needs an active subscription.",
              file=sys.stderr)
        print("Manage your plan at %s — signing in again will not help."
              % cloud_config.dashboard_url(), file=sys.stderr)
        return 1
    except AuthRejected as exc:
        print("Cloud rejected the credentials: %s" % exc, file=sys.stderr)
        print("Run /login (or `postcommit cloud login --browser`) and retry.",
              file=sys.stderr)
        return 1

    for item in pushed:
        print("  + %s" % _describe(item))
    for item in skipped:
        print("  - skipped %s: %s" % (item["draft"], item["reason"]))
    for item in failed:
        print("  ! failed %s [%s]: %s"
              % (item["draft"], item["key"], item["reason"]), file=sys.stderr)

    print("Pushed %d, skipped %d, failed %d, already synced %d."
          % (len(pushed), len(skipped), len(failed), already))
    return 1 if failed else 0
