"""postcommit.drafts — parse saved draft files into individual posts (stdlib).

`/post` saves one file per work item under `.postcommit/drafts/<UTC-ISO>-<sha>.md`,
holding a small header block and exactly one post, as specified by
`agents/post-writer.md`:

    ### Post — <one-line angle description>

    <the post itself>

The `### Post` heading is a label, not post copy, and must never be published.

**Legacy shape.** Before one-post-per-work-item, a run wrote three candidates
into a single file:

    ### Candidate <A|B|C> — <one-line angle description>

    <the post itself>

    — why this angle: <one sentence for the human reviewer>

separated by horizontal rules. Those files are still on users' disks, still
syncable, and still carry the reviewer note the writer spec marked as "not part
of the post" — so both headings parse and the note is still stripped.

Splitting on the horizontal rules would be wrong — the header block is separated
from the body by one too, and a post may legitimately contain one. So posts are
located by their headings and each block runs to the next heading.
"""

import re

# Both headings in one pattern. The dash between the label and the angle
# description may be any dash a writer or a human editor used, and the angle may
# be absent entirely. A legacy heading yields its letter as the key; the current
# one yields the constant POST.
POST_KEY = "POST"

_HEADING_RE = re.compile(
    r"^[ \t]*#{2,4}[ \t]+(?:Post|Candidate[ \t]+([A-Za-z]))[ \t]*"
    r"(?:[—–-][ \t]*(.*?))?[ \t]*$",
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
    """Return [{"key", "angle", "content"}] for each post in `text`.

    `key` is `POST` for the current one-post-per-file shape and the candidate
    letter for a legacy three-candidate file — it is what `cloud_sync` keys the
    idempotency ledger on, which is why a legacy file must keep reporting its
    letters.

    Returns [] when the file has no post headings at all — a hand-written or
    truncated draft. Posts whose body is empty once the heading and the reviewer
    note are removed are dropped, not returned blank.
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
        letter = match.group(1)
        out.append({
            "key": letter.upper() if letter else POST_KEY,
            "angle": (match.group(2) or "").strip(),
            "content": content,
        })
    return out
