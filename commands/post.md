---
description: Draft one LinkedIn post per piece of real work in this repo
argument-hint: <window: e.g. 1d, 4h, HEAD~3..HEAD, since=2026-07-01>
---

You are drafting LinkedIn posts about real work done in this repo within a specified window. **One post per piece of work** — not three posts about one blob of work, and not one post about a whole day.

**Window:** `$ARGUMENTS`

If `$ARGUMENTS` is empty, stop immediately and tell the user:
> `/post` requires a window argument. Examples: `/post 1d`, `/post 4h`, `/post HEAD~3..HEAD`, `/post since=2026-07-01`.

Otherwise, proceed through these steps in order. Do not skip steps. Do not print draft candidates to the chat — the user wants to review them in an editor, not inline.

## 1. Build the work bundles

Load and follow the `postcommit-extract` skill. Pass it the window `$ARGUMENTS`. It slices the window into one section per commit, filters the noise commits, and groups the slices into **work items** — returning one self-contained bundle per item, each with an id (the newest commit's short sha, or `working`).

If the skill reports "no meaningful work in window," stop and tell the user plainly. Do not fabricate a bundle.

Keep the skill's list of filtered-out commits — you report it in step 5.

## 2. Dispatch one post-writer per work item

Write a post for **every** item. There is no cap and no "pick the best N" — a day with 20 pieces of work gets 20 posts, because dropping 15 of them is the thing this command exists to stop. Thin items are handled by the writer's `SKIP`, not by truncating the list.

The items are independent, so dispatch them **in parallel — one message, one Agent call per item**. Claude Code bounds how many actually run at once, so a long list needs no manual batching. For each, use the Agent tool with:

- `subagent_type`: `post-writer`
- `description`: `Draft LinkedIn post`
- `prompt`: that item's complete bundle, followed by:

  > Produce exactly one LinkedIn post as instructed in your system prompt, in the angle that fits this item. Output raw markdown only — no preamble, no postscript, no chat.

Capture each subagent's full response verbatim.

A response of `SKIP: <reason>` means the item had no surprise and no takeaway. That is a correct outcome, not a failure: write no file for it and report the reason in step 5.

## 3. Save to disk

Get the drafts directory from the CLI — do **not** `mkdir` it yourself. The CLI creates it and makes `.postcommit/` self-ignoring (a `.gitignore` containing `*`), so drafts can never be committed by accident:

```
( command -v postcommit >/dev/null 2>&1 && postcommit state drafts-dir ) \
  || ~/.postcommit/bin/postcommit state drafts-dir
```

It prints the absolute path. Write **one file per post** to `<that path>/<UTC-ISO-8601>-<item id>.md` (e.g. `2026-07-04T20-15-33Z-a1b2c3.md` — colons replaced with dashes for filesystem safety). The item id suffix is not decoration: `/sync` reads it back as the ledger key, so a re-run over an overlapping window does not re-upload work already pushed.

Each file's contents must be:

```
# LinkedIn draft — <UTC ISO date>

- window: `<the $ARGUMENTS value>`
- repo: `<basename of cwd>`
- branch: `<current git branch>`
- item: `<item id>`
- commits: `<short shas of the item's commits>`
- generated: `<UTC ISO timestamp>`

---

<that item's subagent output, unmodified>
```

## 4. Open the result

One post: `open <path>`. More than one: `open <drafts dir>` so the user reviews them side by side.

## 5. Report

Print one short paragraph:

- How many posts were written, and where.
- What was dropped and why — commits the CLI filtered (merge, release) and items the writer returned `SKIP` for. Nothing else is ever dropped.
- A one-line summary of what went in, including the item count (e.g. "6 commits → 3 work items, 1 session, 5 files touched").
- Nothing else. No post previews. No commentary on quality.

## Rules

- Everything runs locally. Never send transcripts, diffs, or drafts off the machine.
- Never fabricate detail not present in the bundle.
- If the bundle contains anything that looks like secrets (tokens, `.env` contents, keys), the extract skill should have already masked them — double-check and re-mask if needed before dispatching.
