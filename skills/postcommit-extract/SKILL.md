---
name: postcommit-extract
description: Extract compact "work bundles" (git state + Claude Code session excerpts) from the current repo over a specified window, split into one bundle per piece of work, for downstream drafting of LinkedIn posts. Use when the /post command runs, or when the user asks for a distilled summary of what they actually did in this repo over a specific period.
---

# postcommit-extract

Your job: hand back one compact, high-signal **work bundle per piece of work**,
each answering "what did the human actually do here, and what was interesting
about it?" — from local sources only. No network. Nothing leaves the machine.

The mechanical work (parsing the window, gathering git state, slicing the window
into one section per commit, locating and filtering Claude Code session
transcripts, capping diffs, masking secrets, filtering noise commits) is done
deterministically by the installed `postcommit` CLI. Two pieces of judgment are
left to you: **grouping** the slices into work items, and filling each item's
**Candidate signal**.

## Input

- **Window** — a string like `1d`, `4h`, `30m`, `today`, `HEAD~3..HEAD`,
  `main..HEAD`, `abc123..HEAD`, or `since=YYYY-MM-DD`.
- The current working directory, which must be a git repo.

## Step 1 — Build the deterministic bundle

Run the postcommit CLI to emit the bundle. The plugin bundles the package, so no
separate install is required — resolve the command in this order and use the
first that runs:

1. `postcommit extract <window> --per-commit` — a standalone install on PATH.
2. `~/.postcommit/bin/postcommit extract <window> --per-commit` — the
   plugin-bundled launcher (written by the SessionStart hook).
3. `python3 -m postcommit extract <window> --per-commit` — a source checkout.

In practice this one-liner picks the right one:

```
( command -v postcommit >/dev/null 2>&1 && postcommit extract <window> --per-commit ) \
  || ~/.postcommit/bin/postcommit extract <window> --per-commit
```

It prints a sliced work bundle to stdout: a repo header, a `## Filtered out` list
(merge commits, release chores — listed with a reason, never silently dropped),
then one `### Slice <sha> — <subject>` per commit carrying that commit's own
secret-masked diff and the session excerpts timestamped within it, plus a
`### Slice working` section when the tree is dirty. Capture it verbatim.

The `--per-commit` flag is what makes one post cover one piece of work. Without
it the CLI emits the old flat whole-window bundle, and everything downstream
collapses back into one post about a whole day.

If the bundle's only content is `> No meaningful work in window.`, stop and tell
the user plainly. Do not fabricate a bundle.

If none of the above resolve — no `postcommit` on PATH and no
`~/.postcommit/bin/postcommit` (e.g. Claude Code hasn't run a SessionStart since
the plugin was installed) — tell the user to restart Claude Code once so the hook
writes the launcher, or to install the CLI with `uv tool install postcommit`.
Don't guess at the extraction by hand.

## Step 2 — Group the slices into work items

A slice is one commit. A **work item** is one piece of work, which is usually
several commits: the feature plus its fixup plus its tests. Group slices that
share a feature or scope, sit next to each other in time, and touch overlapping
files. Four commits of one feature are one item, not four.

- Uncommitted work (`### Slice working`) is always its own item.
- Never merge two unrelated pieces of work to keep the count down — a shorter
  list is not the goal, one story per item is.
- Give each item an **id**: the newest commit's short sha in the group, or
  `working` for the uncommitted item.

## Step 3 — Fill each item's Candidate signal

For **every** item, using only facts present in its slices — never invent detail:

- **Problem:** 1 sentence, in the user's own domain terms.
- **Obvious-but-wrong first move:** 1 sentence, or "none evident".
- **Real fix / resolution:** 1 sentence, or "in progress / no clear resolution".
- **Surprising bit:** 1 sentence, or "none obvious — flag to writer".
- **Transferable lesson:** 1 sentence, or "none obvious".

If an item's signal is mostly "none obvious," say so on that item. The writer
downstream skips thin items rather than padding them, and this is what it reads
to decide.

## Step 4 — Return one bundle per item

Return a self-contained bundle per work item, in this shape, no preamble:

```
# Work item <id> — <one-line description>

- commits: <short shas + subjects>

## Git narrative
<the item's slices: diffs and stats, verbatim from the CLI output>

## Session narrative
<the session excerpts from those slices, verbatim>

## Candidate signal
<the five bullets, filled>
```

Also state plainly which commits the CLI filtered out and why — the caller
reports that to the user.

## Safety rules (non-negotiable)

- Everything runs locally. Never send transcripts, diffs, or drafts off the machine.
- The CLI already masks secret-looking values and caps the diff; if you still see
  anything that looks like a token, key, or `.env` content, re-mask it (show the
  filename, redact the value) before returning.
- Never include raw source beyond what the CLI already emits, and never add detail
  that is not in the bundle.
