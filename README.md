# postcommit

A Claude Code plugin that turns real dev work — git history + Claude Code session transcripts — into candidate LinkedIn posts.

Local-only. Manually triggered. Nothing leaves your machine.

## Phase 0 status: proving the wedge

The whole point of this build is one experiment: **does feeding the tool the real work (git diff + session transcript) produce a LinkedIn post that's meaningfully better than just asking Claude, in the same session, "write a post about what we just did"?**

If yes, there's a product. If a 30-second DIY ask gets ~90% of the way there, there isn't. So Phase 0 is deliberately the least possible thing.

## What's in the box

postcommit is now **code-first**: an installable Python package does the real work,
and the Claude Code plugin (command / skill / agent / hooks) is a thin adapter that
shells out to the installed `postcommit` CLI.

```
pyproject.toml                      # installable package (uv/pip); entry points below
uv.lock                             # pinned resolution
postcommit/                         # the package — all the real logic
  __main__.py                       #   `postcommit` CLI: extract, state, hook, install
  extract.py                        #   deterministic git + session-transcript → work bundle
  scoring.py                        #   post-worthiness signals + scoring
  state.py                          #   per-repo/global state (watermark, snooze, rec)
  hooks.py                          #   SessionEnd / SessionStart logic
  serve.py                          #   `postcommit-mcp` MCP server (optional extra)
  install.py                        #   write the skill adapter into a host (~/.claude)
  data/skill.md                     #   the thin skill adapter, shipped as package data
.claude-plugin/plugin.json          # plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json     # self-hosted marketplace listing
commands/post.md                    # /post <window> — the manual trigger
commands/post-snooze.md             # /post-snooze [days] — hush the nudge
skills/postcommit-extract/SKILL.md  # thin skill adapter (runs `postcommit extract`)
agents/post-writer.md               # the crown-jewels prompt (LinkedIn taste)
hooks/hooks.json                    # declares the two hooks (auto-registered on install)
hooks/session-end.py                # thin shim → `postcommit hook session-end`
hooks/session-start.py              # thin shim → `postcommit hook session-start`
hooks/_adapter.py                   # shared forwarding logic for the two shims
tests/                              # stdlib unittest suite for the package
scripts/link-local.sh               # dev-only: uv-install editable + symlink + hooks
```

**Entry points:** `postcommit` (the CLI) and `postcommit-mcp` (the MCP server, needs
the `[mcp]` extra).

## Install

**Two pieces:** the Python package (does the work) and the Claude Code plugin (wires
`/post`, the skill, and the hooks into Claude Code, all of which call the package).

1. Install the CLI:

   ```
   uv tool install postcommit
   # or: pip install postcommit  /  pipx install postcommit
   # MCP server too:  uv tool install 'postcommit[mcp]'
   ```

   The core is dependency-free. `postcommit --version` should now work on your PATH.

2. Install the Claude Code plugin. This repo is its own plugin marketplace:

   ```
   /plugin marketplace add AvivVegh/postcommit
   /plugin install postcommit
   ```

   This registers the `/post` and `/post-snooze` commands, the extract skill, the
   post-writer subagent, and the two hooks (via `hooks/hooks.json`). Those adapters
   shell out to the `postcommit` CLI from step 1. Uninstalling removes all of them —
   including the hooks — automatically. No manual `settings.json` editing.

To update later: `uv tool upgrade postcommit` for the CLI, and
`/plugin update postcommit` for the plugin (picks up a new `version` in the manifest).

## Install (local, for iteration)

For hacking on postcommit itself without publishing:

```
scripts/link-local.sh          # uv-install editable + symlink command/skill/agent + register hooks
scripts/link-local.sh --unlink # undo
```

This installs the package as an **editable** `uv` tool (so `postcommit` tracks your
checkout — edit `postcommit/*.py` and the CLI picks it up immediately), symlinks the
command/skill/subagent into `~/.claude/`, and registers the thin hooks. Requires `uv`
(or install the package yourself with `pip install -e .`). Idempotent; won't overwrite
non-symlink files. Restart Claude Code once after linking. Use this **or** the plugin
install above, not both at once — they register the same hooks two different ways.

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

- **`SessionEnd`** (`postcommit.hooks`, via the `hooks/session-end.py` shim) — when a session closes, it cheaply and
  deterministically (no model call) scores whether the work was post-worthy from git
  (commits/churn since the last post) + transcript signals (real prompts, edits,
  duration, debugging keywords). If it clears the threshold, it stages a lightweight
  recommendation to `.postcommit/state/recommendation.json`. Idempotent, once per
  session. If you already ran `/post` this session, it instead advances the watermark
  so you won't be nudged about work you already acted on.
- **`SessionStart`** (`postcommit.hooks`, via the `hooks/session-start.py` shim) — on a fresh start (`startup`/`clear`,
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
- `postcommit state show` inspects all state.
  `snooze` / `unsnooze` / `mark-posted` / `reset` are also available as
  `postcommit state <verb>`.

Installing (via `scripts/link-local.sh`) installs the editable CLI and registers both
hooks in `~/.claude/settings.json` (backed up to `settings.json.bak` first). `--unlink`
removes all of it.

## Design notes

- **The subagent prompt is the whole product.** `agents/post-writer.md` is the taste/template layer — the file that decides whether a draft feels human or slop. Iterate there first.
- **Three fixed angles** (debugging story / counterintuitive lesson / tiny tool share) so A/B comparison is apples-to-apples. Consider going dynamic only after the fixed angles have proven the wedge.
- **Code-first, thin adapters.** The deterministic work (extraction, scoring, state) lives in the `postcommit` Python package. The command is a thin dispatcher, the skill/hooks are thin shims that call the CLI, and the subagent is the writer (creative, opinionated). Keep those boundaries clean when editing.
- **Privacy by design.** Extraction masks secrets, caps diff size, skips sidechain records, and never touches the network. The Phase 3 posting MCP will only ever send **approved draft text** — not raw code or transcripts.

## Roadmap

- **Phase 0 (this)** — Manual `/post <window>`, three fixed-angle candidates saved to disk. Prove the wedge.
- **Phase 1 (this)** — Two hooks: `SessionEnd` stages a recommendation if the session was post-worthy; `SessionStart` surfaces it as an ambient nudge. Gated (once/day cooldown, snooze, unposted-work-only, startup/clear only, instant file-read only).
- **Phase 2** — Package as an installable Claude Code plugin + a small marketplace repo.
- **Graphify-style repackaging (done)** — Move the real logic out of prompts/hooks into an installable Python package (`uv tool install postcommit`) with a `postcommit` CLI, a `postcommit-mcp` server, and a test suite. The skill/hooks became thin adapters over the CLI, unlocking version pinning, reuse outside Claude Code, and multi-host support.
- **Phase 3 (later)** — Paid layer: MCP server for scheduling and posting approved drafts to LinkedIn. Draft-first, never silent.
