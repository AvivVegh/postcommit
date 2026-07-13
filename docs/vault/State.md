---
tags: [component, code]
aliases: [state.py]
---

# State

**File:** `postcommit/state.py` (~280 lines) · dependency-free (stdlib)

Local-only state for the [[Hooks|habit-loop hooks]], plus the home for the small **time and git helpers** the rest of the package builds on ([[Extractor]] and [[Scoring]] both import it).

## State lives in three places

| Path | Scope | Holds |
|---|---|---|
| `<repo>/.postcommit/state/recommendation.json` | per-repo | the staged nudge |
| `<repo>/.postcommit/state/watermark.json` | per-repo | what's processed/posted + snooze |
| `~/.postcommit/nudge-state.json` | global | once-per-day cooldown |

`.postcommit/` is gitignored, so per-repo state never leaks. See [[Privacy Model]].

## What it provides

- **Time:** `now_utc()`, `iso()` (UTC ISO-8601 `Z`), `parse_iso()` (always returns tz-aware; assumes UTC when no offset — keeps every downstream subtraction tz-safe), `today_local()` (the unit of the daily cooldown).
- **Paths:** `state_dir`, `recommendation_path`, `watermark_path`, `global_dir`, `nudge_state_path`.
- **JSON I/O:** `read_json` (default on any error), `write_json` (**atomic**: temp file in same dir → `os.replace`).
- **Watermark:** `default_watermark()` / `read_watermark` (bounds `processed_sessions` to the last 200) / `write_watermark`. Fields: `last_posted_head`, `posted_at`, `snooze_until`, `processed_sessions`, `last_end_head`.
- **Git helpers:** `git()` (10s timeout, `None` on error), `is_git_repo`, `git_head`, `is_ancestor`, `parse_shortstat` (shared by [[Extractor]] and [[Scoring]] so git's wording is tracked in one place).

## `state` CLI verbs

Backing `postcommit state ...` (see [[CLI]]):
- `show` — dump watermark + recommendation + global nudge-state
- `snooze [N]` (default 3 days) / `unsnooze`
- `mark-posted` — pin watermark to HEAD, drop the rec
- `stage-fake` — stage a fake post-worthy rec for testing the nudge
- `reset` — remove rec + watermark

## Tests
`tests/test_postcommit_state.py` — time/json/watermark/git helpers + `state` verbs.

## Related
[[Hooks]] · [[CLI]] · [[Extractor]] · [[Scoring]]
