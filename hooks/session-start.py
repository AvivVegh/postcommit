#!/usr/bin/env python3
"""Thin SessionStart adapter — forward the payload to the installed postcommit CLI.

All logic lives in the `postcommit` package (postcommit.hooks). This shim pipes
the hook's stdin payload to `postcommit hook session-start` and passes the CLI's
stdout (the additionalContext JSON, if any) straight through. It always exits 0.
"""

import sys

from _adapter import forward  # sibling module in hooks/

if __name__ == "__main__":
    try:
        forward("session-start")
    except Exception:
        pass
    sys.exit(0)
