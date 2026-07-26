# postcommit

**Turn the work you already did into a LinkedIn post — without leaving your editor.**

postcommit is a [Claude Code](https://claude.com/claude-code) plugin that reads your
real dev work — git history plus your Claude Code session transcript — and drafts
candidate LinkedIn posts about it. You trigger it with `/post`, review the drafts, and
post the one you like. Nothing is auto-published.

- 🔒 **Local-only.** Extraction and drafting run entirely on your machine. No transcripts, diffs, or drafts leave it.
- ✍️ **Grounded in real work.** Drafts are built from your actual commits and session — the writer never invents numbers, errors, or file names.
- ⚡ **Manual and low-friction.** One command, three drafts, saved to disk. Optional ambient nudges when a session looks post-worthy.

---

## The idea

Most "AI writes your LinkedIn post" tools start from a blank prompt and produce generic
slop. postcommit starts from what you actually did today — the diff, the debugging
detour, the tiny tool you built — and turns that specificity into a draft worth posting.

The design bet is simple and testable: **feeding the tool the real work should produce a
post meaningfully better than just asking Claude, in the same session, "write a post
about what we just did."** If it doesn't, there's no product. That honesty test (see
[Is it actually better?](#is-it-actually-better)) is the north star, not feature breadth.

## How it works

```
/post <window>
   → extract      deterministic: git state + session transcript → a "work bundle"
                  (masks secrets, caps the diff, skips sidechains — all local)
   → post-writer  a Claude subagent turns the bundle into 3 candidate drafts
   → save         drafts land in .postcommit/drafts/<UTC-ISO>.md and open in your editor
```

Two layers keep it honest: **deterministic code** (an installable Python package does
the extraction, scoring, and state) and a **prompt/taste layer** (the post-writer
subagent that actually writes). The command, skill, and hooks are thin glue between them.

## Install

One step. This repo is its own plugin marketplace:

```
/plugin marketplace add AvivVegh/postcommit
/plugin install postcommit
```

That registers the `/post`, `/post-snooze`, and `/post-login` commands, the extract
skill, the post-writer subagent, and the two hooks. Uninstalling removes all of them automatically
— no manual `settings.json` editing. Restart Claude Code once after installing so the
`SessionStart` hook can wire up the bundled CLI, then `/post` just works.

The plugin **bundles the Python package** that does the real work (it's dependency-free
stdlib), and runs it via your system `python3` (3.9+) — so there's nothing else to
install. To update later: `/plugin update postcommit`.

> **No system `python3`?** Install the CLI standalone and the plugin will prefer it:
> `uv tool install postcommit` (or `pipx install postcommit` / `pip install postcommit`).
> `uv` bundles its own interpreter, so this also covers machines without Python. This is
> also how you get a standalone `postcommit` CLI for use outside Claude Code.

## Usage

Do real work in a repo with Claude Code, then:

```
/post 1d
```

The window argument accepts:

| Form | Example | Meaning |
|------|---------|---------|
| Duration | `1d`, `4h`, `30m` | Work in the last N days/hours/minutes |
| Keyword | `today` | Since midnight local time |
| Git range | `HEAD~3..HEAD`, `main..HEAD` | A commit range |
| Date | `since=2026-07-01` | Since a calendar date |

You get three drafts in three fixed angles — a **debugging story**, a **counterintuitive
lesson**, and a **tiny tool share** — saved to `.postcommit/drafts/<UTC-ISO>.md` and
opened in your editor. The angles are fixed on purpose so you can compare output
apples-to-apples over time.

You do **not** need to add anything to your `.gitignore`. postcommit creates
`.postcommit/` with a `.gitignore` of its own containing `*`, so the directory —
drafts, state, and the ignore file itself — is invisible to git from the moment it
is created. Your drafts are distilled from session transcripts, and this way they
cannot be committed by accident. To commit one on purpose:
`git add -f .postcommit/drafts/<file>.md`.

### Is it actually better?

The built-in honesty check:

1. Run `/post 1d` after real work.
2. In the **same** session, also ask: *"Write a LinkedIn post about what we just did."* — the DIY baseline.
3. Compare. Is the tool's draft clearly better? Would you post it? Would you post the DIY one?

If the tool clearly wins, it's earning its keep. If they're a tie, the specificity isn't
paying off yet.

## The habit loop (hooks)

So you don't have to remember `/post`, two Claude Code hooks make the recommendation
ambient — both instant, deterministic, and local (no model calls):

- **`SessionEnd`** cheaply scores whether the session was post-worthy (commits/churn since your last post + transcript signals like real prompts, edits, duration, debugging keywords). If it clears the bar, it stages a lightweight recommendation. If you already ran `/post` this session, it just advances the watermark instead.
- **`SessionStart`** surfaces that recommendation as a one-line nudge — but only if there's unposted post-worthy work, at most once per day, and never while snoozed.

Controlling nudges:

- `/post` acts on the recommendation and clears it.
- `/post-snooze [days]` hushes nudges for this repo (default 3 days).
- `postcommit state show` inspects all state; `snooze` / `unsnooze` / `mark-posted` / `reset` are also available as `postcommit state <verb>`.

## Cloud (optional): schedule & publish to LinkedIn

Everything above is free and local. postcommit also ships a **separate**, opt-in cloud
MCP server, `postcommit-cloud-mcp`, that passes *already-approved draft text* to the
hosted postcommit-cloud API so drafts can be created, scheduled, and published to
LinkedIn from any MCP host. It's deliberately split from the local tooling — the
local "nothing leaves the machine" guarantee holds because this is the only piece that
touches the network, and only ever with approved draft text.

```sh
uv tool install 'postcommit[cloud]'
postcommit cloud login         # paste a token from the dashboard (see below)
```

From inside Claude Code, `/post-login` reports whether you're already signed in and,
if not, opens the dashboard and hands you the command to run. It deliberately does
**not** take the token itself: anything pasted into the chat is written to the session
transcript, which is exactly what postcommit reads to build work bundles. Paste in your
own terminal. It's the one command in the plugin that touches the network, and it sends
authentication only, never repo content.

The plugin does **not** register the cloud MCP server itself: it bundles a stdlib-only
package, while the server needs `mcp>=1.2` and Python ≥3.10, so that part is always a
real install. `postcommit cloud status` reports whether you're signed in — it prints
`active`, `active-unverified`, `signed-out`, or `rejected`, and never the token. Note
that an expired `id_token` is normal and still reports `active`: the stored refresh
token renews it silently.

`login` defaults to a **paste** handoff: copy the token from the dashboard, paste it at
the prompt, and it's decoded and written (chmod 600) to `~/.postcommit/credentials.json`.
`postcommit cloud login --browser` instead runs a local loopback handoff — it opens the dashboard and
waits for the browser to hand a token back to a one-shot `127.0.0.1` server, timing out
after 300 seconds. `login <token>` takes the token inline, for scripting.

Either way the stored bundle holds a refresh token, so you paste **once** — tokens are
refreshed automatically from there, with no env vars required for normal use.
`postcommit cloud logout` deletes the credentials file (and with it the refresh
token, so you'd have to log in again).

**Tools:** `create_post`, `list_posts`, `update_post`, `delete_post`, `linkedin_status`,
`linkedin_disconnect`.

**Optional configuration (env vars):**

- `POSTCOMMIT_CLOUD_API_URL` — REST API base URL. Defaults to the production gateway; point it at a local backend for dev.
- `POSTCOMMIT_DASHBOARD_URL` — dashboard base URL whose `/cli-auth` page completes the loopback login. Defaults to the production dashboard.
- `POSTCOMMIT_CLOUD_TOKEN` — paste a Firebase id_token directly instead of running `login` (handy for CI/scripting).
- `POSTCOMMIT_FIREBASE_API_KEY` — only needed to refresh a token when it's not already stored by `login`.

## Privacy

Privacy is a design constraint, not a setting:

- The **extraction and drafting path never touches the network.** The core package is stdlib-only.
- Extraction **masks secrets**, caps the diff (~40k chars), keeps ≤10 lines per code snippet, and skips `isSidechain` transcript records.
- The **only** networked component is the optional `postcommit-cloud-mcp` server, and it sends **approved draft text only** — never raw code or transcripts.

## Development

Contributions welcome. To hack on postcommit locally without publishing:

```sh
scripts/link-local.sh          # editable install + symlink command/skill/agent + register hooks
scripts/link-local.sh --unlink # undo
```

This installs the package as an editable `uv` tool (so `postcommit` tracks your
checkout), symlinks the command/skill/subagent into `~/.claude/`, and registers the
hooks. Idempotent; won't overwrite non-symlink files. Restart Claude Code once after
linking. Use this **or** the published plugin, not both — they register the same hooks
two different ways.

**Tests** are stdlib `unittest` — no pytest, no extra deps:

```sh
scripts/run-tests.sh           # or: python3 -m unittest discover -s tests
```

**Lint:** `ruff check postcommit tests hooks` and
`bandit -c pyproject.toml -r postcommit hooks`.

### Layout

```
pyproject.toml                      # installable package; entry points below
.claude-plugin/                     # plugin.json + marketplace.json (the plugin manifest)
postcommit/                         # the package — all deterministic logic
  __main__.py                       #   `postcommit` CLI: extract | state | hook | cloud
  extract.py                        #   git + session-transcript → work bundle (masks secrets, caps diff)
  scoring.py                        #   post-worthiness signals + scoring
  state.py                          #   per-repo/global state, shared git/transcript constants
  hooks.py                          #   SessionEnd / SessionStart logic
  cloud_config.py / cloud_auth.py / cloud_client.py   # stdlib cloud REST client + auth seam
  cloud_login.py                    #   `postcommit cloud` status/login/logout (stdlib)
  serve_cloud.py                    #   `postcommit-cloud-mcp` — networked MCP server ([cloud] extra)
commands/post.md                    # /post <window> — the manual trigger
commands/post-snooze.md             # /post-snooze [days] — hush the nudge
commands/post-login.md              # /post-login — cloud auth (the only networked command)
skills/postcommit-extract/SKILL.md  # the thin extract skill adapter
agents/post-writer.md               # the writer subagent — the LinkedIn taste layer
hooks/                              # hooks.json + the two thin shims that call the CLI
tests/                              # stdlib unittest suite
docs/smoke-test.md                  # manual install/QA checklist
scripts/link-local.sh               # dev-only local install
scripts/run-tests.sh                # run the unittest suite
```

**Entry points:** `postcommit` (CLI) and `postcommit-cloud-mcp` (cloud MCP server,
`[cloud]` extra).

**The subagent prompt is the product.** `agents/post-writer.md` is the taste/template
layer that decides whether a draft reads human or like slop. Iterate there first when
improving output quality.

## License

MIT.
