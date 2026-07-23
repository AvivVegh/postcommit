"""Tests for hooks/_adapter.py — the shared forwarding logic behind the thin
SessionEnd / SessionStart shims. Focus on CLI resolution and the child env that
makes the plugin-bundled `python -m postcommit` fallback importable."""

import os
import sys
import unittest

from _support import ROOT

# _adapter lives in hooks/ (a sibling of the shims), not in the package.
HOOKS = os.path.join(ROOT, "hooks")
if HOOKS not in sys.path:
    sys.path.insert(0, HOOKS)

import _adapter  # noqa: E402


class PluginRoot(unittest.TestCase):
    def test_prefers_env_var(self):
        prev = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = "/some/plugin/root"
        try:
            self.assertEqual(_adapter._plugin_root(), "/some/plugin/root")
        finally:
            if prev is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = prev

    def test_falls_back_to_repo_root(self):
        prev = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        try:
            # two levels up from hooks/_adapter.py is the repo root
            self.assertEqual(_adapter._plugin_root(), ROOT)
        finally:
            if prev is not None:
                os.environ["CLAUDE_PLUGIN_ROOT"] = prev


class ChildEnv(unittest.TestCase):
    def test_sets_plugin_root_and_prepends_pythonpath(self):
        prev = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = "/existing/path"
        try:
            env = _adapter._child_env("/plugin/root")
        finally:
            if prev is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = prev
        self.assertEqual(env["CLAUDE_PLUGIN_ROOT"], "/plugin/root")
        self.assertEqual(
            env["PYTHONPATH"], "/plugin/root" + os.pathsep + "/existing/path")

    def test_pythonpath_without_prior_value(self):
        prev = os.environ.pop("PYTHONPATH", None)
        try:
            env = _adapter._child_env("/plugin/root")
        finally:
            if prev is not None:
                os.environ["PYTHONPATH"] = prev
        self.assertEqual(env["PYTHONPATH"], "/plugin/root")

    def test_does_not_override_existing_plugin_root(self):
        prev = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = "/already/set"
        try:
            env = _adapter._child_env("/plugin/root")
        finally:
            if prev is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = prev
        self.assertEqual(env["CLAUDE_PLUGIN_ROOT"], "/already/set")

    def test_root_none_leaves_env_untouched(self):
        env = _adapter._child_env(None)
        # no plugin root → don't inject one or fabricate a PYTHONPATH
        self.assertEqual(
            env.get("CLAUDE_PLUGIN_ROOT"), os.environ.get("CLAUDE_PLUGIN_ROOT"))


class Command(unittest.TestCase):
    def test_console_script_when_on_path(self):
        orig = _adapter.shutil.which
        _adapter.shutil.which = lambda name: "/usr/local/bin/postcommit"
        try:
            self.assertEqual(
                _adapter._command("session-end"),
                ["/usr/local/bin/postcommit", "hook", "session-end"])
        finally:
            _adapter.shutil.which = orig

    def test_module_fallback_when_not_on_path(self):
        orig = _adapter.shutil.which
        _adapter.shutil.which = lambda name: None
        try:
            self.assertEqual(
                _adapter._command("session-start"),
                [sys.executable, "-m", "postcommit", "hook", "session-start"])
        finally:
            _adapter.shutil.which = orig


if __name__ == "__main__":
    unittest.main()
