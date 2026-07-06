---
name: postcommit-extract
description: Extract a compact "work bundle" (git state + Claude Code session excerpts) from the current repo over a specified window, for downstream drafting of LinkedIn posts. Use when the /post command runs, or when the user asks for a distilled summary of what they actually did in this repo over a specific period.
---

# postcommit-extract

Your job: assemble a compact, high-signal **work bundle** that answers "what did the human actually do here, and what was interesting about it?" — from local sources only. No network. Nothing leaves the machine.

## Input

- **Window** — a string like `1d`, `4h`, `30m`, `today`, `HEAD~3..HEAD`, `main..HEAD`, `abc123..HEAD`, or `since=YYYY-MM-DD`.
- The current working directory, which must be a git repo.

## Step 1 — Parse the window

Translate the window into two things:

- a **git range** for `git log` / `git diff`
- a **cutoff timestamp (UTC)** for filtering session events

Rules:

- `1d`, `4h`, `30m` — duration ending now. Cutoff = now minus that duration. Git range = `--since=<cutoff>`.
- `today` — cutoff = today 00:00 local. Git range = `--since=<cutoff>`.
- `HEAD~N..HEAD`, `main..HEAD`, `<sha>..HEAD`, `<sha>..<sha>` — pass through as the git range. Cutoff = author timestamp of the earliest commit in the range.
- `since=YYYY-MM-DD` — cutoff = that date 00:00 local. Git range = `--since=YYYY-MM-DD`.
- Anything else — stop and tell the user the valid forms.

## Step 2 — Gather git state

Confirm we're inside a repo: `git rev-parse --show-toplevel`. If not, stop.

Collect:

- `git rev-parse --abbrev-ref HEAD` — current branch.
- `git status --porcelain=v1` — uncommitted files.
- `git log --pretty=format:'%h %ci %s' <range>` — commit list.
- `git diff --stat <range>` — files touched and change size.
- `git diff <range>` — the actual diff. **Cap at ~40,000 characters.** If longer, keep hunk headers (`@@ ... @@`) and file boundaries but replace long hunks with `[N lines elided]` so structure is preserved.
- `git diff` (unstaged) and `git diff --staged` for uncommitted work.

## Step 3 — Locate session transcripts

Claude Code stores session JSONLs at:

```
~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl
```

`<encoded-cwd>` = the absolute cwd with every `/` replaced by `-`, then prefixed with `-`.

Example: `/Users/aviv/Documents/repos/postcommit` → `-Users-aviv-Documents-repos-postcommit`.

Select every `*.jsonl` in that directory whose file **mtime is ≥ cutoff**. If none exist, note that and continue with git-only material.

## Step 4 — Parse each JSONL

Each line is one JSON record. Read line by line.

**Keep** these records (filter each by outer `.timestamp >= cutoff`):

- `type: "user"` where `.message.content` is a **string** AND `isMeta` is not `true` AND the string does not start with any of `<local-command-caveat>`, `<command-name>`, `<local-command-stdout>`, `<system-reminder>`. These are the human's real prompts.
- `type: "assistant"`, then iterate `.message.content[]`:
  - `type: "text"` — assistant prose. Keep, but truncate embedded fenced code blocks to ≤10 lines each with `[...N lines elided...]`.
  - `type: "tool_use"` — record only `name` + a one-line summary of `input` (e.g. `Bash: git status --porcelain`, `Edit: src/foo.ts`, `Read: package.json`). **Never** keep raw file contents from tool inputs.
  - `type: "thinking"` — skip entirely.

**Skip** everything else: `tool_result` bodies, `file-history-snapshot`, `permission-mode`, `ai-title`, `attachment`, `last-prompt`, and any record where `isSidechain` is `true` (that's subagent noise).

## Step 5 — Distill each session into a narrative

For each kept session, produce a scannable chronological summary — not a full replay:

- User prompts as `> ...` quotes. Paraphrase if verbose, but **preserve specifics**: error messages, file paths, tool names, numbers, framework names. Those are the atoms that make a post feel real.
- Assistant text as one-line summaries of what was tried or decided.
- Tool activity as bullets: `- ran <cmd>`, `- edited <file> (<N lines>)`, `- searched <pattern>`.

## Step 6 — Emit the work bundle

Return exactly this markdown document, no preamble:

```
# Work bundle — <UTC ISO date> — window: <arg>

## Repo
- path: <abs path>
- branch: <branch>
- commits in window: <N>
- files changed: <N>  (+<additions> / -<deletions>)

## Git narrative

### Commits
- <hash> <date> — <subject>
- ...
(or "none")

### Uncommitted
<summary of git status; or "clean">

### Diff highlights
<compacted diff — headers + selected hunks, secrets masked>

## Session narrative

### Session <short-uuid> — <first ts> → <last ts>
> user prompt 1 (paraphrased if verbose)
- assistant tried X (Bash: <cmd>)
- assistant edited <file>
> user prompt 2
- ...

(repeat per session; or "no session transcripts in window")

## Candidate signal (best guesses, for the writer)
- **Problem:** <1 sentence, in the user's own domain terms>
- **Obvious-but-wrong first move:** <1 sentence, or "none evident">
- **Real fix / resolution:** <1 sentence, or "in progress / no clear resolution">
- **Surprising bit:** <1 sentence, or "none obvious — flag to writer">
- **Transferable lesson:** <1 sentence, or "none obvious">
```

If the "Candidate signal" section is mostly "none obvious," say so at the top of the bundle so the writer downstream can decide whether to draft at all.

## Safety rules (non-negotiable)

- **Never include raw source beyond ~10 lines per snippet.** Summarize instead.
- **Mask anything that looks like a secret** — env vars, tokens, API keys, `.env` contents, files named `credentials*`, `secrets*`, `*.pem`, `*.key`. Show the filename only, contents redacted.
- **No network.** Only local file reads and git commands.
- If the window contains nothing meaningful (no commits, no uncommitted work, no matching session events), emit an almost-empty bundle with a single top line: `> No meaningful work in window.` — and stop.
