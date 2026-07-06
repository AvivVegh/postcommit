"""Unit + CLI tests for hooks/postcommit_state.py — the shared state layer."""

import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone

from _support import init_repo, commit, state as st


class TimeHelpers(unittest.TestCase):
    def test_iso_formats_with_trailing_z(self):
        dt = datetime(2026, 7, 5, 17, 6, 30, tzinfo=timezone.utc)
        self.assertEqual(st.iso(dt), "2026-07-05T17:06:30Z")

    def test_iso_normalizes_to_utc(self):
        # a non-UTC aware datetime is converted before formatting
        from datetime import timedelta
        est = timezone(timedelta(hours=-5))
        dt = datetime(2026, 7, 5, 12, 6, 30, tzinfo=est)
        self.assertEqual(st.iso(dt), "2026-07-05T17:06:30Z")

    def test_parse_iso_roundtrips(self):
        dt = datetime(2026, 7, 5, 17, 6, 30, tzinfo=timezone.utc)
        self.assertEqual(st.parse_iso(st.iso(dt)), dt)

    def test_parse_iso_handles_none_and_garbage(self):
        self.assertIsNone(st.parse_iso(None))
        self.assertIsNone(st.parse_iso(""))
        self.assertIsNone(st.parse_iso("not-a-date"))

    def test_parse_iso_accepts_plain_offset(self):
        self.assertIsNotNone(st.parse_iso("2026-07-05T17:06:30+00:00"))


class JsonIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_write_then_read_roundtrip(self):
        path = os.path.join(self.tmp.name, "nested", "dir", "data.json")
        st.write_json(path, {"b": 1, "a": 2})
        self.assertEqual(st.read_json(path, None), {"b": 1, "a": 2})

    def test_write_json_creates_dirs_and_is_sorted(self):
        path = os.path.join(self.tmp.name, "deep", "data.json")
        st.write_json(path, {"z": 1, "a": 2})
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.endswith("\n"))
        self.assertLess(text.index('"a"'), text.index('"z"'))  # sort_keys

    def test_write_json_leaves_no_temp_files(self):
        path = os.path.join(self.tmp.name, "data.json")
        st.write_json(path, {"x": 1})
        leftovers = [n for n in os.listdir(self.tmp.name) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_read_json_missing_returns_default(self):
        sentinel = {"default": True}
        self.assertEqual(
            st.read_json(os.path.join(self.tmp.name, "nope.json"), sentinel),
            sentinel,
        )

    def test_read_json_corrupt_returns_default(self):
        path = os.path.join(self.tmp.name, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        self.assertIsNone(st.read_json(path, None))


class Watermark(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_defaults_when_absent(self):
        wm = st.read_watermark(self.tmp.name)
        self.assertEqual(wm, st.default_watermark())

    def test_merges_partial_state_over_defaults(self):
        st.write_json(st.watermark_path(self.tmp.name), {"last_posted_head": "abc"})
        wm = st.read_watermark(self.tmp.name)
        self.assertEqual(wm["last_posted_head"], "abc")
        self.assertIsNone(wm["snooze_until"])  # untouched default preserved

    def test_processed_sessions_bounded_to_200(self):
        many = [f"s{i}" for i in range(250)]
        st.write_json(st.watermark_path(self.tmp.name), {"processed_sessions": many})
        wm = st.read_watermark(self.tmp.name)
        self.assertEqual(len(wm["processed_sessions"]), 200)
        self.assertEqual(wm["processed_sessions"][0], "s50")  # keeps the newest

    def test_non_list_processed_sessions_coerced(self):
        st.write_json(st.watermark_path(self.tmp.name), {"processed_sessions": "oops"})
        wm = st.read_watermark(self.tmp.name)
        self.assertEqual(wm["processed_sessions"], [])


class GitHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))
        self.first = commit(self.repo, "a.txt", "one\n", "first")
        self.second = commit(self.repo, "b.txt", "two\n", "second")

    def test_is_git_repo(self):
        self.assertTrue(st.is_git_repo(self.repo))
        self.assertFalse(st.is_git_repo(self.tmp.name))  # parent isn't a repo

    def test_git_head_matches_rev_parse(self):
        self.assertEqual(st.git_head(self.repo), self.second)

    def test_is_ancestor(self):
        self.assertTrue(st.is_ancestor(self.repo, self.first))
        self.assertFalse(st.is_ancestor(self.repo, None))
        self.assertFalse(st.is_ancestor(self.repo, "0" * 40))

    def test_git_returns_none_on_failure(self):
        self.assertIsNone(st.git(self.repo, "not-a-real-subcommand"))


class Cli(unittest.TestCase):
    """Drive the CLI verbs against a real fixture repo via cwd override."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))
        self.head = commit(self.repo, "a.txt", "one\n", "first")
        self._cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self._cwd)

    @staticmethod
    def main(argv):
        # main() prints to stdout; swallow it so test output stays clean.
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return st.main(argv)

    def _wm(self):
        return st.read_json(st.watermark_path(self.repo), {})

    def test_snooze_sets_future_until(self):
        rc = self.main(["snooze", "2"])
        self.assertEqual(rc, 0)
        until = st.parse_iso(self._wm()["snooze_until"])
        self.assertGreater(until, st.now_utc())

    def test_snooze_rejects_bad_days(self):
        self.assertEqual(self.main(["snooze", "abc"]), 2)

    def test_unsnooze_clears(self):
        self.main(["snooze", "3"])
        self.main(["unsnooze"])
        self.assertIsNone(self._wm()["snooze_until"])

    def test_mark_posted_pins_head_and_drops_rec(self):
        st.write_json(st.recommendation_path(self.repo), {"verdict": "post-worthy"})
        self.assertEqual(self.main(["mark-posted"]), 0)
        self.assertEqual(self._wm()["last_posted_head"], self.head)
        self.assertIsNone(st.read_json(st.recommendation_path(self.repo), None))

    def test_stage_fake_writes_post_worthy_rec(self):
        self.assertEqual(self.main(["stage-fake"]), 0)
        rec = st.read_json(st.recommendation_path(self.repo), None)
        self.assertEqual(rec["verdict"], "post-worthy")
        self.assertEqual(rec["head"], self.head)

    def test_reset_removes_state(self):
        self.main(["stage-fake"])
        self.main(["snooze", "1"])
        self.assertEqual(self.main(["reset"]), 0)
        self.assertIsNone(st.read_json(st.recommendation_path(self.repo), None))
        self.assertIsNone(st.read_json(st.watermark_path(self.repo), None))

    def test_unknown_command_returns_2(self):
        self.assertEqual(self.main(["bogus"]), 2)


if __name__ == "__main__":
    unittest.main()
