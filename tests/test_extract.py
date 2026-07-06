"""Tests for postcommit.extract — the deterministic work-bundle builder.

Covers window parsing, diff hygiene (secret masking + size cap), transcript
distillation, and end-to-end bundle assembly against real fixture repos.
"""

import os
import tempfile
import unittest

from _support import commit, init_repo, write_transcript
from _support import extract as ex


class ParseWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))
        commit(self.repo, "a.txt", "one\n", "first")

    def test_duration_sets_cutoff_in_the_past(self):
        from _support import state as st
        win = ex.parse_window("2h", self.repo)
        self.assertIsNotNone(win["cutoff"])
        self.assertLess(win["cutoff"], st.now_utc())
        self.assertEqual(win["log_args"][0], "--since")

    def test_today_is_accepted(self):
        win = ex.parse_window("today", self.repo)
        self.assertIsNotNone(win["cutoff"])

    def test_since_date_is_accepted(self):
        win = ex.parse_window("since=2026-07-01", self.repo)
        self.assertIsNotNone(win["cutoff"])

    def test_explicit_range_passes_through(self):
        win = ex.parse_window("HEAD~1..HEAD", self.repo)
        self.assertEqual(win["diff_range"], "HEAD~1..HEAD")
        self.assertEqual(win["log_args"], ["HEAD~1..HEAD"])

    def test_bad_date_raises_window_error(self):
        with self.assertRaises(ex.WindowError):
            ex.parse_window("since=not-a-date", self.repo)

    def test_garbage_raises_window_error(self):
        with self.assertRaises(ex.WindowError):
            ex.parse_window("wat", self.repo)

    def test_empty_raises_window_error(self):
        with self.assertRaises(ex.WindowError):
            ex.parse_window("", self.repo)


class MaskSecrets(unittest.TestCase):
    def test_masks_assignment_of_secret_key(self):
        diff = "+API_KEY=sk-supersecretvalue1234"
        out = ex.mask_secrets(diff)
        self.assertNotIn("supersecret", out)
        self.assertIn("***", out)

    def test_masks_token_colon_form(self):
        out = ex.mask_secrets('+  "auth_token": "abcdef123456"')
        self.assertNotIn("abcdef123456", out)

    def test_redacts_body_of_sensitive_file(self):
        diff = "\n".join([
            "diff --git a/secrets.env b/secrets.env",
            "+++ b/secrets.env",
            "+DATABASE_URL=postgres://u:p@host/db",
        ])
        out = ex.mask_secrets(diff)
        self.assertIn("redacted — sensitive file", out)
        self.assertNotIn("postgres://u:p@host/db", out)

    def test_leaves_ordinary_lines_untouched(self):
        diff = "+def add(a, b):\n+    return a + b"
        self.assertEqual(ex.mask_secrets(diff), diff)


class CapDiff(unittest.TestCase):
    def test_short_diff_is_unchanged(self):
        diff = "diff --git a/x b/x\n+hello"
        self.assertEqual(ex.cap_diff(diff, limit=1000), diff)

    def test_long_diff_is_capped_but_keeps_structure(self):
        body = "\n".join("+line %d" % i for i in range(5000))
        diff = "diff --git a/x b/x\n@@ -0,0 +1 @@\n" + body
        out = ex.cap_diff(diff, limit=500)
        self.assertIn("diff --git a/x b/x", out)  # structural line survives
        self.assertIn("@@ -0,0 +1 @@", out)        # hunk header survives
        self.assertIn("lines elided", out)         # body got elided
        self.assertLess(len(out), len(diff))


class DistillSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, records):
        return write_transcript(os.path.join(self.tmp.name, "abc1234f.jsonl"), records)

    def test_keeps_prompts_and_tool_uses_skips_meta_and_sidechain(self):
        from _support import tool_use_msg, user_msg
        path = self._write([
            user_msg("fix the parser crash", ts="2026-07-05T10:00:00Z"),
            {"type": "user", "message": {"content": "<system-reminder>noise"},
             "timestamp": "2026-07-05T10:00:01Z"},
            {"isSidechain": True, "type": "user",
             "message": {"content": "subagent noise"},
             "timestamp": "2026-07-05T10:00:02Z"},
            tool_use_msg("Bash", {"command": "pytest -q"}, ts="2026-07-05T10:01:00Z"),
            tool_use_msg("Edit", {"file_path": "src/parser.py"}, ts="2026-07-05T10:02:00Z"),
        ])
        block = ex.distill_session(path, None)
        self.assertIsNotNone(block)
        text = "\n".join(block["lines"])
        self.assertIn("> fix the parser crash", text)
        self.assertIn("Bash: pytest -q", text)
        self.assertIn("Edit: src/parser.py", text)
        self.assertNotIn("system-reminder", text)
        self.assertNotIn("subagent noise", text)
        self.assertEqual(block["id"], "abc1234f")

    def test_returns_none_when_nothing_kept(self):
        from _support import user_msg
        path = self._write([user_msg("<command-name>/post</command-name>")])
        self.assertIsNone(ex.distill_session(path, None))

    def test_never_leaks_write_file_contents(self):
        from _support import tool_use_msg
        path = self._write([
            tool_use_msg("Write", {"file_path": "x.py", "content": "SECRET_BODY"},
                         ts="2026-07-05T10:00:00Z"),
        ])
        block = ex.distill_session(path, None)
        self.assertNotIn("SECRET_BODY", "\n".join(block["lines"]))


class BuildBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))

    def test_empty_when_no_work(self):
        # Clean tree + an empty commit range + no transcripts -> nothing to say.
        commit(self.repo, "a.txt", "one\n", "first")
        bundle = ex.build_bundle("HEAD..HEAD", self.repo)
        self.assertIn("No meaningful work in window.", bundle)

    def test_reports_commits_and_diff(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "two\n" * 5, "feat: add b")
        bundle = ex.build_bundle("HEAD~1..HEAD", self.repo)
        self.assertIn("## Repo", bundle)
        self.assertIn("commits in window: 1", bundle)
        self.assertIn("feat: add b", bundle)
        self.assertIn("```diff", bundle)
        self.assertIn("## Candidate signal", bundle)

    def test_uncommitted_shows_in_bundle(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        with open(os.path.join(self.repo, "c.txt"), "w") as fh:
            fh.write("dirty\n")
        bundle = ex.build_bundle("HEAD..HEAD", self.repo)
        self.assertIn("c.txt", bundle)  # untracked file appears under Uncommitted

    def test_not_a_repo_raises(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        with self.assertRaises(ex.NotARepoError):
            ex.build_bundle("1d", plain)


if __name__ == "__main__":
    unittest.main()
