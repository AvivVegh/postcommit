---
tags: [component, code]
aliases: [scoring.py]
---

# Scoring

**File:** `postcommit/scoring.py` (~250 lines)

Cheap, **deterministic** post-worthiness signals — no model calls. This is the analysis the SessionEnd hook ([[Hooks]]) runs to decide "was there post-worthy work here?" Kept separate from the hook wiring so it is unit-testable in isolation.

## Two signal sources

### Transcript signals — `parse_transcript(path)`
Reads a session JSONL (capped at `MAX_TRANSCRIPT_LINES=8000`) and counts:
- `n_user_prompts` — real prompts (skips meta / system-reminder / sidechain, same rules as [[Session Transcripts]])
- `n_edits` — Edit/Write/MultiEdit/NotebookEdit tool_use blocks
- `duration_min` — **active** minutes: sum of gaps between events, counting only gaps ≤ `IDLE_GAP_SECONDS` (15 min). A session left open all day is mostly one giant idle gap, so it no longer reads as hours of work (false-positive guard).
- `keywords` — matches against `_STORY_KEYWORDS` (bug, crash, race, deadlock, leak, regression, root cause, panic…) → the "debugging-story signal".
- `first_ts` — used by draft-freshness checks.

### Git signals — `git_signals(cwd, last_posted_head)`
Commit count + diff size **since the last post** (`last_posted_head..HEAD` if it's an ancestor of HEAD), else a **24h fallback**. Note: `git diff` ignores `--since`, so churn for the last day is measured against a real base rev (newest commit older than the window, or the empty tree). Uncommitted work counts toward "there is something to talk about."

## The score — `score(git_sig, tx_sig)`

Threshold: **`POST_WORTHY_THRESHOLD = 5`**. Points:
- commits: +3 each, capped at +6
- churn ≥30 over ≥2 files: +2 (+1 more if ≥150), else uncommitted churn: +1
- ≥3 edits: +1 · ≥3 prompts: +1 · ≥15 active min: +1 · story keywords: +1
- **trivial-change guard:** no commits AND churn <10 → score clamped below the threshold.

Returns `(points, reasons)` — reasons are human-readable strings surfaced in the [[Hooks|nudge]].

Also: `summary_line()` (the "2 commits, 3 files touched, ~47 min" line) and `fresh_draft_since()` (did the user already run `/post` this session? → don't nudge).

## Consumes
[[State]] helpers (`git`, `parse_iso`, `parse_shortstat`, `is_ancestor`).

## Tests
`tests/test_session_end.py` — scoring, transcript parsing, shortstat, end-to-end staging.

## Related
[[Hooks]] · [[Extractor]] · [[Session Transcripts]]
