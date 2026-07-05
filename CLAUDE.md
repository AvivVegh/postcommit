# CLAUDE.md

Guidance for Claude Code when working in the **postcommit** repo.

## Project overview

postcommit is a **Claude Code plugin** that turns real dev work — git history plus
Claude Code session transcripts — into candidate LinkedIn posts. It runs entirely
locally, is triggered manually via `/post`, and never sends anything off the machine.

The project is deliberately minimal. Phase 0 exists to answer one question: does
feeding the tool the *real* work (git diff + session transcript) produce a post
meaningfully better than just asking Claude, in the same session, "write a post about
what we just did"? If a 30-second DIY ask gets ~90% of the way there, there is no
product. Keep that experiment — not feature breadth — as the north star.

## Repository layout

```
.claude-plugin/plugin.json          # plugin manifest (name, description, version)
commands/post.md                    # /post <window> — the manual trigger (thin dispatcher)
skills/postcommit-extract/SKILL.md  # extractor: git + JSONL session parser → work bundle
agents/post-writer.md               # the writer subagent — LinkedIn taste/template layer
scripts/link-local.sh               # symlink command/skill/agent into ~/.claude/ for local iteration
README.md                           # product framing, roadmap, how to run the wedge test
.gitignore                          # ignores .postcommit/ (generated drafts) and .DS_Store
```

## The three-part architecture (keep these boundaries clean)

The whole plugin is prompt engineering — three Markdown files with distinct jobs.
When editing, respect the split:

- **`commands/post.md` — the dispatcher.** Thin. Parses the window argument, invokes
  the extract skill, hands the bundle to the subagent, saves the result to
  `.postcommit/drafts/<UTC-ISO>.md`, and opens it. No creative or extraction logic here.
- **`skills/postcommit-extract/SKILL.md` — the extractor.** Deterministic and
  mechanical. Parses the git range and Claude Code session JSONLs into a compact
  "work bundle." This is where privacy rules live (mask secrets, cap diff size, skip
  sidechain/subagent records, no network).
- **`agents/post-writer.md` — the writer.** Creative and opinionated. This is the
  crown jewel — the file that decides whether a draft reads human or like slop.
  **Iterate here first** when improving output quality.

Data flow: `/post <window>` → extract skill → work bundle (markdown) → post-writer
subagent → 3 candidate drafts → saved to disk → opened in editor.

## Build / test / lint

There is no build step, test suite, or linter — the plugin is Markdown prompt files
plus one Bash script. "Testing" is running the wedge experiment by hand (see README).

- `scripts/link-local.sh` — symlink `commands/`, `skills/`, `agents/` into `~/.claude/`
  so `/post` works in Claude Code without publishing. Idempotent; refuses to overwrite
  non-symlink files. Restart Claude Code once after linking.
- `scripts/link-local.sh --unlink` — remove those symlinks.
- The script is `set -euo pipefail`; keep it POSIX-friendly Bash and idempotent.

## Conventions and idioms

- **Prompts are the product.** Behavior changes are edits to the three Markdown files,
  not code. Be precise: these files are read literally by the model at runtime.
- **Fixed angles, on purpose.** The writer always produces exactly 3 candidates in the
  same three angles (debugging story / counterintuitive lesson / tiny tool share) so
  A/B comparison against the DIY baseline stays apples-to-apples. Don't make them
  dynamic until the fixed angles have proven the wedge.
- **Privacy is non-negotiable.** Everything runs locally. Never add a step that sends
  transcripts, diffs, or drafts over the network. Extraction masks secrets, caps diff
  size (~40k chars), keeps ≤10 lines per code snippet, and skips `isSidechain` records.
- **No fabrication.** The writer must never invent numbers, timings, error messages, or
  file names not present in the bundle. Preserve this rule in any edit to the writer.
- **Generated output** lands in `.postcommit/` (git-ignored). Drafts are named by UTC
  ISO timestamp with colons replaced by dashes for filesystem safety.

## Non-obvious details

- Session transcripts live at `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`, where
  `<encoded-cwd>` is the absolute cwd with every `/` replaced by `-` and a leading `-`.
  The extract skill filters records by `.timestamp` against the window cutoff.
- The window argument accepts durations (`1d`, `4h`, `30m`), `today`, git ranges
  (`HEAD~3..HEAD`, `main..HEAD`, `<sha>..<sha>`), and `since=YYYY-MM-DD`.
- Branching/PR flow: Phase work is done on `phase-*` branches and merged via PR into
  `dev`; `main` is the release branch. Target `dev` for ongoing work.

## Roadmap context

- **Phase 0 (current)** — manual `/post <window>`, 3 fixed-angle candidates to disk.
- **Phase 1** — `SessionEnd`/`SessionStart` hooks that stage and surface a nudge, gated.
- **Phase 2** — package as an installable plugin + a small marketplace repo.
- **Phase 3** — paid MCP layer to schedule/post approved drafts (draft-first, never silent).
