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
.claude-plugin/plugin.json          # plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json     # self-hosted marketplace listing this plugin
commands/post.md                    # /post <window> — the manual trigger (thin dispatcher)
skills/postcommit-extract/SKILL.md  # extractor: git + JSONL session parser → work bundle
agents/post-writer.md               # the writer subagent — LinkedIn taste/template layer
hooks/hooks.json                    # declares SessionEnd/SessionStart (auto-registered on install)
scripts/link-local.sh               # dev-only: symlink command/skill/agent into ~/.claude/ for local iteration
scripts/run-tests.sh                # run the stdlib unittest suite (python3 -m unittest)
tests/                              # unittest suite for the Python hooks (see below)
README.md                           # product framing, roadmap, how to run the wedge test
.gitignore                          # ignores .postcommit/ (generated drafts) and .DS_Store
```

Packaging note: the plugin is installed via `/plugin marketplace add AvivVegh/postcommit`
then `/plugin install postcommit`. Hooks are registered from `hooks/hooks.json` using
`${CLAUDE_PLUGIN_ROOT}` and removed automatically on uninstall — the `settings.json`
surgery in `link-local.sh` is only for local symlink-based iteration, never for the
published plugin.

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

There is no build step — the product surface is Markdown prompt files. The only
executable code is the Python hooks (plus two Bash scripts), and that code has a
unit test suite. The three prompt files are still "tested" by hand: the wedge
experiment (see README) and the interactive install QA in `docs/smoke-test.md`.

- Tests: `scripts/run-tests.sh` (or `python3 -m unittest discover -s tests`) runs
  the suite. It is **stdlib-only `unittest`** — no pytest, no pip install — to match
  the hooks' dependency-free rule. Coverage lives under `tests/`:
  `test_postcommit_state.py` (time/json/watermark/git helpers + the CLI verbs),
  `test_session_end.py` (scoring, transcript parsing, shortstat parsing, and the
  end-to-end recommendation staging), and `test_session_start.py` (the nudge text
  plus all five SessionStart gates). `tests/_support.py` loads the hyphen-named hook
  modules via importlib and builds throwaway git repos / transcript JSONLs. Tests
  that touch git shell out to real `git`, and the SessionStart/SessionEnd hooks run
  as subprocesses with `HOME` pointed at a temp dir so the global cooldown file
  stays sandboxed. Add a test alongside any change to hook logic.
- CI: `.github/workflows/ci.yml` runs on every push/PR to `main`. The `validate`
  job automates the `docs/smoke-test.md` pre-flight — manifests parse as JSON, the
  hook scripts named in `hooks/hooks.json` exist and are `+x`, the three hooks
  byte-compile (`py_compile`), the `unittest` suite passes, and the Bash scripts
  pass `shellcheck`. `security-scan` runs `bandit -r hooks -ll` (non-blocking for
  now). `version-guard` fires on a published release and asserts the git tag equals
  `plugin.json` `version`. Keep CI green; `validate` is required before merge to `main`.
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
- **Conventional commits and branches.** Both carry a type prefix — one of `feat`,
  `fix`, `add`, `docs`, `chore`, `refactor`, `ci`. Commit subjects use
  `type(scope): summary` (scope optional, imperative, no trailing period), e.g.
  `feat(ci): add GitHub Actions workflow` or `fix(hooks): handle empty transcript`.
  Branches use `type/short-desc`, e.g. `feat/ci-workflow`, `docs/commit-conventions`.
  Not the old `phase-*` naming.

## Non-obvious details

- Session transcripts live at `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`, where
  `<encoded-cwd>` is the absolute cwd with every `/` replaced by `-` and a leading `-`.
  The extract skill filters records by `.timestamp` against the window cutoff.
- The window argument accepts durations (`1d`, `4h`, `30m`), `today`, git ranges
  (`HEAD~3..HEAD`, `main..HEAD`, `<sha>..<sha>`), and `since=YYYY-MM-DD`.
- Branching/PR flow: trunk-based on `main`. Do work on a short-lived, conventionally
  named branch (`type/short-desc` — see Conventions above) and merge it via PR into
  `main`; there is no long-lived `dev` branch. `main` is protected — the `validate` CI
  job must be green before merge. Releases are cut from `main` by tagging `vX.Y.Z`
  (matching `plugin.json` `version`), which the `version-guard` job enforces.
