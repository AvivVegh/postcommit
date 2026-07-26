"""Tests for postcommit.drafts — splitting a saved draft file into posts.

The two things that must never reach the cloud are the `### Candidate` heading
and the `— why this angle` reviewer note (agents/post-writer.md calls the latter
"not part of the post"), so most of these assert on what is *absent* from the
parsed content.
"""

import unittest

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import drafts

FULL = """# LinkedIn draft candidates — 2026-07-26

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


class Parse(unittest.TestCase):
    def test_finds_all_three_candidates(self):
        got = drafts.parse_candidates(FULL)
        self.assertEqual(["A", "B", "C"], [c["letter"] for c in got])

    def test_angle_captured(self):
        got = drafts.parse_candidates(FULL)
        self.assertEqual("The debugging story", got[0]["angle"])

    def test_header_block_is_not_a_candidate(self):
        """The file's own header is separated by `---` too — must not leak in."""
        got = drafts.parse_candidates(FULL)
        self.assertEqual(3, len(got))
        for cand in got:
            self.assertNotIn("window:", cand["content"])
            self.assertNotIn("LinkedIn draft candidates", cand["content"])

    def test_strips_heading_and_reviewer_note(self):
        got = drafts.parse_candidates(FULL)
        self.assertEqual("I spent four hours on a bug.\n\nThe fix was one line.",
                         got[0]["content"])
        for cand in got:
            self.assertNotIn("why this angle", cand["content"])
            self.assertNotIn("### Candidate", cand["content"])

    def test_no_trailing_horizontal_rule(self):
        for cand in drafts.parse_candidates(FULL):
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
        self.assertEqual([{"letter": "A", "angle": "x", "content": "body"}], got)

    def test_missing_angle_is_empty_not_an_error(self):
        got = drafts.parse_candidates("### Candidate A\n\nbody\n")
        self.assertEqual("", got[0]["angle"])
        self.assertEqual("body", got[0]["content"])

    def test_no_candidates_returns_empty(self):
        self.assertEqual([], drafts.parse_candidates("# just a note\n\nhello"))
        self.assertEqual([], drafts.parse_candidates(""))
        self.assertEqual([], drafts.parse_candidates(None))

    def test_empty_body_dropped_not_returned_blank(self):
        text = "### Candidate A — x\n\n— why this angle: y\n"
        self.assertEqual([], drafts.parse_candidates(text))


if __name__ == "__main__":
    unittest.main()
