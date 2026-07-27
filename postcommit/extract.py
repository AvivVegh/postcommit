"""postcommit.extract — deterministic work-bundle builder.

This is the code-first port of the old prompt-driven `postcommit-extract` skill.
It assembles a compact, high-signal **work bundle** answering "what did the human
actually do here?" from local sources only — git state plus Claude Code session
transcripts. No network. Nothing leaves the machine.

The mechanical steps (window parsing, git gathering, transcript location and
filtering, diff capping, secret masking, bundle emission) live here. The one
judgment call the skill used to make — the "Candidate signal" inference — is
left as a stub for the /post flow to fill, so this stays fully deterministic.

    from postcommit.extract import build_bundle
    print(build_bundle("1d", "/path/to/repo"))

Two shapes come out of here. `build_bundle` is the flat whole-window view (one
merged diff). `build_per_commit_bundle` slices the same window into one section
per commit — the shape `/post` uses, because one post is meant to cover one
piece of work, not everything that happened in a day. Which slices belong to the
same piece of work is judgment, so that grouping is left to the model.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from . import state as st

DIFF_CHAR_CAP = 40_000
MAX_PROMPT_CHARS = 280
MAX_LINE_CHARS = 200
MAX_TOOL_CHARS = 120

# Per-commit mode emits N diffs instead of one, so each gets a smaller share and
# the run as a whole gets a ceiling: a 30-commit window must not produce a bundle
# no model can hold. Once the total is spent, later slices keep their metadata and
# lose their patch body — the commit is still visible, just not quotable.
PER_COMMIT_DIFF_CAP = 12_000
PER_COMMIT_TOTAL_CAP = 60_000
# A single slice's session excerpt. The flat bundle is deliberately uncapped, but
# there it is one block; here an unbounded slice would drown the other slices.
MAX_SLICE_SESSION_LINES = 80

_DURATION_RE = re.compile(r"^(\d+)([dhm])$")
_SINCE_RE = re.compile(r"^since=(\d{4}-\d{2}-\d{2})$")

VALID_FORMS = (
    "valid windows: a duration (1d, 4h, 30m), `today`, a git range "
    "(HEAD~3..HEAD, main..HEAD, <sha>..<sha>), or since=YYYY-MM-DD"
)


class WindowError(ValueError):
    """Raised when the window argument is not a recognized form."""


class NotARepoError(RuntimeError):
    """Raised when extraction is attempted outside a git work tree."""


# --- Step 1: parse the window ----------------------------------------------


def parse_window(window, cwd):
    """Resolve a window string into a cutoff + git ranges.

    Returns a dict:
      cutoff     tz-aware UTC datetime (lower bound for session events), or None
      log_args   argv suffix for `git log` to list in-window commits
      diff_range range string for `git diff <range>` (committed changes)
      label      the original window string (for the bundle header)
    """
    window = (window or "").strip()
    if not window:
        raise WindowError("no window given; " + VALID_FORMS)

    # Explicit git range — pass through, derive cutoff from the earliest commit.
    if ".." in window:
        cutoff = _earliest_commit_time(cwd, window)
        return {"cutoff": cutoff, "log_args": [window],
                "diff_range": window, "label": window}

    m = _DURATION_RE.match(window)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = {"d": 86400, "h": 3600, "m": 60}[unit] * n
        cutoff = st.now_utc() - timedelta(seconds=seconds)
        return _time_window(cwd, cutoff, window)

    if window == "today":
        local_midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        cutoff = local_midnight.astimezone(timezone.utc)
        return _time_window(cwd, cutoff, window)

    m = _SINCE_RE.match(window)
    if m:
        try:
            day = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError as exc:
            raise WindowError("bad date in %r; %s" % (window, VALID_FORMS)) from exc
        local_midnight = day.astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0)
        cutoff = local_midnight.astimezone(timezone.utc)
        return _time_window(cwd, cutoff, window)

    raise WindowError("unrecognized window %r; %s" % (window, VALID_FORMS))


def _time_window(cwd, cutoff, label):
    """Build ranges for a time-based window given a UTC cutoff."""
    since = _git_date(cutoff)
    # The diff base is the newest commit *before* the window; diff base..HEAD is
    # exactly the committed work inside the window. If nothing precedes the
    # window, diff against the empty tree so a repo's first commit still shows.
    base = st.git(cwd, "rev-list", "-1", "--before", since, "HEAD")
    diff_range = ("%s..HEAD" % base) if base else ("%s..HEAD" % st.EMPTY_TREE)
    return {"cutoff": cutoff, "log_args": ["--since", since],
            "diff_range": diff_range, "label": label}


def _git_date(dt):
    """A git-parseable timestamp string for a tz-aware datetime."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


def _earliest_commit_time(cwd, rng):
    out = st.git(cwd, "log", rng, "--reverse", "--format=%aI")
    if not out:
        return None
    first = out.splitlines()[0].strip()
    return st.parse_iso(first)


# --- Step 2: gather git state ----------------------------------------------


def gather_repo(cwd):
    """Repo identity + working-tree state. No window, no diff of the window.

    Split out of `gather_git` so per-commit mode can have the header block
    without paying for a whole-window `git diff` it never renders.
    """
    top = st.git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        raise NotARepoError("%s is not inside a git work tree" % cwd)

    status = st.git(cwd, "status", "--porcelain=v1") or ""
    unstaged = st.git(cwd, "diff") or ""
    staged = st.git(cwd, "diff", "--staged") or ""

    return {
        "top": os.path.abspath(top),
        "branch": st.git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "status": status,
        "has_uncommitted": bool(status or unstaged or staged),
    }


def gather_git(cwd, win):
    repo = gather_repo(cwd)

    commits = st.git(cwd, "log", "--pretty=format:%h %ci %s", *win["log_args"]) or ""
    commit_lines = [ln for ln in commits.splitlines() if ln.strip()]

    files, ins, dels = window_shortstat(cwd, win)

    raw_diff = st.git(cwd, "diff", win["diff_range"]) or ""
    diff = cap_diff(mask_secrets(raw_diff))

    out = dict(repo)
    out.update({
        "commits": commit_lines,
        "files": files,
        "insertions": ins,
        "deletions": dels,
        "diff": diff,
    })
    return out


def window_shortstat(cwd, win):
    shortstat = st.git(cwd, "diff", "--shortstat", win["diff_range"]) or ""
    return st.parse_shortstat(shortstat)


# --- Step 2b: per-commit slicing --------------------------------------------

# %x1f is the ASCII unit separator — it cannot appear in a commit subject, so
# splitting on it is safe where splitting on a space or a tab is not.
_LOG_FORMAT = "%H%x1f%h%x1f%cI%x1f%P%x1f%s"

# Version bumps and release chores are real commits with real diffs, and they
# have no story in them. Filtered, not deleted: they stay listed with a reason.
_RELEASE_SUBJECT_RE = re.compile(
    r"^(?:chore|ci|build)\s*(?:\([^)]*\))?\s*:\s*(?:release|bump|v?\d+\.\d+)"
    r"|^(?:chore|ci|build)\s*\(release\)"
    r"|^release[:\s]"
    r"|^bump\s+version",
    re.IGNORECASE)


def gather_commits(cwd, win):
    """Every commit in the window, oldest first.

    Returns dicts with sha / short / ts / parents / subject. Parents come along
    so merge commits can be recognized without a second git call.
    """
    out = st.git(cwd, "log", "--pretty=format:" + _LOG_FORMAT, *win["log_args"])
    commits = []
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        sha, short, when, parents, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
        commits.append({
            "sha": sha,
            "short": short,
            "ts": st.parse_iso(when),
            "parents": parents.split(),
            "subject": subject,
        })
    commits.reverse()  # git log is newest-first; slices read chronologically
    return commits


def filter_reason(commit, diff):
    """Why this commit gets no post, or None if it deserves one."""
    if len(commit["parents"]) > 1:
        return "merge commit"
    if _RELEASE_SUBJECT_RE.search(commit["subject"] or ""):
        return "release/version bump"
    if not (diff or "").strip():
        return "no diff after masking"
    return None


def commit_diff(cwd, sha, limit=PER_COMMIT_DIFF_CAP):
    """One commit's patch, masked and capped. `--format=` drops the log header."""
    raw = st.git(cwd, "show", "--format=", "--patch", sha) or ""
    return cap_diff(mask_secrets(raw), limit)


def commit_shortstat(cwd, sha):
    out = st.git(cwd, "show", "--format=", "--shortstat", sha) or ""
    return st.parse_shortstat(out)


def session_lines_between(sessions, start, end):
    """Session lines timestamped in `(start, end]`, oldest first.

    A None bound is open on that side. Lines with no timestamp are dropped —
    they cannot be attributed to a commit, and guessing would put a stranger's
    words in the wrong story.
    """
    picked = []
    for s in sessions:
        for ts, text in s["entries"]:
            if ts is None:
                continue
            if start is not None and ts <= start:
                continue
            if end is not None and ts > end:
                continue
            picked.append((ts, text))
    picked.sort(key=lambda pair: pair[0])
    return [text for _, text in picked]


# --- diff hygiene: secret masking + size cap -------------------------------

_SENSITIVE_FILE_RE = re.compile(
    r"(^|/)(credentials|secrets?)[^/]*$"       # credentials*, secret*, secrets*
    r"|(^|/)[^/]*\.env(\.[^/]*)?$"             # .env, .env.local, prod.env
    r"|\.(pem|key|p12|pfx)$", re.IGNORECASE)   # key / certificate material

# Substring redactions that apply to ANY text — diff lines, prompts, shell
# commands, assistant output — not just `key = value` on a line of its own.
# Letter boundaries keep `auth_token=` matching while sparing `tokenizer`.
_INLINE_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|"
    r"secret|token|password|passwd|bearer|credential)s?[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s\"';,)&]+)")
_URL_CRED_RE = re.compile(r"([a-z][a-z0-9+.\-]*://[^/\s:@]+:)[^/\s@]+@")
# `Authorization: Bearer <token>` / a bare `Bearer <token>` — the token follows
# whitespace, not an `=`/`:`, so it is not covered by _INLINE_SECRET_RE.
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{6,}")
# The JWT alternative must stay *before* the bare base64(JSON) one: alternation
# is leftmost-first, so at a position starting `eyJ` the dotted JWT pattern gets
# first refusal and consumes the whole token rather than just its header segment.
_TOKEN_RE = re.compile(
    r"(?i)(?<![a-z0-9])("
    r"sk-[a-z0-9][a-z0-9-]{7,}"                               # OpenAI/Stripe-style
    r"|gh[pousr]_[a-z0-9]{16,}"                               # GitHub tokens
    r"|AKIA[0-9A-Z]{12,}"                                     # AWS access key id
    r"|xox[baprs]-[a-z0-9-]{8,}"                              # Slack tokens
    r"|AIza[0-9A-Za-z_\-]{35,}"                               # Google/Firebase API key
    r"|eyJ[a-z0-9_\-]{8,}\.[a-z0-9_\-]{8,}\.[a-z0-9_\-]{6,}"  # JWT
    # base64(JSON) credential blob — what postcommit-cloud's "copy token" button
    # emits. It holds a refresh_token, so it is permanent account access. Being
    # one unbroken base64 run it has no dots, so the JWT rule above misses it
    # entirely; a user pasting it into the chat would otherwise land it in the
    # transcript, and from there into a work bundle and a draft. `{`/`"` encodes
    # to a leading `eyJ`, and 60+ chars keeps this off short base64 fixtures.
    r"|eyJ[A-Za-z0-9+/_\-]{60,}={0,2}"                        # base64(JSON) blob
    r")(?![a-z0-9])")


def scrub_text(text):
    """Redact secret-looking substrings from arbitrary text.

    Works on any string — a prompt, a shell command, assistant output — not
    only diff-formatted lines. Masks `key=value` / `key: value` secrets, URL
    credentials (`scheme://user:pass@host`), `Bearer <token>`, and well-known
    token shapes. This is the single choke point the privacy rule ("mask
    secrets") relies on, so everything user-authored or transcript-derived must
    pass through it.
    """
    if not text:
        return text
    text = _URL_CRED_RE.sub(r"\1***@", text)
    text = _BEARER_RE.sub(r"\1***", text)
    text = _INLINE_SECRET_RE.sub(r"\1***", text)
    text = _TOKEN_RE.sub("***", text)
    return text


def mask_secrets(diff):
    """Redact secret-looking values and the bodies of sensitive files.

    Sensitive-file content lines are dropped wholesale; every other line runs
    through `scrub_text`, so secrets leak neither from ordinary diff bodies nor
    from `@@`-hunk-header context.
    """
    if not diff:
        return diff
    out = []
    sensitive_file = False
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            path = line[4:].strip()
            if path.startswith(("a/", "b/")):
                path = path[2:]
            sensitive_file = bool(_SENSITIVE_FILE_RE.search(path))
            out.append(line)
            continue
        if line.startswith("diff --git"):
            sensitive_file = bool(_SENSITIVE_FILE_RE.search(line))
            out.append(line)
            continue
        # content lines of a diff start with +, -, or a space
        if sensitive_file and line[:1] in ("+", "-", " "):
            out.append(line[:1] + " [redacted — sensitive file]")
            continue
        out.append(scrub_text(line))
    return "\n".join(out)


def cap_diff(diff, limit=DIFF_CHAR_CAP):
    """Cap the diff at ~`limit` chars, preserving file/hunk structure.

    Structural lines (file boundaries, hunk headers, mode/rename markers) are
    always kept so the shape survives; hunk body lines past the budget are
    replaced with a single `[N lines elided]` marker.
    """
    if len(diff) <= limit:
        return diff
    structural = (
        "diff --git", "index ", "--- ", "+++ ", "@@", "new file",
        "deleted file", "rename ", "similarity ", "old mode", "new mode",
        "Binary files",
    )
    out = []
    size = 0
    eliding = 0
    for line in diff.splitlines():
        keep = line.startswith(structural) or size < limit
        if keep:
            if eliding:
                out.append("[%d lines elided]" % eliding)
                eliding = 0
            out.append(line)
            size += len(line) + 1
        else:
            eliding += 1
    if eliding:
        out.append("[%d lines elided]" % eliding)
    return "\n".join(out)


# --- Step 3+4: locate and parse session transcripts ------------------------



def _dir_is_for_cwd(cand, abscwd):
    """Confirm a candidate project dir actually belongs to `abscwd`.

    Claude Code records the session `cwd` in transcript records, so we can
    disambiguate an encoding collision by reading it back. Returns True on a
    confirmed match; if no record carries a `cwd` at all we can't tell, so we
    fall back to True rather than drop a legitimate directory.
    """
    try:
        names = [n for n in os.listdir(cand) if n.endswith(".jsonl")]
    except OSError:
        return False
    saw_cwd = False
    for name in names:
        try:
            with open(os.path.join(cand, name), encoding="utf-8",
                      errors="replace") as fh:
                for i, raw in enumerate(fh):
                    if i >= 50:
                        break
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    c = rec.get("cwd")
                    if c:
                        saw_cwd = True
                        if os.path.abspath(c) == abscwd:
                            return True
        except OSError:
            continue
    return not saw_cwd


def transcript_dir(cwd):
    """Locate the Claude Code project dir for `cwd`, or None if absent.

    Claude Code encodes the absolute cwd by replacing path separators with `-`
    (documented rule). Some versions also fold `.` to `-`. The `.`-folded form
    is ambiguous — `foo.bar` and `foo-bar` both encode to `-...-foo-bar` — so we
    take the exact encoding as-is but verify the folded fallback against the
    session's recorded `cwd` before trusting it, to avoid emitting a sibling
    repo's transcripts.
    """
    abscwd = os.path.abspath(cwd)
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    slash_only = abscwd.replace(os.sep, "-")
    also_dots = slash_only.replace(".", "-")
    for enc in (slash_only, also_dots):
        cand = os.path.join(base, enc)
        if os.path.isdir(cand):
            if enc == slash_only or _dir_is_for_cwd(cand, abscwd):
                return cand
    return None


def _transcript_files(cwd, cutoff):
    # A None cutoff means the window resolved to no commits (e.g. an empty git
    # range like `HEAD..HEAD`). Without a lower bound every session in the repo
    # would be scoped in, blowing past the requested window, so treat "no
    # cutoff" as "no transcripts".
    if cutoff is None:
        return []
    d = transcript_dir(cwd)
    if not d:
        return []
    cut_ts = cutoff.timestamp()
    picked = []
    try:
        for name in os.listdir(d):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(d, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime >= cut_ts:
                picked.append((mtime, path))
    except OSError:
        return []
    picked.sort()
    return [p for _, p in picked]


def _collapse(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _tool_summary(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    detail = ""
    if name == "Bash":
        detail = _collapse(inp.get("command", "")).split(" && ")[0]
    elif name in st.EDIT_TOOLS:
        detail = inp.get("file_path") or inp.get("notebook_path") or ""
    elif name == "Read":
        detail = inp.get("file_path") or inp.get("path") or ""
    elif name in ("Grep", "Glob"):
        detail = inp.get("pattern") or ""
    detail = _collapse(scrub_text(detail)) if detail else ""
    line = ("%s: %s" % (name, detail)).strip().rstrip(":")
    return line[:MAX_TOOL_CHARS]


def distill_session(path, cutoff):
    """Turn one session JSONL into a scannable narrative block, or None.

    `scoring.parse_transcript` walks the same records but stays deliberately
    separate — it runs in a hook and only counts, this builds narrative and is
    uncapped. Shared record vocabulary lives in `state` (META_PREFIXES,
    EDIT_TOOLS).

    Returns both `lines` (flat, for the whole-window bundle) and `entries` —
    the same lines paired with their record timestamps, which is what lets
    per-commit mode attribute a line to the commit it happened before.
    """
    entries = []
    first_ts = last_ts = None
    cut = cutoff
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if rec.get("isSidechain"):
                    continue
                ts = st.parse_iso(rec.get("timestamp"))
                if cut and ts and ts < cut:
                    continue

                rtype = rec.get("type")
                added = False
                if rtype == "user":
                    msg = rec.get("message") or {}
                    content = msg.get("content")
                    if (
                        isinstance(content, str)
                        and not rec.get("isMeta")
                        and not content.lstrip().startswith(st.META_PREFIXES)
                    ):
                        text = _collapse(scrub_text(content))[:MAX_PROMPT_CHARS]
                        if text:
                            entries.append((ts, "> " + text))
                            added = True
                elif rtype == "assistant":
                    msg = rec.get("message") or {}
                    for block in msg.get("content") or []:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            head = _first_line(block.get("text", ""))
                            if head:
                                entries.append(
                                    (ts, "- " + scrub_text(head)[:MAX_LINE_CHARS]))
                                added = True
                        elif btype == "tool_use":
                            summ = _tool_summary(block.get("name", "?"),
                                                 block.get("input"))
                            if summ:
                                entries.append((ts, "- " + summ))
                                added = True
                        # thinking blocks are skipped entirely

                if added and ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
    except OSError:
        return None

    if not entries:
        return None
    return {
        "id": os.path.basename(path)[:8],
        "first_ts": first_ts,
        "last_ts": last_ts,
        "entries": entries,
        "lines": [text for _, text in entries],
    }


def _first_line(text):
    for ln in (text or "").splitlines():
        ln = ln.strip()
        # skip fence markers so a code block collapses to its first prose line
        if not ln or ln.startswith("```"):
            continue
        return _collapse(ln)
    return ""


# --- Step 6: emit the bundle ------------------------------------------------


def build_bundle(window, cwd):
    """Assemble the full work bundle for `window` in `cwd`. Returns markdown."""
    win = parse_window(window, cwd)
    git = gather_git(cwd, win)
    sessions = [s for s in (distill_session(p, win["cutoff"])
                            for p in _transcript_files(cwd, win["cutoff"])) if s]

    meaningful = bool(git["commits"]) or git["has_uncommitted"] or bool(sessions)
    date = st.iso(st.now_utc())
    if not meaningful:
        return ("# Work bundle — %s — window: %s\n\n> No meaningful work in window."
                % (date, win["label"]))

    n_commits = len(git["commits"])
    out = []
    out.append("# Work bundle — %s — window: %s\n" % (date, win["label"]))

    out.append("## Repo")
    out.append("- path: %s" % git["top"])
    out.append("- branch: %s" % git["branch"])
    out.append("- commits in window: %d" % n_commits)
    out.append("- files changed: %d  (+%d / -%d)\n"
               % (git["files"], git["insertions"], git["deletions"]))

    out.append("## Git narrative\n")
    out.append("### Commits")
    if git["commits"]:
        out.extend("- " + c for c in git["commits"])
    else:
        out.append("none")
    out.append("")

    out.append("### Uncommitted")
    out.append(git["status"].rstrip() if git["status"].strip() else "clean")
    out.append("")

    out.append("### Diff highlights")
    if git["diff"].strip():
        out.append("```diff")
        out.append(git["diff"].rstrip())
        out.append("```")
    else:
        out.append("(no committed diff in window)")
    out.append("")

    out.append("## Session narrative\n")
    if sessions:
        for s in sessions:
            span = "%s → %s" % (
                st.iso(s["first_ts"]) if s["first_ts"] else "?",
                st.iso(s["last_ts"]) if s["last_ts"] else "?",
            )
            out.append("### Session %s — %s" % (s["id"], span))
            out.extend(s["lines"])
            out.append("")
    else:
        out.append("no session transcripts in window\n")

    out.append("## Candidate signal (best guesses, for the writer)")
    out.append("<!-- postcommit extract emits the facts above deterministically;")
    out.append("     it does not infer these. The /post flow (or you) fills them")
    out.append("     from the narrative before handing off to the writer. -->")
    out.append("- **Problem:** —")
    out.append("- **Obvious-but-wrong first move:** —")
    out.append("- **Real fix / resolution:** —")
    out.append("- **Surprising bit:** —")
    out.append("- **Transferable lesson:** —")

    return "\n".join(out).rstrip() + "\n"


def _session_block(lines):
    """Render a slice's session excerpt, capped so one slice can't drown the rest."""
    if not lines:
        return ["(no session activity in this slice)"]
    if len(lines) <= MAX_SLICE_SESSION_LINES:
        return list(lines)
    kept = lines[:MAX_SLICE_SESSION_LINES]
    return kept + ["[%d more session lines elided]"
                   % (len(lines) - MAX_SLICE_SESSION_LINES)]


def build_per_commit_bundle(window, cwd):
    """Assemble a **sliced** work bundle: one section per commit. Returns markdown.

    Same deterministic contract as `build_bundle` — this only changes the shape.
    The grouping of slices into work items is the model's job (see the closing
    section), because "these three commits are the same piece of work" is
    judgment, and judgment does not belong in here.
    """
    win = parse_window(window, cwd)
    repo = gather_repo(cwd)
    commits = gather_commits(cwd, win)
    sessions = [s for s in (distill_session(p, win["cutoff"])
                            for p in _transcript_files(cwd, win["cutoff"])) if s]

    meaningful = bool(commits) or repo["has_uncommitted"] or bool(sessions)
    date = st.iso(st.now_utc())
    if not meaningful:
        return ("# Work bundle (per commit) — %s — window: %s\n\n"
                "> No meaningful work in window." % (date, win["label"]))

    files, ins, dels = window_shortstat(cwd, win)

    out = []
    out.append("# Work bundle (per commit) — %s — window: %s\n" % (date, win["label"]))

    out.append("## Repo")
    out.append("- path: %s" % repo["top"])
    out.append("- branch: %s" % repo["branch"])
    out.append("- commits in window: %d" % len(commits))
    out.append("- files changed: %d  (+%d / -%d)\n" % (files, ins, dels))

    # Diffs are fetched once, up front: the filter needs to see them (an
    # empty-after-masking commit is filtered), and the budget needs to know how
    # much has been spent before deciding whether the next slice keeps its body.
    kept, filtered = [], []
    for commit in commits:
        diff = commit_diff(cwd, commit["sha"])
        reason = filter_reason(commit, diff)
        if reason:
            filtered.append((commit, reason))
        else:
            kept.append((commit, diff))

    out.append("## Filtered out")
    if filtered:
        out.append("<!-- listed, not deleted: nothing disappears silently. -->")
        for commit, reason in filtered:
            out.append("- %s %s — %s" % (commit["short"], commit["subject"], reason))
    else:
        out.append("nothing filtered")
    out.append("")

    out.append("## Work slices\n")
    if not kept:
        out.append("(no commits with a story in this window)\n")

    spent = 0
    prev_ts = None
    for commit, diff in kept:
        c_files, c_ins, c_dels = commit_shortstat(cwd, commit["sha"])
        out.append("### Slice %s — %s" % (commit["short"], commit["subject"]))
        out.append("- committed: %s" % (st.iso(commit["ts"]) if commit["ts"] else "?"))
        out.append("- files changed: %d  (+%d / -%d)\n" % (c_files, c_ins, c_dels))

        out.append("#### Diff")
        if spent >= PER_COMMIT_TOTAL_CAP:
            out.append("(diff omitted — bundle diff budget of %d chars reached)"
                       % PER_COMMIT_TOTAL_CAP)
        else:
            spent += len(diff)
            out.append("```diff")
            out.append(diff.rstrip())
            out.append("```")
        out.append("")

        out.append("#### Session excerpts")
        out.extend(_session_block(
            session_lines_between(sessions, prev_ts, commit["ts"])))
        out.append("")
        prev_ts = commit["ts"] or prev_ts

    if repo["has_uncommitted"]:
        raw = st.git(cwd, "diff", "HEAD") or ""
        out.append("### Slice working — uncommitted changes")
        out.append("- status:")
        out.append(repo["status"].rstrip() or "(no porcelain status)")
        out.append("")
        out.append("#### Diff")
        working = cap_diff(mask_secrets(raw), PER_COMMIT_DIFF_CAP)
        if working.strip():
            out.append("```diff")
            out.append(working.rstrip())
            out.append("```")
        else:
            out.append("(untracked files only — no diff)")
        out.append("")
        out.append("#### Session excerpts")
        out.extend(_session_block(session_lines_between(sessions, prev_ts, None)))
        out.append("")

    out.append("## Grouping + candidate signal (for the model)")
    out.append("<!-- postcommit extract slices deterministically; it does not")
    out.append("     decide which slices belong together. That is the one")
    out.append("     judgment call, and it happens downstream. -->")
    out.append("- Group the slices above into **work items**: same feature or")
    out.append("  scope, adjacent in time, overlapping files. Four commits of one")
    out.append("  feature are one item, not four.")
    out.append("- Uncommitted work is its own item.")
    out.append("- Item id = the newest commit's short sha in the group")
    out.append("  (`working` for the uncommitted item).")
    out.append("- Then fill, **per item**: Problem / Obvious-but-wrong first move /")
    out.append("  Real fix / Surprising bit / Transferable lesson.")

    return "\n".join(out).rstrip() + "\n"
