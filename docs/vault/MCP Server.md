---
tags: [component, code, optional]
aliases: [serve.py, postcommit-mcp]
---

# MCP Server

**File:** `postcommit/serve.py` (~60 lines) · **Entry point:** `postcommit-mcp` · **optional** `[mcp]` extra (`mcp>=1.2`, Python ≥3.10)

Exposes the local work bundle over MCP so hosts beyond Claude Code (Cursor, Codex, opencode, …) can pull it. Everything runs locally — the tools only read git state and [[Session Transcripts|transcripts]] on this machine, **no network calls** (see [[Privacy Model]]).

## Lazy import = zero-dependency core
The MCP SDK is imported lazily inside `build_server()`, so the core [[CLI]] and [[Hooks]] install with **zero dependencies**. Running `postcommit-mcp` without the extra prints an install hint and exits non-zero (graceful degrade — covered by `tests/test_cli.py`).

## Tools (FastMCP)
- **`extract_work_bundle(window, cwd?)`** → calls [[Extractor|`extract.build_bundle`]]. Same window forms as the CLI.
- **`post_recommendation(cwd?)`** → returns the staged [[State|recommendation.json]] for a repo, if any.

Runs on stdio transport by default.

## Related
[[CLI]] · [[Extractor]] · [[Install and Distribution]] · [[Roadmap]]
