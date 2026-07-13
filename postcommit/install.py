"""postcommit.install — write the packaged skill adapter into a host.

The extractor skill ships as package data (`postcommit/data/skill.md`). This
verb copies it into a host's skill directory so the thin adapter is available
without the Claude Code plugin. Today only the Claude Code host is wired up;
`per-host variants` (Cursor, Codex, …) are the natural next files to add here.
"""

import os

try:  # importlib.resources.files is 3.9+; the fallback keeps type-checkers calm
    from importlib.resources import files as _res_files
except ImportError:  # pragma: no cover
    _res_files = None


def _skill_text():
    if _res_files is not None:
        return (_res_files("postcommit") / "data" / "skill.md").read_text(
            encoding="utf-8")
    here = os.path.dirname(os.path.abspath(__file__))  # pragma: no cover
    with open(os.path.join(here, "data", "skill.md"), encoding="utf-8") as fh:
        return fh.read()


def claude_skill_path():
    return os.path.join(
        os.path.expanduser("~"), ".claude", "skills",
        "postcommit-extract", "SKILL.md")


def _within(path, root):
    return path == root or path.startswith(root + os.sep)


def _write_skill(dest, text):
    """Write the packaged skill to `dest` without clobbering a dev symlink or a
    hand-customized copy.

    `link-local.sh` symlinks this path (or its parent dir) back into the repo
    checkout; opening it "w" would then overwrite the tracked source. So if the
    path resolves outside ~/.claude we leave it untouched. An existing real file
    is preserved as `SKILL.md.bak` before being replaced.
    """
    claude_root = os.path.realpath(
        os.path.join(os.path.expanduser("~"), ".claude"))
    if not _within(os.path.realpath(dest), claude_root):
        return "skipped (symlinked outside ~/.claude — link-local dev mode): %s" % dest
    if os.path.isfile(dest):
        try:
            with open(dest, encoding="utf-8") as fh:
                if fh.read() == text:
                    return "already current: %s" % dest
        except OSError:
            pass
        try:
            os.replace(dest, dest + ".bak")  # keep any customized copy
        except OSError:
            pass
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    return "installed skill adapter -> %s" % dest


def install(claude=True):
    msgs = []
    if claude:
        dest = claude_skill_path()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        msgs.append(_write_skill(dest, _skill_text()))
    if not msgs:
        print("nothing to install (no host selected)")
        return 0
    for msg in msgs:
        print(msg)
    print("restart Claude Code once so it discovers the skill.")
    return 0
