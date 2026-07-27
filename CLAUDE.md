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
pyproject.toml                      # installable package: [project.scripts] postcommit + postcommit-cloud-mcp
uv.lock                             # pinned resolution (core is dependency-free; cloud is a 3.10+ extra)
postcommit/                         # the package — all deterministic logic lives here
  __main__.py                       #   `postcommit` CLI dispatch: extract | state | hook | cloud
  extract.py                        #   deterministic git + session-transcript → work bundle (ported SKILL.md)
  scoring.py                        #   post-worthiness signals + scoring (from the old session-end)
  state.py                          #   time/paths/json/watermark/git helpers, shared constants + `state` verbs
  hooks.py                          #   handle_session_end / handle_session_start
  cloud_config.py                   #   cloud-client config from env (stdlib core)
  cloud_auth.py                     #   CredentialProvider seam + credentials writer (stdlib core)
  cloud_login.py                    #   `postcommit cloud` status/login/logout — paste + loopback (stdlib core)
  cloud_client.py                   #   thin REST client for postcommit-cloud (stdlib urllib)
  cloud_sync.py                     #   `postcommit cloud sync` — push draft candidates + idempotency ledger
  drafts.py                         #   parse a saved draft file into its post(s) (current + legacy shape)
  serve_cloud.py                    #   `postcommit-cloud-mcp` MCP server (optional [cloud] extra) — network passthrough
.claude-plugin/plugin.json          # plugin manifest (name, version — kept in sync with pyproject)
.claude-plugin/marketplace.json     # self-hosted marketplace listing this plugin
commands/post.md                    # /post <window> — the manual trigger (thin dispatcher)
commands/snooze.md                  # /snooze [days] — hush the nudge
commands/login.md                   # /login — cloud auth (networked: auth only)
commands/sync.md                    # /sync — push saved drafts to the cloud (networked: content)
skills/postcommit-extract/SKILL.md  # the thin extract skill adapter (single source of truth)
agents/post-writer.md               # the writer subagent — LinkedIn taste/template layer
hooks/hooks.json                    # declares SessionEnd/SessionStart (auto-registered on install)
hooks/session-end.py                # thin shim → `postcommit hook session-end`
hooks/session-start.py              # thin shim → `postcommit hook session-start`
hooks/_adapter.py                   # shared forwarding logic for the two shims
scripts/link-local.sh               # dev-only: uv-install editable + symlink command/skill/agent + register hooks
scripts/run-tests.sh                # run the stdlib unittest suite (python3 -m unittest)
tests/                              # unittest suite for the package (see below)
docs/smoke-test.md                  # manual install/QA checklist for a real Claude Code host
README.md                           # product framing + how to run the wedge test
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
`skills/postcommit-extract/SKILL.md` is the single source of truth for the extract
adapter — there is no second copy to keep in sync.

## The architecture (keep these boundaries clean)

Two layers: **deterministic code** (the `postcommit` package) and **prompt/taste**
(the writer subagent). The command/skill/hooks are thin glue between them.

- **`postcommit/extract.py` — the extractor (code).** Deterministic and mechanical:
  parses the window, gathers git state, locates and filters Claude Code session
  JSONLs, caps the diff, masks secrets, and emits the work bundle. This is where the
  privacy rules live (mask secrets, cap diff ~40k, ≤10 lines/snippet, skip sidechain
  records, no network). Two shapes: `build_bundle` (flat, whole window) and
  `build_per_commit_bundle` (`--per-commit`, one slice per commit — what `/post`
  uses). The judgment calls — which slices are the same piece of work, and the
  "Candidate signal" — are left to the model.
- **`skills/postcommit-extract/SKILL.md` — the extractor adapter (prompt).** Thin:
  tells the model to run `postcommit extract <window> --per-commit`, group the
  slices into work items, and fill each item's Candidate signal.
- **`commands/post.md` — the dispatcher (prompt).** Thin. Parses the window argument,
  invokes the extract skill, dispatches one writer subagent per work item (in
  parallel, capped at 5), saves each result to
  `.postcommit/drafts/<UTC-ISO>-<item>.md` (path obtained from `postcommit state
  drafts-dir`, never `mkdir`'d by hand), and opens it. No creative or extraction
  logic.
- **`agents/post-writer.md` — the writer (prompt).** Creative and opinionated. This is
  the crown jewel — the file that decides whether a draft reads human or like slop.
  **Iterate here first** when improving output quality.

Data flow: `/post <window>` → extract skill → `postcommit extract --per-commit`
(deterministic per-commit slices) → model groups slices into work items and fills
each Candidate signal → one post-writer subagent per item → one draft per item →
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
  `pip install .`) installs the `postcommit` + `postcommit-cloud-mcp` entry points. The
  core is **dependency-free** (stdlib only) so it installs anywhere; only the cloud MCP
  server needs the `[cloud]` extra (`mcp>=1.2`, Python ≥3.10). `uv.lock` pins the
  resolution. Keep the core stdlib-only — that's the privacy/portability guarantee.
- **Tests:** `scripts/run-tests.sh` (or `python3 -m unittest discover -s tests`). It is
  **stdlib-only `unittest`** — no pytest, no pip install. Coverage under `tests/`:
  `test_postcommit_state.py` (time/json/watermark/git helpers + `state` verbs),
  `test_session_end.py` (scoring, transcript parsing, shortstat, end-to-end staging),
  `test_session_start.py` (nudge text + the SessionStart gates),
  `test_extract.py` (window parsing, secret masking, diff cap, transcript distillation,
  bundle assembly), `test_cli.py` (argparse dispatch, the `cloud` verb),
  `test_adapter.py` + `test_hook_adapter.py` (the hook shims: timeouts/error swallowing,
  and plugin-root/child-env/CLI resolution respectively), and the cloud set —
  `test_cloud_auth.py`, `test_cloud_client.py`, `test_cloud_login.py`,
  `test_cloud_sync.py` (ledger idempotency, dry-run does no I/O, auth abort),
  `test_drafts.py` (post parsing, current + legacy shape; labels + reviewer note
  stripped),
  `test_serve_cloud.py`.
  `tests/_support.py` imports the package (putting the repo root on `sys.path`) and
  builds throwaway git repos / transcript JSONLs. `run_hook` drives the thin shims as
  subprocesses with `HOME` at a temp dir and `PYTHONPATH` at the checkout so the
  `python -m postcommit` fallback resolves. Add a test alongside any logic change.
- **Lint:** `ruff check postcommit tests hooks` (config in `pyproject.toml`: E/F/I/B;
  `UP` is intentionally off — the package uses `%`-formatting throughout, matching the
  code it was ported from). `bandit -c pyproject.toml -r postcommit hooks` is the
  security lint — the `-c` is required or the documented B404/B603 skips are ignored.
- **CI:** `.github/workflows/ci.yml`. `validate` (required before merge) parses
  manifests, checks that `plugin.json`, `pyproject.toml` and `postcommit/__init__.py`
  versions all agree, verifies the hooks in `hooks.json` exist + are `+x`,
  byte-compiles the hooks + package, installs the package and smoke-tests the CLI,
  runs `ruff`, the `unittest` suite, and `test_serve_cloud.py` again with the
  `[cloud]` extra installed (otherwise its `build_server` test self-skips forever),
  and `shellcheck`s the scripts. `test-matrix` reruns the suite on Python
  3.9/3.10/3.11. `security-scan` runs `bandit` (non-blocking). `version-guard` (on
  release) asserts the git tag equals `plugin.json` `version`.
- `scripts/link-local.sh` — uv-install the package editable, symlink `commands/`,
  `skills/`, `agents/` into `~/.claude/`, and register the hooks so `/post` works
  without publishing. `--unlink` undoes it. Idempotent; refuses to overwrite
  non-symlink files. `set -euo pipefail`; keep it POSIX-friendly and idempotent.

## Conventions and idioms

- **Prompts are the product.** Behavior changes are edits to the three Markdown files,
  not code. Be precise: these files are read literally by the model at runtime.
- **One post per work item.** A run splits the window into work items and writes
  exactly one post for each — one piece of work, one post, the way LinkedIn is
  actually used. Three variations of the same work is a chooser UI, not a publishing
  flow. The split has a fixed division of labour: **code slices** (per commit,
  `extract.py`), **the model groups** (which commits are one piece of work),
  **the writer picks the angle** from a named library and commits to it. Do not move
  the grouping into Python — commit scopes are too inconsistent for a rule — and do
  not let the writer hedge by emitting two angles. **The fan-out is uncapped**: a
  20-item day gets 20 posts, because a cap re-creates the exact failure the split
  was built to fix ("most of the day's material never surfaces"). Thin items are
  dropped by the writer's `SKIP`, never by truncating the list. The per-slice diff
  budget is **fair-share** — `PER_COMMIT_TOTAL_CAP // len(kept)`, floored at
  `MIN_SLICE_DIFF_CHARS` — not first-come-first-served, which used to hand the
  whole budget to the oldest commits and leave the newest slices unquotable.
  Neither cap is a hard ceiling on bundle size: `cap_diff` keeps structural lines
  unconditionally, so a wide commit overruns its share. Don't quote those constants
  as size guarantees; the guarantees are masking and the snippet rules.
- **Thin items get skipped, not padded.** The writer returns `SKIP: <reason>` when an
  item has no surprise and no takeaway, and the code filters merge and release
  commits before that. Everything dropped is *reported* — silent truncation would
  read as "there was nothing to post about" when there was.
- **Audience is product + engineering.** The post is a story someone in product can
  retell, carrying at least one real checkable specific from the bundle as evidence.
  Both halves matter: jargon walls and substance-free advice are the two failure
  modes, and `agents/post-writer.md` bans both by name.
- **Privacy is non-negotiable.** The *extraction/drafting* path runs entirely locally.
  Never add a step that sends transcripts, diffs, or drafts over the network from it.
  Extraction masks secrets, caps diff size (~40k chars), keeps ≤10 lines per code
  snippet, and skips `isSidechain` records. The one deliberate exception is the
  **cloud MCP client** (`serve_cloud.py`, `[cloud]` extra): it passes *already-approved
  draft text* to the postcommit-cloud REST API and nothing else. Keep the extraction
  path network-free, and keep all outbound HTTP confined to
  `cloud_client.py`/`cloud_auth.py`.
- **Cloud client boundary.** `cloud_config.py`/`cloud_auth.py`/`cloud_client.py`/
  `cloud_login.py` are **stdlib-only core** (they install without any extra); only
  `serve_cloud.py` imports the `mcp` SDK. Auth flows through the `CredentialProvider`
  seam in `cloud_auth.py` (env token → cached/refreshed
  `~/.postcommit/credentials.json`), and `cloud_login.py` is what populates that file —
  do not add throwaway auth scaffolding elsewhere. Anything writing credentials goes
  through `cloud_auth.write_credentials`, which is what applies the 0o600 chmod.
- **Two networked commands, and only two.** `commands/login.md` (`/login`)
  carries *authentication only* — never repo content. `commands/sync.md` (`/sync`) is
  the only surface that sends *content*, and only draft posts the user has
  already seen and confirmed. Everything else — `/post`, the extract skill, the hooks
  — stays entirely local; do not add cloud calls to them. `plugin.json` still declares
  **no** `mcpServers`: the plugin bundles a stdlib-only package, and the cloud MCP
  server needs `mcp>=1.2` + Python ≥3.10, so it cannot ride along the way `/post` does.
  `cloud_sync.py` is stdlib-only for exactly that reason — `/sync` reaches it through
  the launcher, not through the MCP server.
- **`/sync` shows a plan before it uploads.** `cloud_sync.plan()` does no network I/O,
  so `postcommit cloud sync --dry-run` works signed-out and lists every post that
  would go. The command must run it and get confirmation first: it pushes *every*
  unsynced draft in the repo, not just the last run's, and a bulk push of
  transcript-derived drafts should never be a surprise.
- **Pushes are idempotent via a two-level ledger.** `.postcommit/state/synced.json`
  holds `drafts` (`<draft file> → <post key> → post_id`) *and* `items`
  (`<work item sha> → post_id`), both written after *each* successful push, so an
  interrupted run never double-posts on retry. The key comes from
  `cloud_sync.ledger_key` — the work item's short sha, read back off the
  `<UTC-ISO>-<item>.md` filename `/post` chose, which is why that suffix is load-
  bearing and not decoration. **The flat `items` index is the one that actually
  dedupes across runs**: the filename carries the timestamp of the `/post` run that
  wrote it, so re-running over an overlapping window produces a *new* file for the
  *same* item and a filename-keyed lookup misses it. Only real item shas go in
  `items` — legacy candidate letters and the `POST` fallback repeat across files, so
  they stay file-scoped. A v1 ledger (no `items`) reads as an empty index rather
  than being migrated: nothing shipped that would have written one, so a backfill
  would be dead code. `plan()` also dedupes *within* one pass, since two unsynced drafts for one
  item can both be pending. Failures are deliberately *not* recorded — they retry
  next run. Never "fix" a failed push by re-uploading by hand.
- **Pre-split drafts still work.** Drafts written before one-post-per-work-item hold
  three `### Candidate <A|B|C>` blocks and a `— why this angle` reviewer note.
  `drafts.py` parses both headings and still strips the note, and those files keep
  their letter ledger keys, so nothing on a user's disk needs migrating or gets
  re-pushed. Don't "clean up" the legacy branches — they are the compatibility.
- **Two different 403s, two different remedies.** The backend gates `POST /posts`
  behind an active plan and answers `{"error": "subscription_required"}`; a bad token
  is also a 403. `cloud_sync` keeps `AuthRejected` and `SubscriptionRequired` as
  *sibling* exceptions so neither can catch the other, because telling an
  unsubscribed user to run `/login` loops them back to the same error forever. The
  backend contract lives in the postcommit-cloud repo
  (`backend/src/shared/auth/require-subscription.ts`) — check it before touching this.
- **There is no bulk/sync endpoint.** The cloud posts API is five handlers —
  `POST /posts`, `GET /posts`, `GET /posts/summary`, `PATCH /posts/{id}`,
  `DELETE /posts/{id}` — so a sync is N sequential creates, and the ledger is what
  makes that safe. The 3000-char cap in `cloud_sync.MAX_CONTENT_CHARS` mirrors
  `MAX_CONTENT_LENGTH` in the backend's posts handler; they must not drift.
- **Only post bodies go over the wire.** `drafts.py` strips the `### Post` label —
  and, on legacy drafts, the `### Candidate <letter>` label plus the `— why this
  angle` reviewer note — before anything reaches `cloud_client`. If the writer's
  output format changes, `drafts.py` and its tests change with it.
- **Cloud auth hangs off the *main* CLI (`postcommit cloud ...`), not
  `postcommit-cloud-mcp`.** The launcher the SessionStart hook writes runs `python3 -m
  postcommit`, so anything the model-run commands must reach has to live on that
  parser; a verb only on the separate `postcommit-cloud-mcp` console script is
  unreachable from `/login` and forces a fragile hunt for a source checkout. Keep
  new model-facing verbs on `__main__.py`. `cloud_login` is stdlib-only, so this costs
  the dependency-free core nothing.
- **`status` answers "can I use the cloud", not "has the id_token expired".** The
  id_token lives ~1h and the refresh_token beside it is long-lived, so an expired
  id_token is the normal steady state. `cloud_login.status()` returns one of
  `active` / `active-unverified` / `signed-out` / `rejected` with exit 0 meaning
  usable, and it never prints the token. Branching on expiry alone would send users
  back to the dashboard hourly for nothing.
- **The token must never enter the chat.** The dashboard blob is base64(JSON) holding a
  long-lived `refresh_token`. Anything in the chat lands in the session transcript,
  which `postcommit extract` reads — so a pasted token can reach a work bundle, a
  draft, and a published post. `/login` therefore sends the user to their *own*
  terminal to paste, and `extract._TOKEN_RE` masks the bundle shape as a backstop.
- **No fabrication.** The writer must never invent numbers, timings, error messages, or
  file names not present in the bundle. Preserve this rule in any edit to the writer.
- **Generated output** lands in `.postcommit/`, which **ignores itself**: every code
  path that creates it goes through `state.ensure_repo_dir`, which drops a
  `.gitignore` containing `*` (the same trick as `.pytest_cache/`). The user never
  adds an ignore rule, and transcript-derived drafts can't be committed by accident.
  Never `mkdir` that directory directly — route through `ensure_repo_dir` (or, from
  a prompt file, `postcommit state drafts-dir`) or you lose the guarantee. Drafts are
  named by UTC ISO timestamp with colons replaced by dashes for filesystem safety.
- **`state.py` is the shared-vocabulary home.** `extract.py` and `scoring.py` both walk
  the same git output and the same Claude Code JSONL records, so the things they must
  agree on live in `state`: `parse_shortstat`, `EMPTY_TREE`, `META_PREFIXES`,
  `EDIT_TOOLS`. The two transcript *walks* stay separate on purpose (the scorer runs in
  a hook and is capped; the extractor is thorough) — share the vocabulary, not the loop.
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
