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

It prints a machine-readable `status: <state>` line and never prints the token. Exit code 0 means the credentials are usable. Remember which tier resolved — call it `<CLI>` below and reuse it for every later command.

If every tier fails with something like `invalid choice: 'cloud'`, the installed postcommit predates this verb. Tell the user to run `/plugin update postcommit` and restart Claude Code once. Do not fall back to hunting for a source checkout.

## 2. Act on the state

| `status:` | What to do |
|---|---|
| `active` | Say they're signed in, and as whom. Then offer re-auth (step 3). |
| `active-unverified` | Signed in, but the API was unreachable to confirm. Say so in one line, then offer re-auth (step 3). |
| `signed-out` | Go to step 3. |
| `rejected` | The server refused the token. Say it was revoked or the account changed, then go to step 3. |

## 3. Ask how they want to proceed

Use the **AskUserQuestion** tool. One question, header `Sign-in`. Do not write the options out as prose and wait for a typed reply — the picker is the point.

**When `signed-out` or `rejected`** — question: "How do you want to sign in to postcommit cloud?"

1. **Browser handoff (Recommended)** — "Opens the dashboard; approval comes back over a local loopback port. Nothing to copy, and no token enters this chat."
2. **Paste in my own terminal** — "For headless or SSH boxes with no browser. You get the exact command to run yourself."

**When `active` or `active-unverified`** — question: "You're already signed in. Re-authenticate?"

1. **Stay signed in (Recommended)** — "Keep the current credentials. Nothing changes."
2. **Re-authenticate in the browser** — "Signs in again and overwrites the stored credentials with a fresh token."
3. **Re-authenticate by pasting in my own terminal** — "Same, for machines with no browser."

If they pick *Stay signed in*, stop — go to step 5.

Never offer `postcommit cloud logout` as an option here. It deletes the refresh token and is only ever run on an explicit request to sign out.

## 4. Run the chosen flow

### Browser handoff

Run this **in the background** — the CLI waits up to 300s for the browser handoff, which is longer than a foreground command call will sit for:

```
<CLI> cloud login --browser
```

It prints `Opening <url> in your browser to authorize…` before it starts waiting. Read that line from the running command's output and show the user the URL, so a browser that failed to auto-open doesn't leave them staring at nothing for five minutes.

Its output is safe to relay — the URL, a `Signed in as <email>` line, and the credentials path. It never prints the token.

When it finishes, re-run `<CLI> cloud status` and report the new state. If it timed out, say so and offer to run it again.

### Paste in their own terminal

Open the dashboard token page:

```
open https://platform.postcommit.dev
```

If `POSTCOMMIT_DASHBOARD_URL` is set in the environment, open that instead of the default.

Then tell the user, in this order and nothing more:

1. Copy the token from the dashboard.
2. Run this in **their own terminal**, using the tier that resolved in step 1:
   ```
   postcommit cloud login
   ```
3. Paste it at that prompt. Not here.

Explain in one short clause *why* it has to be their terminal: the token would otherwise be captured in this session's transcript.

Then stop. Do **not** run `postcommit cloud login` yourself — it blocks waiting on stdin that a tool call cannot supply, and it will simply hit EOF and fail.

## 5. Report

One or two lines: the state, and either who they're signed in as or what they need to do next. No token, no credential path contents, no speculation about their account.

## Rules

- Authentication only — this command sends no repo content. `/post`, the extract skill, and the hooks stay entirely local.
- `postcommit cloud logout` deletes stored credentials, including the refresh token. **Destructive.** Only on an explicit request to sign out, never as a check or a probe.
