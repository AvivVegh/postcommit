# postcommit

A Claude Code plugin that turns real dev work — git history + Claude Code session transcripts — into candidate LinkedIn posts.

Local-only. Manually triggered. Nothing leaves your machine.

## Phase 0 status: proving the wedge

The whole point of this build is one experiment: **does feeding the tool the real work (git diff + session transcript) produce a LinkedIn post that's meaningfully better than just asking Claude, in the same session, "write a post about what we just did"?**

If yes, there's a product. If a 30-second DIY ask gets ~90% of the way there, there isn't. So Phase 0 is deliberately the least possible thing.

## What's in the box

```
.claude-plugin/plugin.json          # minimal manifest (Phase 2 packaging)
commands/post.md                    # /post <window> — the manual trigger
skills/postcommit-extract/SKILL.md  # extraction how-to (git + JSONL parser)
agents/post-writer.md               # the crown-jewels prompt (LinkedIn taste)
```

## How to run the specificity test

1. Do real work in a repo with Claude Code (bug fix, feature, refactor).
2. When done, run:
   ```
   /post 1d
   ```
   (or `/post HEAD~3..HEAD`, or `/post since=2026-07-01`)
3. Drafts save to `.postcommit/drafts/<UTC-ISO>.md` and open in your editor.
4. In the same Claude Code session, also ask: `Write a LinkedIn post about what we just did.` — this is the DIY baseline.
5. Compare honestly. Is the tool's output clearly better? Would you post it? Would you post the DIY one?

If tool ≫ DIY → Phase 1. If tool ≈ DIY → stop and rethink.

## Design notes

- **The subagent prompt is the whole product.** `agents/post-writer.md` is the taste/template layer — the file that decides whether a draft feels human or slop. Iterate there first.
- **Three fixed angles** (debugging story / counterintuitive lesson / tiny tool share) so A/B comparison is apples-to-apples. Consider going dynamic only after the fixed angles have proven the wedge.
- **Skill vs command vs subagent split** — the command is a thin dispatcher, the skill is the extractor (deterministic, mechanical), the subagent is the writer (creative, opinionated). Keep those boundaries clean when editing.
- **Privacy by design.** Extraction masks secrets, caps diff size, skips sidechain records, and never touches the network. The Phase 3 posting MCP will only ever send **approved draft text** — not raw code or transcripts.

## Roadmap

- **Phase 0 (this)** — Manual `/post <window>`, three fixed-angle candidates saved to disk. Prove the wedge.
- **Phase 1** — Two hooks: `SessionEnd` stages a recommendation if the session was post-worthy; `SessionStart` surfaces it as an ambient nudge. Gated (once/day, cooldown, snooze, unposted-work-only, instant file-read only).
- **Phase 2** — Package as an installable Claude Code plugin + a small marketplace repo.
- **Phase 3 (later)** — Paid layer: MCP server for scheduling and posting approved drafts to LinkedIn. Draft-first, never silent.
