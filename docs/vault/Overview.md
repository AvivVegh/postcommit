---
tags: [moc, postcommit]
aliases: [Home, postcommit, Map of Content]
---

# postcommit — Overview

> [!abstract] What it is
> **postcommit** is a [[Plugin Surface|Claude Code plugin]] that turns real dev work — git history plus Claude Code session transcripts — into candidate LinkedIn posts. It runs **entirely locally**, is triggered manually via `/post`, and never sends anything off the machine.

The project is deliberately minimal. **Phase 0** exists to answer one question (see [[Roadmap]]): does feeding the tool the *real* work produce a post meaningfully better than just asking Claude, in the same session, "write a post about what we just did"? If a 30-second DIY ask gets ~90% of the way there, there is no product. That **wedge experiment** — not feature breadth — is the north star.

Version: **0.2.0** · stdlib-only core · Python ≥3.9

## The map

### Two layers ([[Architecture]])
- **Deterministic code** — the `postcommit` Python package
  - [[Extractor]] — git + transcripts → work bundle
  - [[Scoring]] — cheap post-worthiness signals
  - [[State]] — time/paths/json/watermark/git helpers
  - [[Hooks]] — SessionEnd / SessionStart habit loop
  - [[CLI]] — the `postcommit` entry point
  - [[MCP Server]] — optional `postcommit-mcp`
- **Prompt / taste** — read literally by the model at runtime
  - [[Post-Writer Agent]] — the crown jewel
  - [[Plugin Surface]] — commands, skill adapter, hooks manifest

### Cross-cutting
- [[Data Flow]] — how a `/post` becomes 3 drafts
- [[Privacy Model]] — the non-negotiable invariants
- [[Testing and CI]] — how the code surface is verified
- [[Install and Distribution]] — the two-piece install
- [[Roadmap]] — phases 0→3 and the wedge

## The core boundary to keep clean

```
/post <window>
  → extract skill  → postcommit extract  (deterministic bundle)
  → model fills "Candidate signal"
  → post-writer subagent  → 3 candidate drafts
  → saved to .postcommit/drafts/<UTC-ISO>.md  → opened
```

**Prompts are the product.** Behavior changes are edits to the three Markdown files ([[Post-Writer Agent]], the dispatcher, the skill adapter), not code. Iterate on the [[Post-Writer Agent]] first when improving output quality.
