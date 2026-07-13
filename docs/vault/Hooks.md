---
tags: [component, code]
aliases: [hooks.py, habit loop, SessionEnd, SessionStart]
---

# Hooks

**File:** `postcommit/hooks.py` (~145 lines) — the **habit loop** (Phase 1, see [[Roadmap]]).

The thin scripts under `hooks/` (`session-end.py`, `session-start.py`, sharing `_adapter.py`) forward their stdin payload to `postcommit hook session-end|session-start` ([[CLI]]), which calls the two functions here. Registered via `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}` (see [[Plugin Surface]]).

> [!warning] A broken hook must never break a session
> The `hook` CLI verbs swallow all exceptions and exit 0.

## `handle_session_end(payload)`
Cheap, deterministic (**no model call**), idempotent, once per session end.
1. Bail if not a git repo.
2. Bail if `session_id` already in the watermark's `processed_sessions` (idempotent).
3. Parse transcript signals ([[Scoring]]).
4. **If the user already ran `/post` this session** (`fresh_draft_since`): pin the watermark to HEAD, stamp `posted_at`, drop any stale rec. Don't nudge about spent work.
5. Else: compute git+transcript score. If `score ≥ POST_WORTHY_THRESHOLD` (5), write `recommendation.json` (score, verdict, reasons, `window_hint`, `summary_line`, head, branch…).
6. Record the session as processed; save watermark.

It never generates a post — only decides "was there post-worthy work?" and stages a lightweight recommendation.

## `handle_session_start(payload) → str | None`
**Instant** — file reads only, never generates. Returns the `additionalContext` nudge string (and stamps the daily cooldown) only when **all five gates pass**:

1. **Fresh start** — `source` ∈ {`startup`, `clear`}, never `resume`.
2. **Staged rec** — a `post-worthy` recommendation exists for this repo.
3. **Unposted** — the rec's head ≠ `last_posted_head`, and `posted_at` isn't newer than the rec.
4. **Not snoozed** — `now < snooze_until`.
5. **Daily cooldown** — global `nudge-state.json` `last_nudge_date` ≠ today.

On success it stamps the cooldown and returns the nudge (`build_nudge`), which tells the model to surface the reminder in its first reply: run `/post <window_hint>` or `/post-snooze`.

## State touched
All via [[State]]: `recommendation.json`, `watermark.json`, `~/.postcommit/nudge-state.json`.

## Tests
`tests/test_session_start.py` (nudge text + all five gates), `tests/test_session_end.py` (staging), `tests/test_adapter.py` (the shims). See [[Testing and CI]].

## Related
[[Scoring]] · [[State]] · [[Data Flow]] · [[Plugin Surface]]
