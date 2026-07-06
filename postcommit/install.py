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


def install(claude=True):
    wrote = []
    if claude:
        dest = claude_skill_path()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(_skill_text())
        wrote.append(dest)
    if not wrote:
        print("nothing to install (no host selected)")
        return 0
    for path in wrote:
        print("installed skill adapter -> %s" % path)
    print("restart Claude Code once so it discovers the skill.")
    return 0
