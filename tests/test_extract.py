"""Tests for postcommit.extract — the deterministic work-bundle builder.

Covers window parsing, diff hygiene (secret masking + size cap), transcript
distillation, and end-to-end bundle assembly against real fixture repos.
"""

import base64
import json
import os
import tempfile
import unittest

from _support import commit, init_repo, run_git, write_transcript
from _support import extract as ex
from _support import state as st


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

    def test_redacts_env_file_by_extension(self):
        # `.env` files were not treated as sensitive before — only `secrets*` /
        # `credentials*` / key material. A plain prod.env leaked in full.
        diff = "\n".join([
            "diff --git a/config/prod.env b/config/prod.env",
            "+++ b/config/prod.env",
            "+DATABASE_URL=postgres://u:p@host/db",
        ])
        out = ex.mask_secrets(diff)
        self.assertIn("redacted — sensitive file", out)
        self.assertNotIn("postgres://u:p@host/db", out)


class ScrubText(unittest.TestCase):
    def test_masks_bearer_token(self):
        out = ex.scrub_text("curl -H 'Authorization: Bearer sk-live-abcdef123456' x")
        self.assertNotIn("sk-live-abcdef123456", out)
        self.assertIn("***", out)

    def test_masks_url_credentials(self):
        out = ex.scrub_text("git remote add o https://user:s3cretPass@github.com/a/b")
        self.assertNotIn("s3cretPass", out)

    def test_masks_inline_secret_assignment(self):
        out = ex.scrub_text("export DATABASE_PASSWORD=hunter2trustno1")
        self.assertNotIn("hunter2trustno1", out)

    def test_masks_aws_access_key(self):
        out = ex.scrub_text("id = AKIAIOSFODNN7EXAMPLE")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_leaves_ordinary_text_untouched(self):
        s = "a normal sentence about parsers and tokens of thought"
        self.assertEqual(ex.scrub_text(s), s)


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

    def test_scrubs_secrets_from_prompt_command_and_assistant_text(self):
        from _support import assistant_text, tool_use_msg, user_msg
        path = self._write([
            user_msg("use token=ghp_abcdefabcdefabcdef1234 to auth",
                     ts="2026-07-05T10:00:00Z"),
            tool_use_msg("Bash",
                         {"command": "curl -H 'Authorization: Bearer sk-live-zzzzzzzzzzzz' u"},
                         ts="2026-07-05T10:01:00Z"),
            assistant_text("the key is AKIAIOSFODNN7EXAMPLE now",
                           ts="2026-07-05T10:02:00Z"),
        ])
        text = "\n".join(ex.distill_session(path, None)["lines"])
        self.assertNotIn("ghp_abcdefabcdefabcdef1234", text)
        self.assertNotIn("sk-live-zzzzzzzzzzzz", text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", text)


class TranscriptDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _proj(self, records):
        d = os.path.join(self.tmp.name, "enc")
        os.makedirs(d)
        write_transcript(os.path.join(d, "s.jsonl"), records)
        return d

    def test_rejects_dir_belonging_to_a_different_cwd(self):
        # `.`->`-` folding makes foo.bar and foo-bar collide; the recorded cwd
        # is what disambiguates them.
        d = self._proj([{"type": "user", "cwd": "/Users/me/foo-bar",
                         "message": {"content": "x"}}])
        self.assertFalse(ex._dir_is_for_cwd(d, "/Users/me/foo.bar"))

    def test_accepts_matching_cwd(self):
        d = self._proj([{"type": "user", "cwd": "/Users/me/foo.bar",
                         "message": {"content": "x"}}])
        self.assertTrue(ex._dir_is_for_cwd(d, "/Users/me/foo.bar"))

    def test_accepts_when_no_cwd_recorded(self):
        d = self._proj([{"type": "user", "message": {"content": "x"}}])
        self.assertTrue(ex._dir_is_for_cwd(d, "/Users/me/foo.bar"))

    def test_transcript_files_empty_for_none_cutoff(self):
        # A None cutoff (empty git range) must not scope in every session.
        self.assertEqual(ex._transcript_files(self.tmp.name, None), [])


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


class CredentialBundleMasking(unittest.TestCase):
    """The dashboard's copy-token blob must never survive into a work bundle.

    It is base64(JSON) holding a long-lived refresh_token. Being one unbroken
    base64 run it carries no dots, so the JWT rule misses it — a user pasting it
    into the chat would otherwise land it in the transcript, and from there into
    a bundle, a draft, and potentially a published post.
    """

    @staticmethod
    def _bundle():
        payload = {
            "id_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1MSJ9.sig",
            "refresh_token": "AMf-vBxREFRESHtokenLONGLIVEDvalue1234567890",
            "api_key": "AIzaSyExampleFirebaseWebApiKey0000000000",
            "expires_at": 1785040000,
        }
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def test_bare_bundle_is_masked(self):
        blob = self._bundle()
        self.assertNotIn(blob, ex.scrub_text(blob))

    def test_bundle_after_prose_is_masked(self):
        blob = self._bundle()
        line = "here is my token %s thanks" % blob
        out = ex.scrub_text(line)
        self.assertNotIn(blob, out)
        self.assertIn("here is my token", out)

    def test_firebase_api_key_is_masked(self):
        key = "AIzaSyExampleFirebaseWebApiKey0000000000"
        self.assertNotIn(key, ex.scrub_text(key))

    def test_jwt_still_masked_whole_not_just_its_header(self):
        """Alternation order matters: the dotted JWT rule must win at `eyJ`."""
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzNDUifQ.signaturehere"
        out = ex.scrub_text(jwt)
        self.assertEqual(out, "***")

    def test_ordinary_content_is_not_masked(self):
        for benign in (
            "eyJhIjoxfQ==",                              # short base64
            "The eyJ prefix shows up in prose",
            "a6e7d34a57c8c2881d0e408167c6fa84e39aef7f",  # git sha
            "result = compute(alpha, beta)",
        ):
            self.assertEqual(ex.scrub_text(benign), benign, benign)


class SessionSlicing(unittest.TestCase):
    """Session lines belong to the commit they happened *before*."""

    def _session(self, pairs):
        return {"id": "abc1234f",
                "entries": [(st.parse_iso(ts), text) for ts, text in pairs]}

    def test_lines_land_in_the_half_open_interval(self):
        s = self._session([
            ("2026-07-05T10:00:00Z", "> before"),
            ("2026-07-05T11:00:00Z", "> boundary"),
            ("2026-07-05T12:00:00Z", "> after"),
        ])
        start = st.parse_iso("2026-07-05T10:00:00Z")
        end = st.parse_iso("2026-07-05T11:00:00Z")
        # (start, end] — the line *at* start belongs to the previous slice.
        self.assertEqual(["> boundary"],
                         ex.session_lines_between([s], start, end))

    def test_open_bounds_take_everything_on_that_side(self):
        s = self._session([("2026-07-05T10:00:00Z", "> a"),
                           ("2026-07-05T12:00:00Z", "> b")])
        self.assertEqual(["> a", "> b"],
                         ex.session_lines_between([s], None, None))

    def test_untimestamped_lines_are_dropped_not_guessed(self):
        s = {"id": "x", "entries": [(None, "> orphan")]}
        self.assertEqual([], ex.session_lines_between([s], None, None))

    def test_lines_from_several_sessions_come_back_in_time_order(self):
        a = self._session([("2026-07-05T10:00:00Z", "> first")])
        b = self._session([("2026-07-05T09:00:00Z", "> earlier")])
        self.assertEqual(["> earlier", "> first"],
                         ex.session_lines_between([a, b], None, None))


class PerCommitBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))

    def test_one_slice_per_commit_oldest_first(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "two\n", "feat: add b")
        commit(self.repo, "c.txt", "three\n", "fix: fix c")
        bundle = ex.build_per_commit_bundle("HEAD~2..HEAD", self.repo)
        self.assertIn("### Slice", bundle)
        self.assertEqual(2, bundle.count("### Slice "))
        self.assertLess(bundle.index("feat: add b"), bundle.index("fix: fix c"))

    def test_each_slice_carries_its_own_diff(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "only-in-b\n", "feat: add b")
        commit(self.repo, "c.txt", "only-in-c\n", "fix: fix c")
        bundle = ex.build_per_commit_bundle("HEAD~2..HEAD", self.repo)
        b_slice, c_slice = bundle.split("### Slice ")[1:3]
        self.assertIn("only-in-b", b_slice)
        self.assertNotIn("only-in-c", b_slice)
        self.assertIn("only-in-c", c_slice)

    def test_merge_commit_is_filtered_with_a_reason(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        run_git(self.repo, "checkout", "-q", "-b", "side")
        commit(self.repo, "side.txt", "side\n", "feat: side work")
        run_git(self.repo, "checkout", "-q", "-")
        commit(self.repo, "main.txt", "main\n", "feat: main work")
        run_git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge branch 'side'",
                "side")
        bundle = ex.build_per_commit_bundle("1d", self.repo)
        self.assertIn("Merge branch 'side' — merge commit", bundle)
        slices = bundle.split("## Work slices")[1]
        self.assertNotIn("Merge branch", slices)
        self.assertIn("feat: side work", slices)   # its parents still get one

    def test_release_commit_is_filtered(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "v.txt", "0.10.0\n", "chore(release): 0.10.0")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        self.assertIn("chore(release): 0.10.0 — release/version bump", bundle)
        self.assertIn("(no commits with a story in this window)", bundle)

    def test_ordinary_commits_are_not_filtered(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "two\n", "chore: tidy the makefile")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        self.assertIn("nothing filtered", bundle)
        self.assertIn("chore: tidy the makefile", bundle)

    def test_secrets_are_masked_inside_a_slice(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "conf.py", 'api_key = "sk-abcdef0123456789"\n',
               "feat: add config")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        self.assertNotIn("sk-abcdef0123456789", bundle)
        self.assertIn("api_key", bundle)

    def test_per_commit_diff_is_capped(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "big.txt", ("x" * 60 + "\n") * 500, "feat: big file")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        self.assertIn("lines elided]", bundle)
        self.assertLess(len(bundle), 2 * ex.PER_COMMIT_DIFF_CAP)

    def test_every_slice_keeps_a_quotable_diff(self):
        """The budget is shared, not raced for — no slice ends up empty.

        The old first-come-first-served spend gave the oldest commits the whole
        budget and left the newest ones with metadata only, which is precisely
        the work most worth posting about.
        """
        commit(self.repo, "a.txt", "one\n", "chore: init")
        for i in range(20):
            commit(self.repo, "f%d.txt" % i, ("y" * 60 + "\n") * 200,
                   "feat: change %d" % i)
        bundle = ex.build_per_commit_bundle("HEAD~20..HEAD", self.repo)
        slices = bundle.split("### Slice ")[1:]
        self.assertEqual(20, len(slices))
        for s in slices:
            self.assertIn("```diff", s)
            body = s.split("```diff", 1)[1].split("```", 1)[0]
            self.assertIn("+", body)
        self.assertNotIn("diff omitted", bundle)

    def test_the_newest_slice_is_as_quotable_as_the_oldest(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        for i in range(12):
            commit(self.repo, "f%d.txt" % i, ("z" * 60 + "\n") * 200,
                   "feat: change %d" % i)
        bundle = ex.build_per_commit_bundle("HEAD~12..HEAD", self.repo)
        slices = bundle.split("### Slice ")[1:]
        first = slices[0].split("```diff", 1)[1].split("```", 1)[0]
        last = slices[-1].split("```diff", 1)[1].split("```", 1)[0]
        # Same share, so same order of magnitude — not one full patch and one stub.
        self.assertGreater(len(last), len(first) // 2)

    def test_share_never_falls_below_the_floor(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        for i in range(40):
            commit(self.repo, "f%d.txt" % i, ("w" * 60 + "\n") * 200,
                   "feat: change %d" % i)
        bundle = ex.build_per_commit_bundle("HEAD~40..HEAD", self.repo)
        slices = bundle.split("### Slice ")[1:]
        self.assertEqual(40, len(slices))
        for s in slices:
            body = s.split("```diff", 1)[1].split("```", 1)[0]
            self.assertGreater(len(body), ex.MIN_SLICE_DIFF_CHARS // 2)

    def test_a_lone_commit_still_gets_the_full_per_commit_cap(self):
        """Sharing must not shrink the small case it was never about."""
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "big.txt", ("x" * 60 + "\n") * 500, "feat: big file")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        body = bundle.split("```diff", 1)[1].split("```", 1)[0]
        self.assertGreater(len(body), ex.MIN_SLICE_DIFF_CHARS * 2)

    def test_uncommitted_work_is_its_own_slice(self):
        commit(self.repo, "a.txt", "one\n", "chore: init")
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("one\ndirty\n")
        bundle = ex.build_per_commit_bundle("HEAD..HEAD", self.repo)
        self.assertIn("### Slice working — uncommitted changes", bundle)
        self.assertIn("dirty", bundle)

    def test_empty_when_no_work(self):
        commit(self.repo, "a.txt", "one\n", "first")
        bundle = ex.build_per_commit_bundle("HEAD..HEAD", self.repo)
        self.assertIn("No meaningful work in window.", bundle)

    def test_grouping_is_left_to_the_model(self):
        """The bundle must ask for grouping, not perform it."""
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "two\n", "feat: add b")
        bundle = ex.build_per_commit_bundle("HEAD~1..HEAD", self.repo)
        self.assertIn("## Grouping + candidate signal", bundle)
        self.assertIn("work items", bundle)

    def test_not_a_repo_raises(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        with self.assertRaises(ex.NotARepoError):
            ex.build_per_commit_bundle("1d", plain)
