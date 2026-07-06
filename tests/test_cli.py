"""Tests for the CLI dispatch (postcommit.__main__), the MCP server's graceful
degradation (postcommit.serve), and the skill install verb (postcommit.install).
"""

import contextlib
import io
import os
import tempfile
import unittest

from _support import commit, init_repo

from postcommit import __main__ as cli
from postcommit import install as installer
from postcommit import serve


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


class Serve(unittest.TestCase):
    def test_main_without_mcp_extra_hints_and_exits_nonzero(self):
        # The `mcp` extra is not installed in the test env; main() must degrade.
        try:
            import mcp  # noqa: F401
            self.skipTest("mcp is installed; graceful-degradation path not exercised")
        except ImportError:
            pass
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = serve.main([])
        self.assertEqual(rc, 1)
        self.assertIn("postcommit[mcp]", err.getvalue())


class Install(unittest.TestCase):
    def test_writes_skill_into_fake_home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        saved = os.environ.get("HOME")
        os.environ["HOME"] = tmp.name
        self.addCleanup(lambda: os.environ.__setitem__("HOME", saved) if saved
                        else os.environ.pop("HOME", None))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = installer.install(claude=True)
        self.assertEqual(rc, 0)
        dest = os.path.join(tmp.name, ".claude", "skills",
                            "postcommit-extract", "SKILL.md")
        self.assertTrue(os.path.isfile(dest))
        with open(dest, encoding="utf-8") as fh:
            self.assertIn("postcommit extract", fh.read())


if __name__ == "__main__":
    unittest.main()
