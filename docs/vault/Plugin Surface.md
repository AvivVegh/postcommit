---
tags: [prompt-layer, plugin]
aliases: [command, skill adapter, plugin manifest]
---

# Plugin Surface

The Claude Code plugin — thin adapters that shell out to the installed `postcommit` [[CLI]]. Manifest: `.claude-plugin/plugin.json` (name + version, kept in sync with `pyproject.toml`); self-hosted marketplace: `.claude-plugin/marketplace.json`.

## Commands
- **`commands/post.md`** — `/post <window>` — the manual trigger, a thin **dispatcher** (see [[Data Flow]]). Parses the window; loads the extract skill; dispatches the bundle to the [[Post-Writer Agent]]; saves to `.postcommit/drafts/<UTC-ISO>.md`; `open`s it; reports one line. **No creative or extraction logic.** Refuses empty `$ARGUMENTS`; stops on "no meaningful work"; never fabricates or prints candidates inline.
- **`commands/post-snooze.md`** — `/post-snooze [days]` — hush the nudge (wraps `postcommit state snooze`).

## Skill adapter
- **`skills/postcommit-extract/SKILL.md`** — thin: tells the model to run `postcommit extract <window>`, then fill the [[Extractor|Candidate signal]] from the bundle.
- **Mirror invariant:** it is a **byte-for-byte mirror** of `postcommit/data/skill.md`. Keep them identical — the package-data copy is what `postcommit install` writes into other hosts (see [[Install and Distribution]]).

## Hooks
- **`hooks/hooks.json`** — declares `SessionEnd` + `SessionStart`, each pointing at `"${CLAUDE_PLUGIN_ROOT}"/hooks/*.py`. Auto-registered on plugin install, removed on uninstall.
- **`hooks/session-end.py`**, **`hooks/session-start.py`** — thin shims → `postcommit hook …`, sharing `hooks/_adapter.py` (forwards stdin, falls back to `python -m postcommit`).

See [[Hooks]] for what they do.

## The agent
- **`agents/post-writer.md`** — the writer subagent → [[Post-Writer Agent]].

## Distribution
Two pieces: install the CLI (`uv tool install postcommit`) so the adapters have something to call, then install the plugin (`/plugin marketplace add AvivVegh/postcommit` → `/plugin install postcommit`). The `settings.json` surgery in `link-local.sh` is only for local iteration, never for the published plugin. See [[Install and Distribution]].

## Related
[[Architecture]] · [[CLI]] · [[Data Flow]]
