---
tags: [concept, product]
aliases: [phases, the wedge]
---

# Roadmap

## The wedge (the whole point)

> [!question] The one experiment
> Does feeding the tool the **real work** (git diff + [[Session Transcripts|session transcript]]) produce a LinkedIn post **meaningfully better** than just asking Claude, in the same session, "write a post about what we just did"?
>
> If tool ≫ DIY → Phase 1. If tool ≈ DIY → stop and rethink. Keep *this* — not feature breadth — as the north star.

### How to run it
1. Do real work in a repo with Claude Code.
2. `/post 1d` (or `/post HEAD~3..HEAD`, `/post since=2026-07-01`) → 3 drafts saved to `.postcommit/drafts/` and opened.
3. In the same session, also ask "Write a LinkedIn post about what we just did." — the DIY baseline.
4. Compare honestly. Would you post the tool's output? The DIY one?

This is why the [[Post-Writer Agent|writer]] uses **three fixed angles** — apples-to-apples comparison.

## Phases

- **Phase 0** — Manual `/post <window>`, 3 fixed-angle candidates saved to disk. Prove the wedge. → [[Data Flow]]
- **Phase 1** — The [[Hooks|habit loop]]: `SessionEnd` stages a recommendation if post-worthy; `SessionStart` surfaces it as a gated ambient nudge.
- **Phase 2** — Package as an installable plugin + a marketplace repo. → [[Install and Distribution]]
- **Graphify-style repackaging (done)** — Move the real logic into an installable Python package with a `postcommit` [[CLI]], a [[MCP Server|`postcommit-mcp`]] server, and a test suite. Adapters became thin.
- **Phase 3 (later)** — Paid layer: an MCP server for scheduling and posting **approved drafts** to LinkedIn. Draft-first, never silent. Lives in a **separate repo**; the interface is the draft-file format. Only ever sends approved draft text (see [[Privacy Model]]).

## Related
[[Overview]] · [[Architecture]] · [[Post-Writer Agent]]
