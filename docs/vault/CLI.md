---
tags: [component, code]
aliases: [__main__.py, postcommit CLI]
---

# CLI

**File:** `postcommit/__main__.py` (~135 lines) · **Entry point:** `postcommit` (also `python -m postcommit`)

argparse dispatch over the four subcommands. Thin — each `cmd_*` imports its module lazily and delegates.

## Subcommands

| Command | Delegates to | Notes |
|---|---|---|
| `postcommit extract <window>` | [[Extractor]] `build_bundle` | emits the work bundle to stdout; `WindowError`→exit 2, `NotARepoError`→exit 1 |
| `postcommit state [verb]` | [[State]] verbs | `show`(default) / `snooze [N]` / `unsnooze` / `mark-posted` / `stage-fake` / `reset` |
| `postcommit hook <event>` | [[Hooks]] | `session-end` / `session-start`; reads the hook payload as JSON on **stdin** |
| `postcommit install [--claude]` | [[Install and Distribution\|install.py]] | writes the skill adapter into a host |
| `postcommit --version` | — | prints the package version |

## The `hook` verb contract

> [!important]
> `cmd_hook` wraps everything in `try/except: pass` and always returns 0 — **a broken hook must never break a user's session.** For `session-start` it emits the Claude Code `hookSpecificOutput` / `additionalContext` JSON envelope when [[Hooks|handle_session_start]] returns a nudge.

There is a **second** entry point, `postcommit-mcp` → [[MCP Server]] (`serve.py`), gated behind the `[mcp]` extra.

## Tests
`tests/test_cli.py` — argparse dispatch, MCP graceful-degrade, install.

## Related
[[Extractor]] · [[State]] · [[Hooks]] · [[Install and Distribution]]
