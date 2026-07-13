---
tags: [concept, tooling]
aliases: [install.py, link-local, distribution]
---

# Install and Distribution

Distribution has **two pieces** that must both be present: the Python package (does the work) and the Claude Code plugin (wires `/post`, the skill, and the hooks — all of which call the package).

## Published path
1. **Install the CLI** — `uv tool install postcommit` (or `pip`/`pipx`). Core is dependency-free; MCP server needs `uv tool install 'postcommit[mcp]'`. `postcommit --version` then works on PATH.
2. **Install the plugin** — the repo is its own marketplace:
   ```
   /plugin marketplace add AvivVegh/postcommit
   /plugin install postcommit
   ```
   Registers `/post`, `/post-snooze`, the extract skill, the [[Post-Writer Agent]], and the two [[Hooks]] (via `hooks/hooks.json`, using `${CLAUDE_PLUGIN_ROOT}`). Uninstall removes all of them — including hooks — automatically. **No manual `settings.json` editing.**

Update: `uv tool upgrade postcommit` + `/plugin update postcommit`.

## Build
`uv build` → wheel/sdist. `uv tool install .` installs the `postcommit` + `postcommit-mcp` entry points. `uv.lock` pins the resolution. Keep the core stdlib-only ([[Privacy Model]]).

## `postcommit install` (install.py)
Copies the packaged skill adapter (`postcommit/data/skill.md`, shipped as package data) into a host's skill dir (`~/.claude/skills/postcommit-extract/SKILL.md`). Guards:
- refuses to write if the dest resolves **outside `~/.claude`** (a `link-local` dev symlink → would clobber tracked source).
- backs up an existing real file to `SKILL.md.bak` before replacing.
- Only the Claude Code host is wired today; Cursor/Codex variants are the natural next additions.

## Local dev — `scripts/link-local.sh`
uv-installs the package **editable**, symlinks `commands/` `skills/` `agents/` into `~/.claude/`, and registers the hooks in `~/.claude/settings.json` (backed up first). `--unlink` undoes it. Idempotent; refuses to overwrite non-symlink files. **Use this OR the plugin install, not both** — they register the same hooks two different ways.

## Related
[[Plugin Surface]] · [[CLI]] · [[MCP Server]] · [[Testing and CI]]
