"""postcommit.drafts — parse saved draft files into individual posts (stdlib).

`/post` saves one file per run under `.postcommit/drafts/<UTC-ISO>.md`, and that
file is *not* one post: it is a small header block followed by three candidates
in fixed angles, as specified by `agents/post-writer.md`:

    ### Candidate <A|B|C> — <one-line angle description>

    <the post itself>

    — why this angle: <one sentence for the human reviewer>

separated by horizontal rules. Two things in there must never be published: the
`### Candidate` heading (it is a label, not post copy) and the `— why this angle`
line, which the writer spec explicitly marks as "not part of the post".

Splitting on the horizontal rules would be wrong — the header block is separated
from the body by one too, and a post may legitimately contain one. So candidates
are located by their headings and each block runs to the next heading.
"""

import re

# The heading tolerates any dash the writer (or a human editor) used between the
# letter and the angle description, and tolerates the angle being absent.
_HEADING_RE = re.compile(
    r"^[ \t]*#{2,4}[ \t]+Candidate[ \t]+([A-Za-z])[ \t]*(?:[—–-][ \t]*(.*?))?[ \t]*$",
    re.MULTILINE)

# "— why this angle: ..." — em dash in the spec, but accept the ASCII variants a
# human edit is likely to introduce.
_WHY_RE = re.compile(r"^[ \t]*[—–-]{1,2}[ \t]*why this angle:.*$",
                     re.MULTILINE | re.IGNORECASE)

_RULE_LINE_RE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$")


def _strip_trailing_rules(block):
    """Drop the horizontal rule(s) that separated this block from the next.

    Only trailing rules go — a rule in the middle of a post is the author's.
    """
    lines = block.rstrip().split("\n")
    while lines and _RULE_LINE_RE.match(lines[-1]):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines)


def parse_candidates(text):
    """Return [{"letter", "angle", "content"}] for each candidate in `text`.

    Returns [] when the file has no candidate headings at all — a hand-written
    or truncated draft. Candidates whose body is empty once the heading and the
    reviewer note are removed are dropped, not returned as blank posts.
    """
    headings = list(_HEADING_RE.finditer(text or ""))
    out = []
    for i, match in enumerate(headings):
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = _WHY_RE.sub("", text[start:end])
        content = _strip_trailing_rules(block).strip()
        if not content:
            continue
        out.append({
            "letter": match.group(1).upper(),
            "angle": (match.group(2) or "").strip(),
            "content": content,
        })
    return out
