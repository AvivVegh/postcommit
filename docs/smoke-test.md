# Phase 2 smoke test — install / QA / uninstall

Interactive checklist for verifying the packaged plugin installs, works, and
cleans up after itself. Runs against a **real Claude Code instance** — the
install step is interactive and can't be fully automated.

There are two passes:

- **Pass A — local marketplace** (de-risk *before* merging). Catches manifest
  errors without needing anything pushed to GitHub.
- **Pass B — fresh `~/.claude/`** (the real Phase 2 deliverable). Requires the
  plugin merged to `main` and pushed, because `/plugin marketplace add
  AvivVegh/postcommit` reads from GitHub.

Do Pass A first. Only do Pass B once PR #6 is merged.

---

## Pre-flight (both passes)

Sanity-check the manifests parse and the hook scripts are executable before you
touch Claude Code:

```bash
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json hooks/hooks.json; do
  python3 -m json.tool "$f" >/dev/null && echo "ok  $f" || echo "BAD $f"
done
test -x hooks/session-end.py   && echo "ok  session-end.py executable"   || echo "BAD session-end.py not +x"
test -x hooks/session-start.py && echo "ok  session-start.py executable" || echo "BAD session-start.py not +x"
```

- [ ] All three JSON files parse.
- [ ] Both hook scripts are executable.

---

## Pass A — local marketplace (before merge)

Point Claude Code at this working copy as a local marketplace. In Claude Code:

```
/plugin marketplace add /Users/avivvegh/Documents/repos/postcommit
/plugin install postcommit@postcommit
```

- [ ] Install completes with no manifest / schema errors.
- [ ] `/help` (or the command list) shows **`/post`** and **`/post-snooze`**.
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

Launch Claude Code with that env set. In Claude Code:

```
/plugin marketplace add AvivVegh/postcommit
/plugin install postcommit
```

- [ ] Marketplace resolves from GitHub `main` and lists `postcommit` at `0.1.0`.
- [ ] Install completes clean.
- [ ] `/post` and `/post-snooze` are available.
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

## Functional checks (run in a scratch git repo)

Do this inside a throwaway repo with a couple of real commits, so the hooks have
something to score.

**`/post` works:**
- [ ] Run `/post 1d` (or `/post HEAD~2..HEAD`).
- [ ] Three candidate drafts are produced and saved under
      `.postcommit/drafts/<UTC-ISO>.md`.

**The nudge loop works (Phase 1 via the installed hooks):**
- [ ] Do a little real work (edits + a commit), then **end the session**.
      SessionEnd should stage a recommendation:
      ```bash
      cat .postcommit/state/recommendation.json   # exists, post-worthy
      ```
- [ ] Start a **fresh** session (`startup`/`clear`, not `resume`). SessionStart
      should surface an ambient nudge (once/day, unposted-work-only).
- [ ] Running `/post` clears the recommendation; a second fresh start does **not**
      nudge again.
- [ ] `/post-snooze 1` suppresses the nudge; confirm no nudge on next start.

---

## Uninstall / cleanup checks

```
/plugin uninstall postcommit
```

- [ ] `/post` and `/post-snooze` are gone.
- [ ] `/hooks` no longer lists the SessionEnd / SessionStart entries — **this is
      the key one**: uninstall must remove the hooks automatically. No dangling
      nudges after removal.
- [ ] `settings.json` still untouched (nothing to clean up there).
- [ ] Per-repo `.postcommit/` state and `~/.postcommit/` are the user's data and
      are expected to remain (document this, or remove manually if testing clean).

---

## Pass / fail

The plugin passes Phase 2 QA when **both** hold:

1. Fresh install (Pass B) yields working `/post` + a firing nudge with no manual
   `settings.json` editing.
2. Uninstall removes commands **and** hooks, leaving no dangling registrations.
