"""Tests for the SessionStart path (postcommit.hooks) — the nudge builder and
the five gates that decide whether a SessionStart nudge fires, driven end-to-end
through the thin hook shim."""

import json
import os
import tempfile
import unittest

from _support import run_hook
from _support import session_start as ss
from _support import state as st


class BuildNudge(unittest.TestCase):
    def test_includes_window_summary_and_reasons(self):
        text = ss.build_nudge({
            "window_hint": "main..HEAD",
            "summary_line": "2 commits, 3 files touched",
            "reasons": ["2 new commits", "debugging-story signal (bug)"],
        })
        self.assertIn("/post main..HEAD", text)
        self.assertIn("2 commits, 3 files touched", text)
        self.assertIn("debugging-story signal (bug)", text)
        self.assertIn("/post-snooze", text)

    def test_falls_back_when_fields_missing(self):
        text = ss.build_nudge({})
        self.assertIn("/post 1d", text)
        self.assertIn("looked post-worthy", text)


class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        # A post-worthy, unposted recommendation and a clean watermark.
        self.rec = {
            "verdict": "post-worthy",
            "head": "deadbeef",
            "created_at": st.iso(st.now_utc()),
            "window_hint": "1d",
            "summary_line": "2 commits, 3 files touched",
            "reasons": ["2 new commits"],
        }
        st.write_json(st.recommendation_path(self.repo), self.rec)
        st.write_json(st.watermark_path(self.repo), st.default_watermark())

    def _run(self, source="startup"):
        return run_hook(
            "session-start.py",
            {"source": source, "cwd": self.repo, "session_id": "s"},
            self.home,
        )

    def _fired(self, proc):
        if not proc.stdout.strip():
            return False
        out = json.loads(proc.stdout)
        return out["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def _nudge_state_path(self):
        # Mirrors postcommit_state.nudge_state_path() under the subprocess's HOME.
        return os.path.join(self.home, ".postcommit", "nudge-state.json")

    def _nudge_state(self):
        return st.read_json(self._nudge_state_path(), None)

    # --- happy path ---------------------------------------------------------

    def test_fires_and_stamps_cooldown(self):
        proc = self._run()
        self.assertTrue(self._fired(proc))
        self.assertIn("/post 1d", proc.stdout)
        self.assertEqual(self._nudge_state()["last_nudge_date"], st.today_local())

    # --- gate 1: source -----------------------------------------------------

    def test_silent_on_resume_source(self):
        self.assertFalse(self._fired(self._run(source="resume")))

    def test_silent_on_compact_source(self):
        self.assertFalse(self._fired(self._run(source="compact")))

    # --- gate 2: staged recommendation --------------------------------------

    def test_silent_without_recommendation(self):
        os.remove(st.recommendation_path(self.repo))
        self.assertFalse(self._fired(self._run()))

    def test_silent_when_not_post_worthy(self):
        st.write_json(st.recommendation_path(self.repo), {"verdict": "meh"})
        self.assertFalse(self._fired(self._run()))

    # --- gate 3: unposted ---------------------------------------------------

    def test_silent_when_head_already_posted(self):
        wm = st.default_watermark()
        wm["last_posted_head"] = "deadbeef"  # matches rec.head
        st.write_json(st.watermark_path(self.repo), wm)
        self.assertFalse(self._fired(self._run()))

    def test_silent_when_posted_after_recommendation(self):
        wm = st.default_watermark()
        wm["posted_at"] = st.iso(st.now_utc())  # posted at/after rec creation
        st.write_json(st.watermark_path(self.repo), wm)
        # rec was created a moment before; make sure it predates posted_at
        self.rec["created_at"] = st.iso(st.now_utc().replace(year=2000))
        st.write_json(st.recommendation_path(self.repo), self.rec)
        self.assertFalse(self._fired(self._run()))

    # --- gate 4: snooze -----------------------------------------------------

    def test_silent_while_snoozed(self):
        from datetime import timedelta
        wm = st.default_watermark()
        wm["snooze_until"] = st.iso(st.now_utc() + timedelta(days=2))
        st.write_json(st.watermark_path(self.repo), wm)
        self.assertFalse(self._fired(self._run()))

    def test_fires_after_snooze_expires(self):
        from datetime import timedelta
        wm = st.default_watermark()
        wm["snooze_until"] = st.iso(st.now_utc() - timedelta(days=1))
        st.write_json(st.watermark_path(self.repo), wm)
        self.assertTrue(self._fired(self._run()))

    # --- gate 5: daily cooldown ---------------------------------------------

    def test_silent_when_already_nudged_today(self):
        st.write_json(self._nudge_state_path(), {"last_nudge_date": st.today_local()})
        self.assertFalse(self._fired(self._run()))

    def test_only_fires_once_across_two_starts(self):
        self.assertTrue(self._fired(self._run()))
        self.assertFalse(self._fired(self._run()))  # cooldown now stamped


class Launcher(unittest.TestCase):
    """ss._ensure_launcher writes the ~/.postcommit/bin/postcommit shim that the
    model-run /post path uses to reach the plugin-bundled package."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        # point HOME at the throwaway dir so launcher_path() resolves under it
        self._prev_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        if self._prev_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._prev_home

    def _plugin_root(self, name="plugin"):
        """A fake plugin root that actually bundles the package (has __main__.py)."""
        root = os.path.join(self.tmp.name, name)
        os.makedirs(os.path.join(root, "postcommit"))
        with open(os.path.join(root, "postcommit", "__main__.py"), "w") as fh:
            fh.write("# marker\n")
        return root

    def _launcher(self):
        return os.path.join(self.home, ".postcommit", "bin", "postcommit")

    def _read_launcher(self):
        with open(self._launcher(), encoding="utf-8") as fh:
            return fh.read()

    def test_writes_executable_launcher_pointing_at_root(self):
        root = self._plugin_root()
        ss._ensure_launcher(root)
        p = self._launcher()
        self.assertTrue(os.path.isfile(p))
        self.assertTrue(os.access(p, os.X_OK))
        body = self._read_launcher()
        self.assertIn(root, body)
        self.assertIn("python3 -m postcommit", body)

    def test_idempotent_content_stable(self):
        root = self._plugin_root()
        ss._ensure_launcher(root)
        first = self._read_launcher()
        ss._ensure_launcher(root)
        self.assertEqual(first, self._read_launcher())

    def test_rewrites_when_plugin_root_changes(self):
        ss._ensure_launcher(self._plugin_root("plugin-a"))
        newroot = self._plugin_root("plugin-b")
        ss._ensure_launcher(newroot)
        body = self._read_launcher()
        self.assertIn(newroot, body)
        self.assertNotIn("plugin-a", body)

    def test_noop_when_root_unknown(self):
        ss._ensure_launcher(None)
        self.assertFalse(os.path.exists(self._launcher()))

    def test_noop_when_package_not_bundled(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)  # no postcommit/__main__.py inside
        ss._ensure_launcher(empty)
        self.assertFalse(os.path.exists(self._launcher()))

    def test_session_start_writes_launcher_via_env(self):
        """handle_session_start bootstraps the launcher from CLAUDE_PLUGIN_ROOT,
        even on a non-fresh source that produces no nudge."""
        root = self._plugin_root("plugin-env")
        prev = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = root
        try:
            out = ss.handle_session_start({"source": "resume", "cwd": self.home})
        finally:
            if prev is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = prev
        self.assertIsNone(out)  # resume → no nudge
        self.assertTrue(os.path.isfile(self._launcher()))  # but launcher written


if __name__ == "__main__":
    unittest.main()
