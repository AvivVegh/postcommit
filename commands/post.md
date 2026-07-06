---
description: Draft 3 candidate LinkedIn posts from real work in this repo
argument-hint: <window: e.g. 1d, 4h, HEAD~3..HEAD, since=2026-07-01>
---

You are drafting LinkedIn posts about real work done in this repo within a specified window.

**Window:** `$ARGUMENTS`

If `$ARGUMENTS` is empty, stop immediately and tell the user:
> `/post` requires a window argument. Examples: `/post 1d`, `/post 4h`, `/post HEAD~3..HEAD`, `/post since=2026-07-01`.

Otherwise, proceed through these steps in order. Do not skip steps. Do not print draft candidates to the chat — the user wants to review them in an editor, not inline.

## 1. Build the work bundle

Load and follow the `postcommit-extract` skill. Pass it the window `$ARGUMENTS`. It will return a markdown work bundle covering git state and Claude Code session activity for this repo within the window.

If the skill reports "no meaningful work in window," stop and tell the user plainly. Do not fabricate a bundle.

## 2. Dispatch to the post-writer subagent

Use the Agent tool with:

- `subagent_type`: `post-writer`
- `description`: `Draft LinkedIn posts`
- `prompt`: the complete work bundle from step 1, followed by:

  > Produce exactly 3 candidate LinkedIn posts as instructed in your system prompt. Output raw markdown only — no preamble, no postscript, no chat.

Capture the subagent's full response verbatim.

## 3. Save to disk

Create `.postcommit/drafts/` in the repo root if it doesn't exist. Write the drafts to `.postcommit/drafts/<UTC-ISO-8601>.md` (e.g. `2026-07-04T20-15-33Z.md` — colons replaced with dashes for filesystem safety).

The file's contents must be:

```
# LinkedIn draft candidates — <UTC ISO date>

- window: `<the $ARGUMENTS value>`
- repo: `<basename of cwd>`
- branch: `<current git branch>`
- generated: `<UTC ISO timestamp>`

---

<the subagent's raw output, unmodified>
```

## 4. Open the file

Run `open <path>` so the user can review in their default editor.

## 5. Report

Print exactly one short paragraph:

- The saved file path.
- A one-line summary of what went into the bundle (e.g. "2 commits, 1 session, ~47 min active work, 5 files touched").
- Nothing else. No candidate previews. No commentary on quality.

## Rules

- Everything runs locally. Never send transcripts, diffs, or drafts off the machine.
- Never fabricate detail not present in the bundle.
- If the bundle contains anything that looks like secrets (tokens, `.env` contents, keys), the extract skill should have already masked them — double-check and re-mask if needed before dispatching.
