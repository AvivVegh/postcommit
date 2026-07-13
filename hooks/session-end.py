#!/usr/bin/env python3
"""Thin SessionEnd adapter — forward the payload to the installed postcommit CLI.

All logic lives in the `postcommit` package (postcommit.hooks). This shim only
pipes the hook's stdin payload to `postcommit hook session-end`, preferring the
installed console script and falling back to `python -m postcommit` for a source
checkout. It always exits 0 — a hook must never break a user's session.
"""

import sys

from _adapter import forward  # sibling module in hooks/

if __name__ == "__main__":
    try:
        forward("session-end")
    except Exception:
        pass
    sys.exit(0)
