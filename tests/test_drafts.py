"""Tests for postcommit.drafts — splitting a saved draft file into posts.

The things that must never reach the cloud are the `### Post` / `### Candidate`
headings and the `— why this angle` reviewer note (agents/post-writer.md calls
the latter "not part of the post"), so most of these assert on what is *absent*
from the parsed content.

Two shapes are covered on purpose: the current one-post-per-file draft, and the
pre-split three-candidate file that is still sitting on users' disks.
"""

import unittest

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import drafts

SINGLE = """# LinkedIn draft — 2026-07-26

- window: `1d`
- repo: `postcommit`
- branch: `main`
- item: `a1b2c3`
- generated: `2026-07-26T09:00:00Z`

---

### Post — The cost of the obvious approach

We shipped three drafts per run.

Nobody wanted three.
"""

LEGACY = """# LinkedIn draft candidates — 2026-07-26

- window: `1d`
- repo: `postcommit`
- branch: `main`
- generated: `2026-07-26T09:00:00Z`

---

### Candidate A — The debugging story

I spent four hours on a bug.

The fix was one line.

— why this angle: the timeline is concrete and verifiable.

---

### Candidate B — The counterintuitive lesson

The obvious fix made it worse.

— why this angle: leads with the surprise.

---

### Candidate C — The tiny tool share

Here is the snippet.

— why this angle: reusable artifact.
"""


class ParseSinglePost(unittest.TestCase):
    """The current shape: one work item, one file, one post."""

    def test_one_post_keyed_post(self):
        got = drafts.parse_candidates(SINGLE)
        self.assertEqual([drafts.POST_KEY], [c["key"] for c in got])

    def test_angle_captured(self):
        got = drafts.parse_candidates(SINGLE)
        self.assertEqual("The cost of the obvious approach", got[0]["angle"])

    def test_header_block_is_not_part_of_the_post(self):
        """The file's own header is separated by `---` — must not leak in."""
        got = drafts.parse_candidates(SINGLE)
        self.assertEqual(
            "We shipped three drafts per run.\n\nNobody wanted three.",
            got[0]["content"])
        self.assertNotIn("item:", got[0]["content"])
        self.assertNotIn("### Post", got[0]["content"])

    def test_missing_angle_is_empty_not_an_error(self):
        got = drafts.parse_candidates("### Post\n\nbody\n")
        self.assertEqual(drafts.POST_KEY, got[0]["key"])
        self.assertEqual("", got[0]["angle"])
        self.assertEqual("body", got[0]["content"])


class ParseLegacy(unittest.TestCase):
    """Pre-split drafts are still on disk, still syncable, still keyed A/B/C."""

    def test_finds_all_three_candidates(self):
        got = drafts.parse_candidates(LEGACY)
        self.assertEqual(["A", "B", "C"], [c["key"] for c in got])

    def test_angle_captured(self):
        got = drafts.parse_candidates(LEGACY)
        self.assertEqual("The debugging story", got[0]["angle"])

    def test_header_block_is_not_a_candidate(self):
        """The file's own header is separated by `---` too — must not leak in."""
        got = drafts.parse_candidates(LEGACY)
        self.assertEqual(3, len(got))
        for cand in got:
            self.assertNotIn("window:", cand["content"])
            self.assertNotIn("LinkedIn draft candidates", cand["content"])

    def test_strips_heading_and_reviewer_note(self):
        got = drafts.parse_candidates(LEGACY)
        self.assertEqual("I spent four hours on a bug.\n\nThe fix was one line.",
                         got[0]["content"])
        for cand in got:
            self.assertNotIn("why this angle", cand["content"])
            self.assertNotIn("### Candidate", cand["content"])

    def test_no_trailing_horizontal_rule(self):
        for cand in drafts.parse_candidates(LEGACY):
            self.assertFalse(cand["content"].rstrip().endswith("---"))

    def test_rule_inside_a_post_is_preserved(self):
        """Only *trailing* rules are separators; one mid-post is the author's."""
        text = ("### Candidate A — x\n\ntop\n\n---\n\nbottom\n\n"
                "— why this angle: y\n")
        got = drafts.parse_candidates(text)
        self.assertEqual("top\n\n---\n\nbottom", got[0]["content"])

    def test_ascii_dash_variants_accepted(self):
        text = "### Candidate A - x\n\nbody\n\n-- why this angle: y\n"
        got = drafts.parse_candidates(text)
        self.assertEqual([{"key": "A", "angle": "x", "content": "body"}], got)

    def test_missing_angle_is_empty_not_an_error(self):
        got = drafts.parse_candidates("### Candidate A\n\nbody\n")
        self.assertEqual("", got[0]["angle"])
        self.assertEqual("body", got[0]["content"])


class ParseEdges(unittest.TestCase):
    def test_no_posts_returns_empty(self):
        self.assertEqual([], drafts.parse_candidates("# just a note\n\nhello"))
        self.assertEqual([], drafts.parse_candidates(""))
        self.assertEqual([], drafts.parse_candidates(None))

    def test_empty_body_dropped_not_returned_blank(self):
        self.assertEqual([], drafts.parse_candidates("### Post — x\n"))
        text = "### Candidate A — x\n\n— why this angle: y\n"
        self.assertEqual([], drafts.parse_candidates(text))

    def test_a_hand_edited_file_may_hold_both_shapes(self):
        text = "### Post — new\n\nfresh\n\n---\n\n### Candidate B — old\n\nstale\n"
        got = drafts.parse_candidates(text)
        self.assertEqual([drafts.POST_KEY, "B"], [c["key"] for c in got])
        self.assertEqual(["fresh", "stale"], [c["content"] for c in got])


if __name__ == "__main__":
    unittest.main()
