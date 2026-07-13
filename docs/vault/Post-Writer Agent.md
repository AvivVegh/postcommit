---
tags: [prompt-layer, crown-jewel]
aliases: [post-writer, writer subagent]
---

# Post-Writer Agent

**File:** `agents/post-writer.md` · **Layer:** prompt / taste (see [[Architecture]])

> [!tip] The crown jewel
> This is the file that decides whether a draft reads human or like slop. **Iterate here first** when improving output quality. It is read literally by the model at runtime.

Given a [[Extractor|work bundle]], it produces **3 candidate LinkedIn posts** that "could only have been written by someone who did the work." Uses no tools, asks no clarifying questions — reads the bundle, drafts, returns raw markdown.

## Fixed angles (on purpose)

Always exactly 3 candidates in the **same three angles**, so A/B comparison against the DIY baseline stays apples-to-apples (see [[Roadmap|the wedge]]):

- **A — The debugging story.** Chronological, opens on a concrete moment.
- **B — The counterintuitive lesson.** Leads with the surprising finding.
- **C — The tiny tool / pattern share.** Focuses on the reusable artifact.

Don't make them dynamic until the fixed angles have proven the wedge.

## Its taste rules (abridged)
- First ~140 chars earn the click; specific, curiosity-shaped promise; no throat-clearing, no 🚀.
- 120–220 words, generous line breaks, one stealable takeaway, no body links, ≤1–3 hashtags.
- Kills: generic advice, LLM tells ("dive in", "game-changer", "journey"), hero narrative, vague verbs.

## No fabrication (invariant)
> [!danger] Preserve in any edit
> The writer must **never invent** numbers, timings, error messages, or file names not present in the bundle. When unsure, stay vague rather than invent. This is part of the [[Privacy Model|no-fabrication rule]].

## Mining the bundle
It extracts five atoms — problem / obvious-but-wrong move / real fix / surprising bit / transferable lesson — treating the bundle's **Candidate signal** section (the [[Extractor|deterministic stub]], filled by the [[Data Flow|/post flow]]) as a starting point, not a ceiling.

## How it's invoked
Dispatched by `commands/post.md` via the Agent tool (`subagent_type: post-writer`). See [[Plugin Surface]] and [[Data Flow]].

## Related
[[Plugin Surface]] · [[Data Flow]] · [[Roadmap]]
