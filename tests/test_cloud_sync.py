"""Tests for postcommit.cloud_sync — pushing draft posts to the cloud.

No network: a stub client records every create_post call. The emphasis is on the
two properties that make a bulk uploader safe to re-run — idempotency via the
ledger, and `plan()` doing no I/O — plus the guarantee that reviewer notes and
post labels never reach the wire.

Most of the abort/failure cases run against a *legacy* two-candidate draft on
purpose: those files are still on users' disks, and they are also the cheapest
way to exercise "second push in the same file" behaviour. `PerItemDrafts` covers
the current one-post-per-file shape and the sha-keyed ledger.
"""

import os
import shutil
import tempfile
import unittest

from _support import state

from postcommit import cloud_sync
from postcommit.cloud_client import CloudApiError

POST_DRAFT = """# LinkedIn draft — 2026-07-26

- window: `1d`
- item: `a1b2c3`

---

### Post — the cost of the obvious approach

one post body
"""

LEGACY_DRAFT = """# LinkedIn draft candidates — 2026-07-26

- window: `1d`

---

### Candidate A — story

post A body

— why this angle: reviewer note A.

---

### Candidate B — lesson

post B body

— why this angle: reviewer note B.
"""


class _StubClient:
    def __init__(self, fail_with=None):
        self.calls = []
        self.fail_with = fail_with

    def create_post(self, content, scheduled_at=None):
        self.calls.append(content)
        if self.fail_with is not None:
            raise self.fail_with
        return {"id": "post-%d" % len(self.calls)}


class SyncBase(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cwd, True)
        os.makedirs(state.drafts_dir(self.cwd))

    def write_draft(self, name, body=LEGACY_DRAFT):
        path = os.path.join(state.drafts_dir(self.cwd), name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


class Plan(SyncBase):
    def test_lists_every_candidate(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        pending, skipped, already = cloud_sync.plan(self.cwd)
        self.assertEqual(["A", "B"], [p["key"] for p in pending])
        self.assertEqual([], skipped)
        self.assertEqual(0, already)

    def test_drafts_ordered_oldest_first(self):
        self.write_draft("2026-07-26T12-00-00Z.md")
        self.write_draft("2026-07-26T09-00-00Z.md")
        pending, _, _ = cloud_sync.plan(self.cwd)
        self.assertEqual(["2026-07-26T09-00-00Z.md"] * 2
                         + ["2026-07-26T12-00-00Z.md"] * 2,
                         [p["draft"] for p in pending])

    def test_oversized_candidate_skipped_with_reason(self):
        body = ("### Candidate A — x\n\n" + "z" * 3001
                + "\n\n— why this angle: y\n")
        self.write_draft("2026-07-26T09-00-00Z.md", body)
        pending, skipped, _ = cloud_sync.plan(self.cwd)
        self.assertEqual([], pending)
        self.assertIn("exceeds the 3000-char cap", skipped[0]["reason"])

    def test_file_without_candidates_skipped(self):
        self.write_draft("2026-07-26T09-00-00Z.md", "just a note\n")
        pending, skipped, _ = cloud_sync.plan(self.cwd)
        self.assertEqual([], pending)
        self.assertEqual("no post blocks found", skipped[0]["reason"])

    def test_missing_drafts_dir_is_not_an_error(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertEqual(([], [], 0), cloud_sync.plan(empty))


class PerItemDrafts(SyncBase):
    """One post per work item, keyed in the ledger by the item's short sha."""

    NAME = "2026-07-26T09-00-00Z-a1b2c3.md"

    def test_one_pending_post_keyed_by_the_filename_sha(self):
        self.write_draft(self.NAME, POST_DRAFT)
        pending, skipped, already = cloud_sync.plan(self.cwd)
        self.assertEqual(["a1b2c3"], [p["key"] for p in pending])
        self.assertEqual([], skipped)
        self.assertFalse(pending[0]["legacy"])

    def test_ledger_records_under_the_sha(self):
        self.write_draft(self.NAME, POST_DRAFT)
        cloud_sync.sync(self.cwd, client=_StubClient())
        entry = cloud_sync.read_ledger(self.cwd)["drafts"][self.NAME]
        self.assertEqual(["a1b2c3"], list(entry))
        self.assertEqual("post-1", entry["a1b2c3"]["post_id"])

    def test_rerun_pushes_nothing_new(self):
        self.write_draft(self.NAME, POST_DRAFT)
        cloud_sync.sync(self.cwd, client=_StubClient())
        client = _StubClient()
        _, _, _, already = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual([], client.calls)
        self.assertEqual(1, already)

    def test_body_goes_over_the_wire_without_the_label(self):
        self.write_draft(self.NAME, POST_DRAFT)
        client = _StubClient()
        cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(["one post body"], client.calls)

    def test_a_draft_with_no_sha_suffix_still_syncs(self):
        """Hand-named or hand-written files must not be unsyncable."""
        self.write_draft("notes.md", POST_DRAFT)
        pending, _, _ = cloud_sync.plan(self.cwd)
        self.assertEqual(["POST"], [p["key"] for p in pending])

    def test_legacy_and_new_drafts_coexist(self):
        self.write_draft("2026-07-20T09-00-00Z.md")            # legacy A/B
        self.write_draft(self.NAME, POST_DRAFT)                # new single post
        client = _StubClient()
        pushed, _, _, _ = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(3, len(client.calls))
        ledger = cloud_sync.read_ledger(self.cwd)["drafts"]
        self.assertEqual(["A", "B"], sorted(ledger["2026-07-20T09-00-00Z.md"]))
        self.assertEqual(["a1b2c3"], list(ledger[self.NAME]))
        self.assertEqual({"A", "B", "a1b2c3"}, {p["key"] for p in pushed})

    def test_same_item_under_a_new_filename_is_not_re_pushed(self):
        """The bug the flat item index exists for.

        Every /post run stamps the draft filename with its own timestamp, so a
        second run over an overlapping window writes a *different* file for the
        *same* work item. Keying only on the filename missed that and pushed the
        item twice.
        """
        self.write_draft("2026-07-26T09-00-00Z-a1b2c3.md", POST_DRAFT)
        cloud_sync.sync(self.cwd, client=_StubClient())

        rerun = POST_DRAFT.replace("one post body", "reworded post body")
        self.write_draft("2026-07-27T09-00-00Z-a1b2c3.md", rerun)
        client = _StubClient()
        _, _, _, already = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual([], client.calls)
        # Both files are now covered: the first by its own per-file entry, the
        # second by the flat item index.
        self.assertEqual(2, already)

    def test_two_unsynced_files_for_one_item_push_once(self):
        """Two /post runs, then a single sync — the ledger has seen neither."""
        self.write_draft("2026-07-26T09-00-00Z-a1b2c3.md", POST_DRAFT)
        self.write_draft("2026-07-27T09-00-00Z-a1b2c3.md",
                         POST_DRAFT.replace("one post", "second one"))
        client = _StubClient()
        cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(["one post body"], client.calls)

    def test_different_items_are_unaffected(self):
        self.write_draft("2026-07-26T09-00-00Z-a1b2c3.md", POST_DRAFT)
        self.write_draft("2026-07-26T09-01-00Z-d4e5f6.md", POST_DRAFT)
        client = _StubClient()
        cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(2, len(client.calls))
        self.assertEqual({"a1b2c3", "d4e5f6"},
                         set(cloud_sync.read_ledger(self.cwd)["items"]))

    def test_legacy_letters_stay_scoped_to_their_file(self):
        """A/B mean something different in every file — never flat-indexed."""
        self.write_draft("2026-07-20T09-00-00Z.md")
        self.write_draft("2026-07-21T09-00-00Z.md")
        client = _StubClient()
        cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(4, len(client.calls))
        self.assertEqual({}, cloud_sync.read_ledger(self.cwd)["items"])

    def test_suffixless_drafts_do_not_collide(self):
        """The POST fallback repeats across files, so it stays file-scoped too."""
        self.write_draft("notes.md", POST_DRAFT)
        self.write_draft("other-notes.md", POST_DRAFT)
        client = _StubClient()
        cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(2, len(client.calls))
        self.assertEqual({}, cloud_sync.read_ledger(self.cwd)["items"])

    def test_a_v1_ledger_is_backfilled_and_still_blocks(self):
        cloud_sync.write_ledger(self.cwd, {
            "version": 1,
            "drafts": {"2026-07-26T09-00-00Z-a1b2c3.md": {
                "a1b2c3": {"post_id": "p1", "synced_at": "then"}}},
        })
        self.write_draft("2026-07-27T09-00-00Z-a1b2c3.md", POST_DRAFT)
        pending, _, already = cloud_sync.plan(self.cwd)
        self.assertEqual([], pending)
        self.assertEqual(1, already)
        ledger = cloud_sync.read_ledger(self.cwd)
        self.assertEqual(cloud_sync.LEDGER_VERSION, ledger["version"])
        self.assertEqual("p1", ledger["items"]["a1b2c3"]["post_id"])

    def test_v1_backfill_ignores_legacy_letters(self):
        cloud_sync.write_ledger(self.cwd, {
            "version": 1,
            "drafts": {"2026-07-20T09-00-00Z.md": {
                "A": {"post_id": "p1", "synced_at": "then"},
                "B": {"post_id": "p2", "synced_at": "then"}}},
        })
        self.assertEqual({}, cloud_sync.read_ledger(self.cwd)["items"])

    def test_a_pre_split_ledger_still_blocks_its_draft(self):
        """Letters written before the split must not be re-pushed."""
        self.write_draft("2026-07-20T09-00-00Z.md")
        cloud_sync.write_ledger(self.cwd, {
            "version": 1,
            "drafts": {"2026-07-20T09-00-00Z.md": {
                "A": {"post_id": "p1", "synced_at": "then"},
                "B": {"post_id": "p2", "synced_at": "then"}}},
        })
        pending, _, already = cloud_sync.plan(self.cwd)
        self.assertEqual([], pending)
        self.assertEqual(2, already)


class Describe(SyncBase):
    def test_new_draft_needs_no_candidate_label(self):
        line = cloud_sync._describe(
            {"draft": "d.md", "key": "a1b2c3", "angle": "the surprise",
             "chars": 12})
        self.assertIn("post — the surprise", line)
        self.assertNotIn("Candidate", line)

    def test_legacy_draft_keeps_its_letter(self):
        line = cloud_sync._describe(
            {"draft": "d.md", "key": "B", "legacy": True, "angle": "lesson",
             "chars": 12})
        self.assertIn("Candidate B — lesson", line)


class Sync(SyncBase):
    def test_pushes_body_without_label_or_reviewer_note(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        client = _StubClient()
        pushed, _, failed, _ = cloud_sync.sync(self.cwd, client=client)

        self.assertEqual(["post A body", "post B body"], client.calls)
        self.assertEqual(2, len(pushed))
        self.assertEqual([], failed)
        for sent in client.calls:
            self.assertNotIn("why this angle", sent)
            self.assertNotIn("Candidate", sent)

    def test_rerun_pushes_nothing_new(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        cloud_sync.sync(self.cwd, client=_StubClient())

        second = _StubClient()
        pushed, _, _, already = cloud_sync.sync(self.cwd, client=second)
        self.assertEqual([], second.calls)
        self.assertEqual([], pushed)
        self.assertEqual(2, already)

    def test_new_draft_syncs_while_old_one_stays_put(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        cloud_sync.sync(self.cwd, client=_StubClient())

        self.write_draft("2026-07-26T18-00-00Z.md")
        client = _StubClient()
        pushed, _, _, already = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(2, len(client.calls))
        self.assertEqual({"2026-07-26T18-00-00Z.md"},
                         {p["draft"] for p in pushed})
        self.assertEqual(2, already)

    def test_ledger_records_post_ids(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        cloud_sync.sync(self.cwd, client=_StubClient())
        ledger = cloud_sync.read_ledger(self.cwd)
        entry = ledger["drafts"]["2026-07-26T09-00-00Z.md"]
        self.assertEqual("post-1", entry["A"]["post_id"])
        self.assertEqual("post-2", entry["B"]["post_id"])
        self.assertTrue(entry["A"]["synced_at"])

    def test_ledger_lands_under_the_self_ignoring_dir(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        cloud_sync.sync(self.cwd, client=_StubClient())
        self.assertTrue(os.path.exists(state.synced_path(self.cwd)))
        self.assertTrue(os.path.exists(
            os.path.join(state.repo_dir(self.cwd), ".gitignore")))

    def test_non_auth_failure_records_and_continues(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        client = _StubClient(fail_with=CloudApiError(500, "boom"))
        pushed, _, failed, _ = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual([], pushed)
        self.assertEqual(2, len(failed))       # both attempted, neither aborted
        self.assertEqual(2, len(client.calls))

    def test_failed_push_is_retried_next_run(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        cloud_sync.sync(self.cwd, client=_StubClient(
            fail_with=CloudApiError(500, "boom")))
        client = _StubClient()
        pushed, _, _, already = cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(2, len(pushed))
        self.assertEqual(0, already)

    def test_auth_rejection_aborts_the_run(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        client = _StubClient(fail_with=CloudApiError(401, "nope"))
        with self.assertRaises(cloud_sync.AuthRejected):
            cloud_sync.sync(self.cwd, client=client)
        # Stopped after the first rejection instead of retrying the second.
        self.assertEqual(1, len(client.calls))

    def test_subscription_403_is_not_an_auth_rejection(self):
        """The backend gates POST /posts on an active plan and says so in the
        403 body. Re-authenticating cannot fix that, so it must not be reported
        as rejected credentials."""
        self.write_draft("2026-07-26T09-00-00Z.md")
        client = _StubClient(
            fail_with=CloudApiError(403, "subscription_required"))
        with self.assertRaises(cloud_sync.SubscriptionRequired):
            cloud_sync.sync(self.cwd, client=client)
        self.assertEqual(1, len(client.calls))

    def test_plain_403_is_still_an_auth_rejection(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        client = _StubClient(fail_with=CloudApiError(403, "Access denied"))
        with self.assertRaises(cloud_sync.AuthRejected):
            cloud_sync.sync(self.cwd, client=client)

    def test_the_two_403s_do_not_catch_each_other(self):
        """Siblings, not parent/child — catching one must never swallow the other."""
        self.assertFalse(issubclass(cloud_sync.AuthRejected,
                                    cloud_sync.SubscriptionRequired))
        self.assertFalse(issubclass(cloud_sync.SubscriptionRequired,
                                    cloud_sync.AuthRejected))

    def test_nothing_pending_never_builds_a_client(self):
        """No drafts must mean no CloudClient(), so it works signed-out."""
        self.assertEqual(([], [], [], 0), cloud_sync.sync(self.cwd))


class Guidance(SyncBase):
    """cmd_sync must give the remedy that actually matches the failure."""

    def _run(self, error):
        import contextlib
        import io
        self.write_draft("2026-07-26T09-00-00Z.md")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cloud_sync.cmd_sync(
                self.cwd, client=_StubClient(fail_with=error))
        return rc, err.getvalue()

    def test_subscription_403_points_at_billing_not_login(self):
        rc, err = self._run(CloudApiError(403, "subscription_required"))
        self.assertEqual(1, rc)
        self.assertIn("subscription", err.lower())
        self.assertNotIn("/login", err)

    def test_auth_403_points_at_login(self):
        rc, err = self._run(CloudApiError(403, "Access denied"))
        self.assertEqual(1, rc)
        self.assertIn("/login", err)


class DryRun(SyncBase):
    def test_dry_run_makes_no_calls_and_writes_no_ledger(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        rc = cloud_sync.cmd_sync(self.cwd, dry_run=True)
        self.assertEqual(0, rc)
        self.assertFalse(os.path.exists(state.synced_path(self.cwd)))


if __name__ == "__main__":
    unittest.main()
