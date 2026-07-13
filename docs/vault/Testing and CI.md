---
tags: [concept, tooling]
aliases: [tests, CI, ci.yml]
---

# Testing and CI

The executable surface (the `postcommit` package + thin hook shims + two Bash scripts) has a **stdlib-only `unittest`** suite — no pytest, no pip install. The prompt files ([[Post-Writer Agent|writer]], dispatcher, skill adapter) are still "tested" by hand via the wedge experiment (see [[Roadmap]]) and `docs/smoke-test.md`.

## Run
```
scripts/run-tests.sh          # python3 -m unittest discover -s tests
ruff check postcommit tests hooks    # lint: E/F/I/B (UP intentionally off — %-formatting)
bandit -r postcommit hooks           # security lint
```

## Coverage (`tests/`)
| File | Covers |
|---|---|
| `test_postcommit_state.py` | [[State]] — time/json/watermark/git helpers + `state` verbs |
| `test_session_end.py` | [[Scoring]] + [[Hooks]] — scoring, transcript parsing, shortstat, end-to-end staging |
| `test_session_start.py` | [[Hooks]] — nudge text + all five SessionStart gates |
| `test_extract.py` | [[Extractor]] — window parsing, secret masking, diff cap, distillation, assembly |
| `test_cli.py` | [[CLI]] — argparse dispatch, MCP graceful-degrade, install |
| `test_adapter.py` | the thin hook shims |

`tests/_support.py` puts the repo root on `sys.path`, builds throwaway git repos / transcript JSONLs, and `run_hook` drives the shims as subprocesses (`HOME` at a temp dir, `PYTHONPATH` at the checkout). **Add a test alongside any logic change.**

## CI — `.github/workflows/ci.yml`
- **`validate`** (required before merge) — parses manifests, checks `plugin.json`/`pyproject.toml` versions agree, verifies hooks exist + are `+x`, byte-compiles, installs + smoke-tests the CLI, runs `ruff` + the unittest suite, `shellcheck`s scripts.
- **`test-matrix`** — reruns the suite on Python 3.9 / 3.10 / 3.11.
- **`security-scan`** — `bandit` (non-blocking).
- **`version-guard`** (on release) — asserts the git tag equals `plugin.json` `version`.

## Related
[[Install and Distribution]] · [[Architecture]]
