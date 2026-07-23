---
name: postcommit-extract
description: Extract a compact "work bundle" (git state + Claude Code session excerpts) from the current repo over a specified window, for downstream drafting of LinkedIn posts. Use when the /post command runs, or when the user asks for a distilled summary of what they actually did in this repo over a specific period.
---

# postcommit-extract

Your job: hand back a compact, high-signal **work bundle** answering "what did the
human actually do here, and what was interesting about it?" — from local sources
only. No network. Nothing leaves the machine.

The mechanical work (parsing the window, gathering git state, locating and
filtering Claude Code session transcripts, capping the diff, masking secrets,
emitting the bundle) is done deterministically by the installed `postcommit` CLI.
Your remaining job is one small piece of judgment: the **Candidate signal**.

## Input

- **Window** — a string like `1d`, `4h`, `30m`, `today`, `HEAD~3..HEAD`,
  `main..HEAD`, `abc123..HEAD`, or `since=YYYY-MM-DD`.
- The current working directory, which must be a git repo.

## Step 1 — Build the deterministic bundle

Run the postcommit CLI to emit the bundle. The plugin bundles the package, so no
separate install is required — resolve the command in this order and use the
first that runs:

1. `postcommit extract <window>` — a standalone install on PATH.
2. `~/.postcommit/bin/postcommit extract <window>` — the plugin-bundled launcher
   (written by the SessionStart hook).
3. `python3 -m postcommit extract <window>` — a source checkout.

In practice this one-liner picks the right one:

```
( command -v postcommit >/dev/null 2>&1 && postcommit extract <window> ) \
  || ~/.postcommit/bin/postcommit extract <window>
```

It prints a complete work bundle to stdout: repo header, git narrative (commits,
uncommitted state, a size-capped and secret-masked diff), and a session narrative
distilled from this repo's Claude Code transcripts in the window. Capture it
verbatim.

If the bundle's only content is `> No meaningful work in window.`, stop and tell
the user plainly. Do not fabricate a bundle.

If none of the above resolve — no `postcommit` on PATH and no
`~/.postcommit/bin/postcommit` (e.g. Claude Code hasn't run a SessionStart since
the plugin was installed) — tell the user to restart Claude Code once so the hook
writes the launcher, or to install the CLI with `uv tool install postcommit`.
Don't guess at the extraction by hand.

## Step 2 — Fill the Candidate signal

The bundle ends with a `## Candidate signal (best guesses, for the writer)`
section whose bullets are placeholder dashes. Replace them using **only** facts
already present in the bundle above — never invent detail:

- **Problem:** 1 sentence, in the user's own domain terms.
- **Obvious-but-wrong first move:** 1 sentence, or "none evident".
- **Real fix / resolution:** 1 sentence, or "in progress / no clear resolution".
- **Surprising bit:** 1 sentence, or "none obvious — flag to writer".
- **Transferable lesson:** 1 sentence, or "none obvious".

If the signal is mostly "none obvious," say so at the top of the bundle so the
writer downstream can decide whether to draft at all.

## Step 3 — Return the bundle

Return the full bundle (the CLI output with your Candidate signal filled in), no
preamble.

## Safety rules (non-negotiable)

- Everything runs locally. Never send transcripts, diffs, or drafts off the machine.
- The CLI already masks secret-looking values and caps the diff; if you still see
  anything that looks like a token, key, or `.env` content, re-mask it (show the
  filename, redact the value) before returning.
- Never include raw source beyond what the CLI already emits, and never add detail
  that is not in the bundle.
