"""Tests for the SessionEnd path — scoring, transcript parsing (postcommit.scoring),
and the end-to-end recommendation staging through the thin hook shim."""

import json
import os
import tempfile
import unittest

from _support import (
    commit,
    edit_msg,
    init_repo,
    run_hook,
    user_msg,
    write_transcript,
)
from _support import (
    scoring as se,
)
from _support import (
    state as st,
)


def git_sig(**over):
    base = {"n_commits": 0, "files": 0, "insertions": 0, "deletions": 0,
            "has_uncommitted": False, "window_hint": "1d", "range": None}
    base.update(over)
    return base


def tx_sig(**over):
    base = {"n_user_prompts": 0, "n_edits": 0, "duration_min": 0,
            "keywords": set(), "first_ts": None}
    base.update(over)
    return base


class ParseShortstat(unittest.TestCase):
    def test_full_line(self):
        sig = git_sig()
        se._parse_shortstat("5 files changed, 100 insertions(+), 50 deletions(-)", sig)
        self.assertEqual((sig["files"], sig["insertions"], sig["deletions"]), (5, 100, 50))

    def test_insertions_only(self):
        sig = git_sig()
        se._parse_shortstat("1 file changed, 3 insertions(+)", sig)
        self.assertEqual((sig["files"], sig["insertions"], sig["deletions"]), (1, 3, 0))

    def test_deletions_only(self):
        sig = git_sig()
        se._parse_shortstat("2 files changed, 4 deletions(-)", sig)
        self.assertEqual((sig["files"], sig["insertions"], sig["deletions"]), (2, 0, 4))

    def test_empty_resets_to_zero(self):
        sig = git_sig(files=9, insertions=9, deletions=9)
        se._parse_shortstat("", sig)
        self.assertEqual((sig["files"], sig["insertions"], sig["deletions"]), (0, 0, 0))

    def test_add_variant_accumulates(self):
        sig = git_sig(files=1, insertions=10, deletions=2)
        se._parse_shortstat_add("2 files changed, 5 insertions(+), 3 deletions(-)", sig)
        self.assertEqual((sig["files"], sig["insertions"], sig["deletions"]), (3, 15, 5))


class Score(unittest.TestCase):
    def test_commit_heavy_work_is_post_worthy(self):
        pts, reasons = se.score(
            git_sig(n_commits=2, files=5, insertions=100, deletions=50), tx_sig())
        self.assertGreaterEqual(pts, se.POST_WORTHY_THRESHOLD)
        self.assertEqual(pts, 9)  # 6 (commits) + 2 (churn>=30) + 1 (churn>=150)

    def test_single_commit_reason_singular(self):
        _, reasons = se.score(git_sig(n_commits=1), tx_sig())
        self.assertIn("1 new commit", reasons)

    def test_commit_points_capped_at_two(self):
        # 5 commits scores the same commit points as 2 (min(n,2)*3 == 6)
        pts5, _ = se.score(git_sig(n_commits=5), tx_sig())
        pts2, _ = se.score(git_sig(n_commits=2), tx_sig())
        self.assertEqual(pts5, pts2)

    def test_trivial_change_is_capped_below_threshold(self):
        # Big session signals but no commits and near-zero churn -> not a story.
        pts, _ = se.score(
            git_sig(n_commits=0, insertions=2, has_uncommitted=True),
            tx_sig(n_edits=5, n_user_prompts=5, duration_min=30, keywords={"bug"}))
        self.assertLess(pts, se.POST_WORTHY_THRESHOLD)

    def test_uncommitted_wip_scores_a_point(self):
        pts, reasons = se.score(
            git_sig(n_commits=0, insertions=5, deletions=1, has_uncommitted=True),
            tx_sig())
        self.assertEqual(pts, 1)
        self.assertTrue(any("uncommitted" in r for r in reasons))

    def test_transcript_signals_add_up(self):
        pts, reasons = se.score(
            git_sig(n_commits=1),
            tx_sig(n_edits=3, n_user_prompts=3, duration_min=20, keywords={"bug", "fix"}))
        # 3 (commit) + 1 edits + 1 prompts + 1 duration + 1 keywords
        self.assertEqual(pts, 7)
        self.assertTrue(any("debugging-story" in r for r in reasons))


class ParseTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, records):
        return write_transcript(os.path.join(self.tmp.name, "s.jsonl"), records)

    def test_missing_file_returns_empty_signals(self):
        sig = se.parse_transcript(os.path.join(self.tmp.name, "nope.jsonl"))
        self.assertEqual(sig["n_user_prompts"], 0)
        self.assertEqual(sig["n_edits"], 0)

    def test_counts_prompts_edits_keywords_and_duration(self):
        path = self._write([
            user_msg("I hit a bug in the parser", ts="2026-07-05T10:00:00Z"),
            edit_msg("Edit", ts="2026-07-05T10:05:00Z"),
            edit_msg("Write", ts="2026-07-05T10:10:00Z"),
            user_msg("now fix the error", ts="2026-07-05T10:12:00Z"),
        ])
        sig = se.parse_transcript(path)
        self.assertEqual(sig["n_user_prompts"], 2)
        self.assertEqual(sig["n_edits"], 2)
        self.assertEqual(sig["keywords"], {"bug", "fix", "error"})
        self.assertEqual(sig["duration_min"], 12)  # 300 + 300 + 120 = 720s

    def test_meta_and_command_prompts_ignored(self):
        path = self._write([
            user_msg("<command-name>/post</command-name>"),
            user_msg("real work happened here", is_meta=True),
            user_msg({"not": "a string"}),
        ])
        sig = se.parse_transcript(path)
        self.assertEqual(sig["n_user_prompts"], 0)

    def test_idle_gap_excluded_from_duration(self):
        path = self._write([
            user_msg("start", ts="2026-07-05T10:00:00Z"),
            # 2h gap — session left open, not active work
            user_msg("resume", ts="2026-07-05T12:00:00Z"),
            edit_msg("Edit", ts="2026-07-05T12:05:00Z"),
        ])
        sig = se.parse_transcript(path)
        self.assertEqual(sig["duration_min"], 5)  # only the 5-min active gap counts

    def test_non_edit_tools_not_counted(self):
        path = self._write([edit_msg("Read"), edit_msg("Bash"), edit_msg("Grep")])
        self.assertEqual(se.parse_transcript(path)["n_edits"], 0)

    def test_malformed_lines_skipped(self):
        path = os.path.join(self.tmp.name, "s.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{bad json\n")
            fh.write("\n")
            fh.write(json.dumps(user_msg("valid prompt with a fix")) + "\n")
        self.assertEqual(se.parse_transcript(path)["n_user_prompts"], 1)


class FreshDraft(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.drafts = os.path.join(self.tmp.name, ".postcommit", "drafts")
        os.makedirs(self.drafts)

    def test_true_when_draft_written_after_session_start(self):
        with open(os.path.join(self.drafts, "d.md"), "w") as fh:
            fh.write("draft")
        past = st.now_utc().replace(year=2000)
        self.assertTrue(se.fresh_draft_since(self.tmp.name, past))

    def test_false_when_draft_predates_session(self):
        with open(os.path.join(self.drafts, "d.md"), "w") as fh:
            fh.write("draft")
        future = st.now_utc().replace(year=2999)
        self.assertFalse(se.fresh_draft_since(self.tmp.name, future))

    def test_false_when_no_first_ts(self):
        self.assertFalse(se.fresh_draft_since(self.tmp.name, None))


class SummaryLine(unittest.TestCase):
    def test_pluralization_and_join(self):
        line = se.summary_line(git_sig(n_commits=2, files=1), tx_sig(duration_min=15))
        self.assertEqual(line, "2 commits, 1 file touched, ~15 min")

    def test_fallback_when_empty(self):
        self.assertEqual(se.summary_line(git_sig(), tx_sig()), "recent work")


class EndToEnd(unittest.TestCase):
    """Run the hook as a subprocess against a real repo + transcript."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.repo = init_repo(os.path.join(self.tmp.name, "repo"))
        base = commit(self.repo, "a.py", "x = 1\n", "chore: init")
        # Pin the watermark to `base` so the hook measures a real range diff
        # (base..HEAD), which is what pushes the score over the threshold.
        st.write_json(st.watermark_path(self.repo), {"last_posted_head": base})
        commit(self.repo, "b.py", "y = 2\n" * 40, "feat: big work")
        commit(self.repo, "c.py", "z = 3\n" * 40, "feat: more work")
        self.transcript = write_transcript(
            os.path.join(self.tmp.name, "s.jsonl"),
            [user_msg("fix the crash", ts="2026-07-05T10:00:00Z"),
             edit_msg("Edit", ts="2026-07-05T10:05:00Z")])

    def _payload(self, session_id="sess-1"):
        return {"session_id": session_id, "cwd": self.repo,
                "transcript_path": self.transcript, "reason": "clear"}

    def test_stages_recommendation_and_marks_processed(self):
        proc = run_hook("session-end.py", self._payload(), self.home)
        self.assertEqual(proc.returncode, 0)
        rec = st.read_json(st.recommendation_path(self.repo), None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["verdict"], "post-worthy")
        wm = st.read_watermark(self.repo)
        self.assertIn("sess-1", wm["processed_sessions"])

    def test_idempotent_for_same_session(self):
        run_hook("session-end.py", self._payload(), self.home)
        # remove the rec, re-run same session id: must NOT re-stage
        os.remove(st.recommendation_path(self.repo))
        run_hook("session-end.py", self._payload(), self.home)
        self.assertIsNone(st.read_json(st.recommendation_path(self.repo), None))

    def test_no_op_outside_git_repo(self):
        non_repo = os.path.join(self.tmp.name, "plain")
        os.makedirs(non_repo)
        payload = {"session_id": "s", "cwd": non_repo,
                   "transcript_path": self.transcript}
        run_hook("session-end.py", payload, self.home)
        self.assertFalse(os.path.exists(st.recommendation_path(non_repo)))


if __name__ == "__main__":
    unittest.main()
