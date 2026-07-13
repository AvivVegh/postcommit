---
tags: [concept, architecture]
---

# Architecture

postcommit is **code-first**: an installable Python package (`postcommit/`) holds the real logic, and the Claude Code plugin surface (command / skill / agent / hooks) are thin adapters that shell out to the installed `postcommit` CLI. This mirrors *graphify*.

## Two layers, kept clean

> [!note] Boundary
> **Deterministic code** does the mechanical, testable work. **Prompt/taste** does the creative, opinionated work. The command/skill/hooks are thin glue between them. Keep these boundaries clean when editing.

### Layer 1 — deterministic code (the `postcommit` package)
Everything here is unit-tested, no model calls, no network.
- [[Extractor]] (`extract.py`) — window → work bundle. Owns the [[Privacy Model|privacy rules]]. The one judgment call ("Candidate signal") is left as a **stub** for the model to fill so this stays fully deterministic.
- [[Scoring]] (`scoring.py`) — cheap post-worthiness signals.
- [[State]] (`state.py`) — time/paths/json/watermark/git helpers + `state` verbs.
- [[Hooks]] (`hooks.py`) — SessionEnd / SessionStart logic.
- [[CLI]] (`__main__.py`) — dispatch: `extract | state | hook | install`.
- [[MCP Server]] (`serve.py`) — optional `postcommit-mcp`.

### Layer 2 — prompt / taste
Read literally by the model at runtime. **This is the product.**
- [[Post-Writer Agent]] (`agents/post-writer.md`) — the crown jewel; decides whether a draft reads human or like slop. **Iterate here first.**
- [[Plugin Surface]] — dispatcher (`commands/post.md`), skill adapter, hooks manifest.

## Why code-first

Moving the real logic out of prompts/hooks into an installable package (`uv tool install postcommit`) unlocked version pinning, reuse outside Claude Code, and multi-host support. The skill/hooks became thin adapters over the CLI.

## Mirror invariant

`skills/postcommit-extract/SKILL.md` is a **byte-for-byte mirror** of `postcommit/data/skill.md` — keep them identical. The package-data copy is what `postcommit install` writes into other hosts. See [[Plugin Surface]] and [[Install and Distribution]].

## Related
[[Data Flow]] · [[Overview]]
