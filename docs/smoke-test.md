# Smoke test — install / QA / uninstall

Interactive checklist for verifying the packaged plugin installs, works, and
cleans up after itself. Runs against a **real Claude Code instance** — the
install step is interactive and can't be fully automated.

There are two passes:

- **Pass A — local marketplace** (de-risk *before* merging). Catches manifest
  errors without needing anything pushed to GitHub.
- **Pass B — fresh `~/.claude/`** (the real thing). Requires the change merged to
  `main` and pushed, because `/plugin marketplace add AvivVegh/postcommit` reads
  from GitHub.

Do Pass A first, then Pass B once the branch is merged.

---

## Pre-flight (both passes)

The plugin **bundles** the Python package — a separate CLI install is *not*
required, and Pass B deliberately tests the no-install path. So the pre-flight
only checks the repo itself:

```bash
# 1. Manifests parse and hook shims are executable.
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json; do
  python3 -m json.tool "$f" >/dev/null && echo "ok  $f" || echo "BAD $f"
done
test -x hooks/session-end.py   && echo "ok  session-end.py executable"   || echo "BAD session-end.py not +x"
test -x hooks/session-start.py && echo "ok  session-start.py executable" || echo "BAD session-start.py not +x"

# 2. The bundled package runs straight from the checkout and self-reports the
#    same version the manifest advertises.
python3 -m postcommit --version
python3 -c 'import json; print("plugin.json:", json.load(open(".claude-plugin/plugin.json"))["version"])'

# 3. It produces a bundle in a repo with work:
python3 -m postcommit extract HEAD~1..HEAD | head -3
```

- [ ] All three JSON files parse.
- [ ] Both hook shims are executable.
- [ ] `python3 -m postcommit --version` matches the `plugin.json` version exactly.
- [ ] `postcommit extract` emits a work bundle.

---

## Pass A — local marketplace (before merge)

Point Claude Code at this working copy as a local marketplace. In Claude Code:

```
/plugin marketplace add /Users/avivvegh/Documents/repos/postcommit
/plugin install postcommit@postcommit
```

- [ ] Install completes with no manifest / schema errors.
- [ ] `/help` (or the command list) shows **`/post`**, **`/snooze`**, and
      **`/login`**.
- [ ] The `postcommit-extract` skill and `post-writer` subagent are listed.
- [ ] Hooks registered — see **Verifying hooks** below.

Then run the functional + uninstall checks (same as Pass B, below), and finally
remove the local marketplace so it doesn't shadow the real one:

```
/plugin uninstall postcommit@postcommit
/plugin marketplace remove postcommit
```

---

## Pass B — fresh `~/.claude/` (after merge)

Simulate a brand-new machine by pointing Claude Code at an empty config dir, so
your real `~/.claude/` is untouched:

```bash
export CLAUDE_CONFIG_DIR="$(mktemp -d)/claude"   # throwaway, fresh config
echo "using $CLAUDE_CONFIG_DIR"
```

For a true fresh-machine test, make sure no standalone CLI is shadowing the
bundled one — if `command -v postcommit` prints a path, the launcher tier below
never gets exercised.

Launch Claude Code with that env set. In Claude Code:

```
/plugin marketplace add AvivVegh/postcommit
/plugin install postcommit
```

- [ ] Marketplace resolves from GitHub `main` and lists `postcommit` at the
      version in `plugin.json`.
- [ ] Install completes clean.
- [ ] `/post`, `/snooze`, and `/login` are available.
- [ ] Skill + subagent listed.
- [ ] Hooks registered — see below.

When done, delete the throwaway dir: `rm -rf "$CLAUDE_CONFIG_DIR"`.

---

## Verifying hooks are registered

The plugin's hooks come from `hooks/hooks.json`, not from `settings.json`
surgery. Confirm Claude Code picked them up:

- [ ] `/hooks` lists a **SessionEnd** and a **SessionStart** entry whose command
      contains `session-end.py` / `session-start.py` under the plugin root.
- [ ] The active config's `settings.json` was **not** modified by the install
      (contrast with `link-local.sh`, which does edit it). Confirm no
      postcommit hook entry was written there:

```bash
grep -l "session-end.py\|session-start.py" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json" 2>/dev/null \
  && echo "UNEXPECTED: hook found in settings.json" || echo "ok: settings.json untouched"
```

---

## Verifying the launcher (the single-install plumbing)

`${CLAUDE_PLUGIN_ROOT}` is only visible to hooks, never to the model-run command
or skill. The SessionStart hook bridges that gap by writing a launcher to a fixed
path, and `/post` resolves the CLI as PATH → launcher → `python3 -m postcommit`.
If the launcher is missing, `/post` falls back or fails on a plugin-only install,
so check it explicitly:

- [ ] After the **first** session start post-install, the launcher exists:
      ```bash
      ls -l ~/.postcommit/bin/postcommit
      ~/.postcommit/bin/postcommit --version
      ~/.postcommit/bin/postcommit state show
      ```
- [ ] It is executable and owner-only (`0700`).
- [ ] After `/plugin update postcommit` (or moving the plugin root), the launcher
      is rewritten to point at the new root — `--version` still works.

---

## Functional checks (run in a scratch git repo)

Do this inside a throwaway repo with a couple of real commits, so the hooks have
something to score.

**`/post` works:**
- [ ] Run `/post 1d` (or `/post HEAD~2..HEAD`).
- [ ] Three candidate drafts are produced and saved under
      `.postcommit/drafts/<UTC-ISO>.md`.

**The nudge loop works (via the installed hooks):**
- [ ] Do a little real work (edits + a commit), then **end the session**.
      SessionEnd should stage a recommendation:
      ```bash
      cat .postcommit/state/recommendation.json   # exists, post-worthy
      ```
- [ ] Start a **fresh** session (`startup`/`clear`, not `resume`). SessionStart
      should surface an ambient nudge (once/day, unposted-work-only).
- [ ] Running `/post` clears the recommendation; a second fresh start does **not**
      nudge again.
- [ ] `/snooze 1` suppresses the nudge; confirm no nudge on next start.

**`/login` works (auth only — no repo content leaves the machine):**
- [ ] Run `/login`. It reports one of `active` / `active-unverified` /
      `signed-out` / `rejected` and never prints a token.
- [ ] When signed out, it points you at the dashboard and tells you to run
      `postcommit cloud login` **in your own terminal** — it must not ask you to
      paste the token into the chat, and must not run `login` itself.
- [ ] `postcommit cloud status` exits 0 when the credentials are usable.
- [ ] `~/.postcommit/credentials.json` is mode `0600` after a login.

---

## Uninstall / cleanup checks

```
/plugin uninstall postcommit
```

- [ ] `/post`, `/snooze`, and `/login` are gone.
- [ ] `/hooks` no longer lists the SessionEnd / SessionStart entries — **this is
      the key one**: uninstall must remove the hooks automatically. No dangling
      nudges after removal.
- [ ] `settings.json` still untouched (nothing to clean up there).
- [ ] Per-repo `.postcommit/` state and `~/.postcommit/` are the user's data and
      are expected to remain (document this, or remove manually if testing clean).
- [ ] In a test repo that has **no** `.postcommit` rule in its own `.gitignore`,
      `git status --porcelain` is clean after `/post` — `.postcommit/.gitignore`
      exists and contains `*`, and `git check-ignore .postcommit/drafts/<file>.md`
      echoes the path back.

---

## Pass / fail

The plugin passes QA when **both** hold:

1. Fresh install (Pass B) yields working `/post` + a firing nudge with **no**
   separate CLI install and no manual `settings.json` editing.
2. Uninstall removes commands **and** hooks, leaving no dangling registrations.
