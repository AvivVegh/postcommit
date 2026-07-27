---
description: Push saved local drafts to postcommit cloud
argument-hint: ""
---

The user wants to upload the LinkedIn draft candidates saved in this repo to **postcommit cloud**, where they can be scheduled and published.

This is the only command besides `/login` that sends anything over the network, and unlike `/login` it sends *content*. Treat the confirmation step in §3 as mandatory.

## 1. Check they're signed in

Resolve the CLI in this order and use the first that runs — call it `<CLI>` and reuse it for every later command:

1. `postcommit cloud status` — a standalone install on PATH.
2. `~/.postcommit/bin/postcommit cloud status` — the plugin-bundled launcher.
3. `python3 -m postcommit cloud status` — a source checkout.

```
( command -v postcommit >/dev/null 2>&1 && postcommit cloud status ) \
  || ~/.postcommit/bin/postcommit cloud status
```

| `status:` | What to do |
|---|---|
| `active` / `active-unverified` | Go to step 2. |
| `signed-out` / `rejected` | Stop. Tell them to run `/login` first, and nothing else. Do not attempt the sync. |

## 2. Show the plan

Never upload before the user has seen what would go. Run:

```
<CLI> cloud sync --dry-run
```

This touches no network. It lists each post that would be pushed as `<draft file>  post — <angle> (<n> chars)`, plus anything skipped and a count of what has already been synced. Drafts written before the one-post-per-work-item split hold three candidates each and list as `Candidate <A|B|C> — <angle>`; they still sync, and their ledger entries still block re-pushes.

Relay that list as-is. Do **not** print the post bodies — the user reviews those in the draft files, not in chat.

If it says nothing is pending, say so and stop.

## 3. Confirm, then push

Show the total — "this uploads N posts from M draft files" — and ask the user to confirm before running anything.

Note plainly, in one line, that this pushes **every unsynced draft in the repo**, not only the ones from their last `/post` run — and that any pre-split draft still on disk contributes all three of its candidates. The drafts are derived from session transcripts, so a bulk upload should never be a surprise.

Only after they agree:

```
<CLI> cloud sync
```

Each successful push is recorded in `.postcommit/state/synced.json` as it happens, so re-running never creates duplicates and an interrupted run is safe to resume.

## 4. Report

One or two lines: how many were pushed, skipped, or failed, and where to review them. No post bodies, no candidate previews.

Common outcomes worth relaying verbatim:

- A post skipped for exceeding the 3000-character cap — say which draft, so they can trim it.
- A run aborted because the cloud rejected the credentials — tell them to run `/login` and retry.
- A run aborted because the account has no active subscription — point them at the dashboard's billing page. Do **not** suggest `/login`: the credentials are fine, and re-authenticating just returns them to the same error.

## Rules

- Nothing here reads git history or session transcripts. It uploads only the post bodies already saved under `.postcommit/drafts/`, with the `### Post` / `### Candidate` labels and the legacy `— why this angle` reviewer notes stripped by the CLI.
- `/post`, the extract skill and the hooks stay entirely local — never add a cloud call to them.
- Never re-upload by hand to "fix" a failure. The ledger exists to keep runs idempotent; just re-run `<CLI> cloud sync`.
