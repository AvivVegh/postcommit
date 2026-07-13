---
tags: [concept, non-obvious]
---

# Session Transcripts

The non-obvious detail that both the [[Extractor]] and [[Scoring]] depend on.

## Where they live

Claude Code session transcripts are JSONL files at:

```
~/.claude/projects/<encoded-cwd>/<uuid>.jsonl
```

where `<encoded-cwd>` is the absolute cwd with every `/` replaced by `-` and a leading `-`.

## The encoding ambiguity

`extract.transcript_dir(cwd)` computes that path. Some Claude Code versions also **fold `.` to `-`**, so it tries a `.`-folded variant too. That folded form is ambiguous — `foo.bar` and `foo-bar` both encode to `-...-foo-bar` — so:

- The **exact** encoding (`/`→`-` only) is trusted as-is.
- The **folded fallback** is verified against the session's recorded `cwd` (`_dir_is_for_cwd`) before it's trusted, to avoid emitting a sibling repo's transcripts. If no record carries a `cwd` at all, it can't tell, so it falls back to trusting the dir rather than dropping legitimate data.

## Record filtering

Both consumers apply the same conventions:
- Records are filtered by `.timestamp` against the window cutoff.
- `isSidechain` (sub-agent) records are **skipped** so the human's own work is what's scored/narrated.
- `isMeta` user records and `<system-reminder>` / `<command-name>` / `<local-command-*>` prefixed content are skipped.
- A `None` cutoff (e.g. an empty git range `HEAD..HEAD`) means **no transcripts** — without a lower bound every session in the repo would be scoped in.

## Related
[[Extractor]] · [[Scoring]] · [[Privacy Model]]
