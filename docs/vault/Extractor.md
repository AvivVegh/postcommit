---
tags: [component, code]
aliases: [extract.py]
---

# Extractor

**File:** `postcommit/extract.py` (~540 lines) · **Entry:** `build_bundle(window, cwd)`

Deterministic, code-first port of the old prompt-driven `postcommit-extract` skill. Assembles a compact, high-signal **work bundle** answering "what did the human actually do here?" from local sources only — git state plus Claude Code session transcripts. **No network.**

This is where the [[Privacy Model|privacy rules]] live.

## The pipeline (build_bundle)

1. **Parse the window** — `parse_window()` resolves a window string into a `cutoff` (tz-aware UTC lower bound) + git ranges + label. Accepts:
   - durations `1d` / `4h` / `30m`
   - `today` (local midnight → UTC)
   - git ranges `HEAD~3..HEAD`, `main..HEAD`, `<sha>..<sha>`
   - `since=YYYY-MM-DD`
   - Raises `WindowError` on anything else.
   - For time windows the diff base is the newest commit *before* the window; if none precedes it, diff against git's **empty tree** (`4b825dc…`) so a repo's first commit still shows.
2. **Gather git state** — `gather_git()`: toplevel (raises `NotARepoError` if outside a work tree), branch, porcelain status, in-window commits, shortstat, capped+masked diff, uncommitted flag.
3. **Locate transcripts** — `transcript_dir()` / `_transcript_files()` — see [[Session Transcripts]].
4. **Distill each session** — `distill_session()` turns one JSONL into a scannable narrative block (user prompts as `>`, assistant text/tool_use as `-`, thinking skipped, `isSidechain` skipped, timestamps ≥ cutoff).
5. **Emit the bundle** — markdown: Repo header, Git narrative (commits / uncommitted / diff highlights), Session narrative, and the **Candidate signal** stub.

## Privacy machinery (lives here)

- `scrub_text()` — the single choke point. Redacts `key=value` secrets, URL creds (`scheme://user:pass@host`), `Bearer <token>`, and well-known token shapes (OpenAI/Stripe `sk-`, GitHub `gh?_`, AWS `AKIA`, Slack `xox?`, JWT). Everything user-authored or transcript-derived passes through it.
- `mask_secrets()` — drops the body of sensitive files (`.env`, `*.pem`, `credentials*`, `secrets*`) wholesale; runs every other diff line through `scrub_text`.
- `cap_diff()` — caps the diff at `DIFF_CHAR_CAP` (~40k chars), keeping file/hunk structure and replacing elided bodies with `[N lines elided]`.

Constants: `MAX_PROMPT_CHARS=280`, `MAX_LINE_CHARS=200`, `MAX_TOOL_CHARS=120`.

## Consumes / produces
- Uses [[State]] for `git()`, `now_utc()`, `parse_iso()`, `parse_shortstat()`, `iso()`.
- Output consumed by [[Data Flow|the /post flow]] and [[MCP Server]] (`extract_work_bundle` tool).

## Tests
`tests/test_extract.py` — window parsing, secret masking, diff cap, transcript distillation, bundle assembly. See [[Testing and CI]].

## Related
[[Session Transcripts]] · [[Privacy Model]] · [[Scoring]] (shares transcript-parsing conventions)
