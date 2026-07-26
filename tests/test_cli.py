"""Tests for the CLI dispatch (postcommit.__main__)."""

import contextlib
import io
import os
import tempfile
import unittest

from _support import commit, init_repo

from postcommit import __main__ as cli


def _capture(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class Dispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))
        commit(self.repo, "a.txt", "one\n", "chore: init")
        commit(self.repo, "b.txt", "two\n" * 5, "feat: add b")
        self._cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self._cwd)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            _capture(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_extract_writes_bundle_to_stdout(self):
        rc, out, _ = _capture(["extract", "HEAD~1..HEAD"])
        self.assertEqual(rc, 0)
        self.assertIn("# Work bundle", out)
        self.assertIn("feat: add b", out)

    def test_extract_bad_window_returns_2(self):
        rc, _, err = _capture(["extract", "nonsense"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized window", err)

    def test_bad_subcommand_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            _capture(["bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_state_snooze_via_cli(self):
        rc, out, _ = _capture(["state", "snooze", "2"])
        self.assertEqual(rc, 0)
        self.assertIn("snoozed", out)

    def test_state_drafts_dir_prints_a_usable_path(self):
        """/post reads this path off stdout, so it must be the only thing on it."""
        rc, out, _ = _capture(["state", "drafts-dir"])
        self.assertEqual(rc, 0)
        path = out.strip()
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(os.path.basename(path), "drafts")

    def test_no_args_prints_help(self):
        rc, out, _ = _capture([])
        self.assertEqual(rc, 0)
        self.assertIn("usage", out.lower())


class HookVerb(unittest.TestCase):
    """The hook verbs must be crash-proof and always return 0."""

    def test_session_end_returns_zero_on_garbage_stdin(self):
        with contextlib.redirect_stdout(io.StringIO()):
            import sys
            saved = sys.stdin
            sys.stdin = io.StringIO("not json")
            try:
                rc = cli.main(["hook", "session-end"])
            finally:
                sys.stdin = saved
        self.assertEqual(rc, 0)


class CloudVerb(unittest.TestCase):
    """`postcommit cloud ...` exists on the *main* CLI so the plugin launcher
    (which runs `python3 -m postcommit`) can reach cloud auth at all."""

    def test_cloud_verb_is_registered(self):
        from postcommit.__main__ import build_parser
        args = build_parser().parse_args(["cloud", "status"])
        self.assertEqual(args.verb, "status")

    def test_cloud_defaults_to_status(self):
        from postcommit.__main__ import build_parser
        self.assertEqual(build_parser().parse_args(["cloud"]).verb, "status")

    def test_login_accepts_inline_token_and_browser_flag(self):
        from postcommit.__main__ import build_parser
        a = build_parser().parse_args(["cloud", "login", "BLOB"])
        self.assertEqual((a.verb, a.token, a.browser), ("login", "BLOB", False))
        b = build_parser().parse_args(["cloud", "login", "--browser"])
        self.assertTrue(b.browser)

    def test_sync_verb_and_dry_run_flag(self):
        from postcommit.__main__ import build_parser
        a = build_parser().parse_args(["cloud", "sync"])
        self.assertEqual((a.verb, a.dry_run), ("sync", False))
        b = build_parser().parse_args(["cloud", "sync", "--dry-run"])
        self.assertTrue(b.dry_run)

    def test_sync_dry_run_needs_no_credentials(self):
        """The plan is local-only, so it must work before /post-login."""
        cwd = tempfile.mkdtemp()
        old = os.getcwd()
        os.chdir(cwd)
        try:
            rc, out, _ = _capture(["cloud", "sync", "--dry-run"])
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to sync", out)

    def test_bad_cloud_verb_exits_2(self):
        from postcommit.__main__ import build_parser
        with self.assertRaises(SystemExit) as cm:
            build_parser().parse_args(["cloud", "bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_status_reports_signed_out_without_credentials(self):
        """Exit 1 = not usable, so /post-login can branch without parsing."""
        home = tempfile.mkdtemp()
        old = os.environ.get("HOME")
        os.environ["HOME"] = home
        os.environ.pop("POSTCOMMIT_CLOUD_TOKEN", None)
        try:
            rc, out, _ = _capture(["cloud", "status"])
        finally:
            if old is not None:
                os.environ["HOME"] = old
        self.assertEqual(rc, 1)
        self.assertIn("status: signed-out", out)


if __name__ == "__main__":
    unittest.main()
