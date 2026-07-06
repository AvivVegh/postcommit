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
commands/post-snooze.md             # /post-snooze [days] — hush the nudge
skills/postcommit-extract/SKILL.md  # extraction how-to (git + JSONL parser)
agents/post-writer.md               # the crown-jewels prompt (LinkedIn taste)
hooks/session-end.py                # Phase 1: stage a recommendation if post-worthy
hooks/session-start.py              # Phase 1: surface it as an ambient nudge
hooks/postcommit_state.py           # Phase 1: state lib + CLI (watermark/snooze)
scripts/link-local.sh               # symlink into ~/.claude/ + register hooks
```

## Install (local, for iteration)

```
scripts/link-local.sh          # symlink command/skill/subagent into ~/.claude/
scripts/link-local.sh --unlink # undo
```

Idempotent. Won't overwrite non-symlink files. Restart Claude Code once after linking; from then on, edits in this repo take effect on the next `/post` invocation.

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

## Phase 1: the habit loop (hooks)

The goal of Phase 1 is to stop relying on you remembering `/post`. Two Claude Code
hooks make the recommendation ambient:

- **`SessionEnd`** (`hooks/session-end.py`) — when a session closes, it cheaply and
  deterministically (no model call) scores whether the work was post-worthy from git
  (commits/churn since the last post) + transcript signals (real prompts, edits,
  duration, debugging keywords). If it clears the threshold, it stages a lightweight
  recommendation to `.postcommit/state/recommendation.json`. Idempotent, once per
  session. If you already ran `/post` this session, it instead advances the watermark
  so you won't be nudged about work you already acted on.
- **`SessionStart`** (`hooks/session-start.py`) — on a fresh start (`startup`/`clear`,
  never `resume`), it reads the staged recommendation and surfaces it as an ambient
  nudge. It is **instant** (file reads only, never generates) and hard-gated:
  - only if there's unposted post-worthy work
  - at most once per calendar day (global cooldown, `~/.postcommit/nudge-state.json`)
  - not while snoozed

### State

- `.postcommit/state/recommendation.json` — the staged nudge (per repo).
- `.postcommit/state/watermark.json` — what's already processed/posted, plus snooze
  (per repo). Both live under the already-gitignored `.postcommit/`.
- `~/.postcommit/nudge-state.json` — the global once-per-day cooldown.

### Controlling nudges

- `/post` acts on the recommendation (and clears it).
- `/post-snooze [days]` hushes nudges for this repo (default 3 days).
- `python3 ~/.postcommit/bin/postcommit-state show` inspects all state.
  `snooze` / `unsnooze` / `mark-posted` / `reset` are also available.

Installing (via `scripts/link-local.sh`) registers both hooks in
`~/.claude/settings.json` (backed up to `settings.json.bak` first) and symlinks the
state CLI to `~/.postcommit/bin/postcommit-state`. `--unlink` removes all of it.

## Design notes

- **The subagent prompt is the whole product.** `agents/post-writer.md` is the taste/template layer — the file that decides whether a draft feels human or slop. Iterate there first.
- **Three fixed angles** (debugging story / counterintuitive lesson / tiny tool share) so A/B comparison is apples-to-apples. Consider going dynamic only after the fixed angles have proven the wedge.
- **Skill vs command vs subagent split** — the command is a thin dispatcher, the skill is the extractor (deterministic, mechanical), the subagent is the writer (creative, opinionated). Keep those boundaries clean when editing.
- **Privacy by design.** Extraction masks secrets, caps diff size, skips sidechain records, and never touches the network. The Phase 3 posting MCP will only ever send **approved draft text** — not raw code or transcripts.

## Roadmap

- **Phase 0 (this)** — Manual `/post <window>`, three fixed-angle candidates saved to disk. Prove the wedge.
- **Phase 1 (this)** — Two hooks: `SessionEnd` stages a recommendation if the session was post-worthy; `SessionStart` surfaces it as an ambient nudge. Gated (once/day cooldown, snooze, unposted-work-only, startup/clear only, instant file-read only).
- **Phase 2** — Package as an installable Claude Code plugin + a small marketplace repo.
- **Phase 3 (later)** — Paid layer: MCP server for scheduling and posting approved drafts to LinkedIn. Draft-first, never silent.
