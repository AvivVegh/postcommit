"""Tests for postcommit.cloud_sync — pushing draft candidates to the cloud.

No network: a stub client records every create_post call. The emphasis is on the
two properties that make a bulk uploader safe to re-run — idempotency via the
ledger, and `plan()` doing no I/O — plus the guarantee that reviewer notes and
candidate labels never reach the wire.
"""

import os
import shutil
import tempfile
import unittest

from _support import state

from postcommit import cloud_sync
from postcommit.cloud_client import CloudApiError

DRAFT = """# LinkedIn draft candidates — 2026-07-26

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

    def write_draft(self, name, body=DRAFT):
        path = os.path.join(state.drafts_dir(self.cwd), name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


class Plan(SyncBase):
    def test_lists_every_candidate(self):
        self.write_draft("2026-07-26T09-00-00Z.md")
        pending, skipped, already = cloud_sync.plan(self.cwd)
        self.assertEqual(["A", "B"], [p["letter"] for p in pending])
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
        self.assertEqual("no candidate blocks found", skipped[0]["reason"])

    def test_missing_drafts_dir_is_not_an_error(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertEqual(([], [], 0), cloud_sync.plan(empty))


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
