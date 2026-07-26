---
description: Check or set up postcommit cloud authentication
argument-hint: ""
---

The user wants to know whether they're signed in to **postcommit cloud** — the optional service that schedules and publishes approved drafts — and to sign in if not.

## Rule zero: never handle the token

Do **not** ask the user to paste their token into this chat, and if they paste one anyway, do not echo it, store it, or pass it to any command. Tell them it is now in the session transcript and they should rotate it from the dashboard.

This is not boilerplate. The token is a base64 bundle holding a long-lived `refresh_token` — permanent account access. Anything in this chat is written to the Claude Code session transcript, and `postcommit extract` reads those transcripts to build work bundles, which become drafts, which get published. A token pasted here can end up in a LinkedIn post.

The token is pasted by the user, in their own terminal, into a command they run themselves. You never see it.

## 1. Check the current state

Resolve the CLI in this order and use the first that runs:

1. `postcommit cloud status` — a standalone install on PATH.
2. `~/.postcommit/bin/postcommit cloud status` — the plugin-bundled launcher.
3. `python3 -m postcommit cloud status` — a source checkout.

```
( command -v postcommit >/dev/null 2>&1 && postcommit cloud status ) \
  || ~/.postcommit/bin/postcommit cloud status
```

It prints a machine-readable `status: <state>` line and never prints the token. Exit code 0 means the credentials are usable.

If every tier fails with something like `invalid choice: 'cloud'`, the installed postcommit predates this verb. Tell the user to run `/plugin update postcommit` and restart Claude Code once. Do not fall back to hunting for a source checkout.

## 2. Act on the state

| `status:` | What to do |
|---|---|
| `active` | Tell the user they're signed in, and as whom. **Stop — nothing else to do.** |
| `active-unverified` | Signed in, but the API was unreachable to confirm. Say so in one line and stop; do not send them to log in again. |
| `signed-out` | Go to step 3. |
| `rejected` | The server refused the token. Say it was revoked or the account changed, then go to step 3. |

## 3. Send them to the dashboard

Only for `signed-out` and `rejected`.

Open the dashboard token page:

```
open https://platform.postcommit.dev
```

If `POSTCOMMIT_DASHBOARD_URL` is set in the environment, open that instead of the default.

Then tell the user, in this order and nothing more:

1. Copy the token from the dashboard.
2. Run this in **their own terminal** — give them the exact line, using whichever tier resolved in step 1:
   ```
   postcommit cloud login
   ```
3. Paste it at that prompt. Not here.

Explain in one short clause *why* it has to be their terminal: the token would otherwise be captured in this session's transcript.

Then stop. Do not run `postcommit cloud login` yourself — it blocks waiting on stdin that a tool call cannot supply, and it will simply hit EOF and fail. Offer `postcommit cloud login --browser` only if the user says they'd rather not paste; that flow needs no stdin, opens the dashboard, and waits for a loopback handoff (300s timeout).

## 4. Report

One or two lines: the state, and either who they're signed in as or what they need to do next. No token, no credential path contents, no speculation about their account.

## Rules

- Authentication only — this command sends no repo content. `/post`, the extract skill, and the hooks stay entirely local.
- `postcommit cloud logout` deletes stored credentials, including the refresh token. **Destructive.** Only on an explicit request to sign out, never as a check or a probe.
