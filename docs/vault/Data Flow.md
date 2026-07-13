---
tags: [concept, architecture]
---

# Data Flow

Two flows share the same deterministic core: the **manual `/post`** flow and the **ambient habit loop**.

## Manual flow — `/post <window>`

```
/post <window>            commands/post.md — thin dispatcher (Plugin Surface)
  │
  ├─▶ extract skill        skills/postcommit-extract/SKILL.md
  │      │
  │      └─▶ postcommit extract <window>     Extractor (deterministic)
  │              → parse window → gather git → locate + distill transcripts
  │              → mask secrets, cap diff → emit work bundle (markdown)
  │
  ├─▶ model fills "Candidate signal"   (the one judgment call, left as a stub)
  │
  ├─▶ post-writer subagent             Post-Writer Agent (creative)
  │      → 3 candidate drafts (fixed angles A/B/C)
  │
  ├─▶ save to .postcommit/drafts/<UTC-ISO>.md   (colons → dashes)
  └─▶ open <path>
```

Steps: [[Plugin Surface]] → [[Extractor]] → model → [[Post-Writer Agent]] → disk → editor.

> [!important] The stub handoff
> `postcommit extract` emits **facts** deterministically and leaves a "Candidate signal" section blank (Problem / obvious-but-wrong move / real fix / surprising bit / lesson). The `/post` flow (or the human) fills it from the narrative before handing off to the writer. This is the seam between the two [[Architecture|layers]].

## Ambient flow — the habit loop

Same deterministic logic ([[Hooks]] / [[Scoring]] / [[State]]), reached through the thin `hooks/` shims:

```
SessionEnd    → score the session (no model call) → stage recommendation.json  if post-worthy
SessionStart  → read recommendation → surface an ambient nudge  (hard-gated, once/day)
```

See [[Hooks]] for the gates and [[Scoring]] for the signals.

## Related
[[Architecture]] · [[Privacy Model]] · [[Overview]]
