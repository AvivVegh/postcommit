---
description: Log in to postcommit cloud so drafts can be scheduled and published
argument-hint: "[--browser | <token>]"
---

The user wants to authenticate against **postcommit cloud** — the optional, paid service that schedules and publishes approved drafts to LinkedIn.

This is the one postcommit command that touches the network. It sends **authentication only**: no transcripts, no diffs, no drafts. `/post` and the extract skill remain entirely local.

**Argument:** `$ARGUMENTS` — empty (paste flow, the default), `--browser` (loopback flow), or a token string for scripting.

## 1. Run the login

The cloud CLI is a separate entry point from `postcommit`, so resolve it in this order and use the first that runs:

1. `postcommit-cloud-mcp login $ARGUMENTS` — a standalone install on PATH.
2. `python3 -m postcommit.serve_cloud login $ARGUMENTS` — the bundled package or a source checkout.

In practice this one-liner picks the right one:

```
( command -v postcommit-cloud-mcp >/dev/null 2>&1 \
    && postcommit-cloud-mcp login $ARGUMENTS ) \
  || python3 -m postcommit.serve_cloud login $ARGUMENTS
```

Note `login` and `logout` are dispatched before the MCP server is built and depend only on the standard library, so they work even when the `[cloud]` extra isn't installed. The extra is needed only to *run* the server, not to authenticate.

**The default flow is interactive and waits on stdin.** With no arguments it prompts the user to paste a token copied from the dashboard. Run it so the user can see the prompt and paste; do not try to answer the prompt yourself, and never invent a token. If the command is blocked from running interactively, stop and tell the user to run it themselves in a terminal — give them the exact command.

With `--browser` it instead opens the dashboard and waits for a one-shot `127.0.0.1` handoff; that flow needs a usable browser and times out after 300 seconds.

## 2. Report

On success it prints the signed-in identity and the credentials path. Relay in one line: that they are signed in, as whom, and that the token refreshes automatically from here — logging in again is not needed.

On failure, relay the CLI's own error verbatim. The usual causes are a malformed or truncated paste, an expired token from the dashboard, or a `--browser` timeout. Do not retry with a different flow unless the user asks.

## Rules

- Never print, echo, or write the token, the credentials file, or any of its contents into the chat, a file, or a commit. It grants access to the user's account.
- Never send repo content anywhere. This command handles authentication only.
- `postcommit-cloud-mcp logout` deletes the stored credentials — **destructive**. Only run it if the user explicitly asks to sign out, and never as a test or a probe.
