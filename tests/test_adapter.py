"""Tests for the thin hook adapter (hooks/_adapter.py).

The adapter lives under hooks/ (not the package), so it is loaded by path. It
pipes the hook payload to the CLI with a per-event subprocess timeout that keeps
the file-read-only session-start path from stalling session startup.
"""

import importlib.util
import io
import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "_adapter", os.path.join(ROOT, "hooks", "_adapter.py"))
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


class Forward(unittest.TestCase):
    def _timeout_for(self, event):
        captured = {}

        def fake_run(cmd, input=None, timeout=None, check=None):
            captured["timeout"] = timeout

        real_stdin = sys.stdin
        sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(b"{}"))
        try:
            with mock.patch.object(adapter.subprocess, "run", fake_run):
                adapter.forward(event)
        finally:
            sys.stdin = real_stdin
        return captured["timeout"]

    def test_session_start_timeout_is_tight(self):
        # The INSTANT path must not be allowed to hang for the long default.
        self.assertLessEqual(self._timeout_for("session-start"), 10)

    def test_session_end_gets_more_time_than_start(self):
        self.assertGreater(self._timeout_for("session-end"),
                           self._timeout_for("session-start"))

    def test_unknown_event_uses_default(self):
        self.assertEqual(self._timeout_for("whatever"), adapter._DEFAULT_TIMEOUT)

    def test_forward_swallows_subprocess_errors(self):
        real_stdin = sys.stdin
        sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(b"{}"))
        try:
            def boom(*a, **k):
                raise OSError("no such executable")
            with mock.patch.object(adapter.subprocess, "run", boom):
                adapter.forward("session-end")  # must not raise
        finally:
            sys.stdin = real_stdin


if __name__ == "__main__":
    unittest.main()
