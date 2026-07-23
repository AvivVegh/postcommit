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

postcommit is **code-first**: an installable Python package (`postcommit/`) holds the
real logic, and the Claude Code plugin surface (command/skill/agent/hooks) are thin
adapters that shell out to the installed `postcommit` CLI. This mirrors graphify.

```
pyproject.toml                      # installable package: [project.scripts] postcommit + postcommit-mcp + postcommit-cloud-mcp
uv.lock                             # pinned resolution (core is dependency-free; mcp is a 3.10+ extra)
postcommit/                         # the package — all deterministic logic lives here
  __main__.py                       #   `postcommit` CLI dispatch: extract | state | hook | install
  extract.py                        #   deterministic git + session-transcript → work bundle (ported SKILL.md)
  scoring.py                        #   post-worthiness signals + scoring (from the old session-end)
  state.py                          #   time/paths/json/watermark/git helpers + `state` verbs
  hooks.py                          #   handle_session_end / handle_session_start
  serve.py                          #   `postcommit-mcp` MCP server (optional [mcp] extra) — local only
  cloud_config.py                   #   cloud-client config from env (stdlib core)
  cloud_auth.py                     #   CredentialProvider seam: env/refresh id_token (stdlib core)
  cloud_client.py                   #   thin REST client for postcommit-cloud (stdlib urllib)
  serve_cloud.py                    #   `postcommit-cloud-mcp` MCP server (optional [cloud] extra) — network passthrough
  install.py                        #   write the skill adapter into a host (~/.claude)
  data/skill.md                     #   the thin skill adapter, shipped as package-data
.claude-plugin/plugin.json          # plugin manifest (name, version — kept in sync with pyproject)
.claude-plugin/marketplace.json     # self-hosted marketplace listing this plugin
commands/post.md                    # /post <window> — the manual trigger (thin dispatcher)
commands/post-snooze.md             # /post-snooze [days] — hush the nudge
skills/postcommit-extract/SKILL.md  # thin skill adapter — mirror of postcommit/data/skill.md
agents/post-writer.md               # the writer subagent — LinkedIn taste/template layer
hooks/hooks.json                    # declares SessionEnd/SessionStart (auto-registered on install)
hooks/session-end.py                # thin shim → `postcommit hook session-end`
hooks/session-start.py              # thin shim → `postcommit hook session-start`
hooks/_adapter.py                   # shared forwarding logic for the two shims
scripts/link-local.sh               # dev-only: uv-install editable + symlink command/skill/agent + register hooks
scripts/run-tests.sh                # run the stdlib unittest suite (python3 -m unittest)
tests/                              # unittest suite for the package (see below)
README.md                           # product framing, roadmap, how to run the wedge test
.gitignore                          # ignores .postcommit/, build artifacts, tooling caches
```

Distribution is **single-install**: `/plugin marketplace add AvivVegh/postcommit` →
`/plugin install postcommit`. Installing a `source: "./"` plugin copies the *whole
repo* into `${CLAUDE_PLUGIN_ROOT}` — so the stdlib-only `postcommit/` package rides
along and runs via `python3 -m postcommit`; there is no separate `uv/pip` step (that
remains an optional fallback for python-less machines / non-Claude hosts). The CLI is
reached through a three-tier resolution — **PATH `postcommit` → the launcher at
`~/.postcommit/bin/postcommit` → `python3 -m postcommit`** — and the launcher is what
bridges the model-run `/post` path to the bundled package (see the architecture note
below). Hooks are registered from `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}` and
removed automatically on uninstall — the `settings.json` surgery in `link-local.sh` is
only for local iteration, never for the published plugin.
`skills/postcommit-extract/SKILL.md` is a byte-for-byte mirror of
`postcommit/data/skill.md`; keep them identical (the package-data copy is what
`postcommit install` writes into other hosts).

## The architecture (keep these boundaries clean)

Two layers: **deterministic code** (the `postcommit` package) and **prompt/taste**
(the writer subagent). The command/skill/hooks are thin glue between them.

- **`postcommit/extract.py` — the extractor (code).** Deterministic and mechanical:
  parses the window, gathers git state, locates and filters Claude Code session
  JSONLs, caps the diff, masks secrets, and emits the work bundle. This is where the
  privacy rules live (mask secrets, cap diff ~40k, ≤10 lines/snippet, skip sidechain
  records, no network). The one judgment call — the "Candidate signal" — is left as a
  stub for the model to fill.
- **`skills/postcommit-extract/SKILL.md` — the extractor adapter (prompt).** Thin:
  tells the model to run `postcommit extract <window>`, then fill the Candidate signal
  from the bundle. Mirrors `postcommit/data/skill.md`.
- **`commands/post.md` — the dispatcher (prompt).** Thin. Parses the window argument,
  invokes the extract skill, hands the bundle to the subagent, saves the result to
  `.postcommit/drafts/<UTC-ISO>.md`, and opens it. No creative or extraction logic.
- **`agents/post-writer.md` — the writer (prompt).** Creative and opinionated. This is
  the crown jewel — the file that decides whether a draft reads human or like slop.
  **Iterate here first** when improving output quality.

Data flow: `/post <window>` → extract skill → `postcommit extract` (deterministic
bundle) → model fills Candidate signal → post-writer subagent → 3 candidate drafts →
saved to disk → opened in editor. The SessionEnd/SessionStart habit-loop is the same
logic (`postcommit.hooks`/`scoring`/`state`), reached through the thin `hooks/` shims.

**Reaching the bundled CLI (single-install plumbing).** `${CLAUDE_PLUGIN_ROOT}` is only
available to hooks, *not* to the model-run command/skill. So the SessionStart hook
(`hooks._ensure_launcher`, called first in `handle_session_start`) writes a tiny
launcher to the fixed path `~/.postcommit/bin/postcommit` that `exec`s `python3 -m
postcommit` with `PYTHONPATH` pointed at the current plugin root. The extract skill then
resolves the CLI as PATH `postcommit` → that launcher → `python3 -m postcommit`. The
launcher is idempotent and rewritten only when the plugin root moves (upgrades). The
hook shims' `hooks/_adapter.py` mirrors the same fallback so the hooks themselves run
the bundled package without a PATH install.

## Build / test / lint

The executable surface is the `postcommit` Python package (plus the thin hook shims
and two Bash scripts). It has a unit test suite. The prompt files (writer, dispatcher,
skill adapter) are still "tested" by hand: the wedge experiment (see README) and the
interactive install QA in `docs/smoke-test.md`.

- **Build/install:** `uv build` produces the wheel/sdist; `uv tool install .` (or
  `pip install .`) installs the `postcommit` + `postcommit-mcp` entry points. The core
  is **dependency-free** (stdlib only) so it installs anywhere; the MCP server needs
  the `[mcp]` extra (`mcp>=1.2`, Python ≥3.10). `uv.lock` pins the resolution. Keep
  the core stdlib-only — that's the privacy/portability guarantee.
- **Tests:** `scripts/run-tests.sh` (or `python3 -m unittest discover -s tests`). It is
  **stdlib-only `unittest`** — no pytest, no pip install. Coverage under `tests/`:
  `test_postcommit_state.py` (time/json/watermark/git helpers + `state` verbs),
  `test_session_end.py` (scoring, transcript parsing, shortstat, end-to-end staging),
  `test_session_start.py` (nudge text + all five SessionStart gates),
  `test_extract.py` (window parsing, secret masking, diff cap, transcript distillation,
  bundle assembly), and `test_cli.py` (argparse dispatch, MCP graceful-degrade, install).
  `tests/_support.py` imports the package (putting the repo root on `sys.path`) and
  builds throwaway git repos / transcript JSONLs. `run_hook` drives the thin shims as
  subprocesses with `HOME` at a temp dir and `PYTHONPATH` at the checkout so the
  `python -m postcommit` fallback resolves. Add a test alongside any logic change.
- **Lint:** `ruff check postcommit tests hooks` (config in `pyproject.toml`: E/F/I/B;
  `UP` is intentionally off — the package uses `%`-formatting throughout, matching the
  code it was ported from). `bandit -r postcommit hooks` is the security lint.
- **CI:** `.github/workflows/ci.yml`. `validate` (required before merge) parses
  manifests, checks `plugin.json`/`pyproject.toml` versions agree, verifies the hooks
  in `hooks.json` exist + are `+x`, byte-compiles the hooks + package, installs the
  package and smoke-tests the CLI, runs `ruff` and the `unittest` suite, and
  `shellcheck`s the scripts. `test-matrix` reruns the suite on Python 3.9/3.10/3.11.
  `security-scan` runs `bandit` (non-blocking). `version-guard` (on release) asserts
  the git tag equals `plugin.json` `version`.
- `scripts/link-local.sh` — uv-install the package editable, symlink `commands/`,
  `skills/`, `agents/` into `~/.claude/`, and register the hooks so `/post` works
  without publishing. `--unlink` undoes it. Idempotent; refuses to overwrite
  non-symlink files. `set -euo pipefail`; keep it POSIX-friendly and idempotent.

## Conventions and idioms

- **Prompts are the product.** Behavior changes are edits to the three Markdown files,
  not code. Be precise: these files are read literally by the model at runtime.
- **Fixed angles, on purpose.** The writer always produces exactly 3 candidates in the
  same three angles (debugging story / counterintuitive lesson / tiny tool share) so
  A/B comparison against the DIY baseline stays apples-to-apples. Don't make them
  dynamic until the fixed angles have proven the wedge.
- **Privacy is non-negotiable.** The *extraction/drafting* path runs entirely locally.
  Never add a step that sends transcripts, diffs, or drafts over the network from it.
  Extraction masks secrets, caps diff size (~40k chars), keeps ≤10 lines per code
  snippet, and skips `isSidechain` records. The one deliberate exception is the
  **cloud MCP client** (`serve_cloud.py`, `[cloud]` extra): it passes *already-approved
  draft text* to the postcommit-cloud REST API and nothing else. It is a **separate**
  server from the local-only `postcommit-mcp` precisely so the local guarantee holds —
  keep `serve.py` and the extraction path network-free, and keep all outbound HTTP
  confined to `cloud_client.py`/`cloud_auth.py`.
- **Cloud client boundary.** `cloud_config.py`/`cloud_auth.py`/`cloud_client.py` are
  **stdlib-only core** (they install without any extra); only `serve_cloud.py` imports
  the `mcp` SDK. Auth flows through the `CredentialProvider` seam in `cloud_auth.py`
  (env token → cached/refreshed `~/.postcommit/credentials.json`); a later ticket adds
  the interactive login that populates that file — do not add throwaway auth scaffolding
  elsewhere.
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
  `postcommit.extract.transcript_dir` computes that and also tries a `.`-folded variant
  (some Claude Code versions fold `.` to `-`), then filters records by `.timestamp`
  against the window cutoff.
- The window argument accepts durations (`1d`, `4h`, `30m`), `today`, git ranges
  (`HEAD~3..HEAD`, `main..HEAD`, `<sha>..<sha>`), and `since=YYYY-MM-DD`.
- Branching/PR flow: trunk-based on `main`. Do work on a short-lived, conventionally
  named branch (`type/short-desc` — see Conventions above) and merge it via PR into
  `main`; there is no long-lived `dev` branch. `main` is protected — the `validate` CI
  job must be green before merge. Releases are cut from `main` by tagging `vX.Y.Z`
  (matching `plugin.json` `version`), which the `version-guard` job enforces.
