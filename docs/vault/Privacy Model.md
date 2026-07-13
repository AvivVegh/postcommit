---
tags: [concept, invariant]
aliases: [privacy, secret masking]
---

# Privacy Model

> [!danger] Non-negotiable
> Everything runs **locally**. Never add a step that sends transcripts, diffs, or drafts over the network. This is the whole trust story of the product.

## The invariants

1. **No network, ever.** The core is stdlib-only (`uv.lock` pins the resolution) — that's the privacy *and* portability guarantee. Keep the core stdlib-only. Even the [[MCP Server]] only reads local files.
2. **Mask secrets.** The [[Extractor]]'s `scrub_text()` is the single choke point — everything user-authored or transcript-derived passes through it. Redacts `key=value` secrets, URL creds, `Bearer <token>`, and known token shapes (`sk-`, `gh?_`, `AKIA`, `xox?`, JWT). `mask_secrets()` drops sensitive-file bodies (`.env`, `*.pem/key/p12/pfx`, `credentials*`, `secrets*`) wholesale.
3. **Cap the diff** at ~40k chars (`cap_diff`), keeping ≤10 lines per code snippet in the distilled narrative.
4. **Skip sidechain records** (`isSidechain`) — see [[Session Transcripts]].
5. **No fabrication.** The [[Post-Writer Agent]] must never invent numbers, timings, error messages, or file names not in the bundle. Preserve this in any writer edit.
6. **Generated output is local + gitignored.** Drafts land in `.postcommit/drafts/`; [[State|state]] lives in `.postcommit/state/` and `~/.postcommit/`. All gitignored — per-repo state never leaks.

## The `/post` command re-checks
`commands/post.md` explicitly double-checks for anything secret-looking and re-masks before dispatching, even though the [[Extractor]] should already have masked it.

## Phase 3 boundary
The future paid posting MCP (see [[Roadmap]], separate repo) will only ever send **approved draft text** — never raw code or transcripts.

## Related
[[Extractor]] · [[Post-Writer Agent]] · [[Session Transcripts]] · [[Architecture]]
