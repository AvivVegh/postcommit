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

Run:

```
postcommit extract <window>
```

It prints a complete work bundle to stdout: repo header, git narrative (commits,
uncommitted state, a size-capped and secret-masked diff), and a session narrative
distilled from this repo's Claude Code transcripts in the window. Capture it
verbatim.

If the bundle's only content is `> No meaningful work in window.`, stop and tell
the user plainly. Do not fabricate a bundle.

If `postcommit` is not found on PATH, install it once with
`uv tool install postcommit` (or `pip install postcommit`) and re-run. If it
still cannot run, tell the user how to install it rather than guessing at the
extraction by hand.

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
