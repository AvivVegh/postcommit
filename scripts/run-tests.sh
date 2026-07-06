#!/usr/bin/env bash
# Run the postcommit test suite. Stdlib `unittest` only — no pip install, no
# third-party deps, matching the hooks themselves. Needs python3 and git on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

exec python3 -m unittest discover -s tests -p 'test_*.py' "$@"
