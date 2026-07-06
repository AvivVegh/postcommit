---
description: Hush postcommit LinkedIn-draft nudges for this repo for a few days
argument-hint: "[days: default 3]"
---

The user wants to silence the ambient postcommit nudge (the SessionStart reminder to run `/post`) for this repo.

**Days:** `$ARGUMENTS` — a positive integer number of days, or empty for the default of 3.

Run the postcommit state CLI to write the snooze. It operates on the current repo's `.postcommit/state/watermark.json`:

```
python3 ~/.postcommit/bin/postcommit-state snooze $ARGUMENTS
```

If `$ARGUMENTS` is empty, run it with no argument (defaults to 3 days).

If that path does not exist (postcommit isn't linked locally), fall back to writing the snooze directly:

1. Compute an ISO-8601 UTC timestamp `N` days from now (e.g. `python3 -c "from datetime import *; print((datetime.now(timezone.utc)+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ'))"`).
2. Read `.postcommit/state/watermark.json` (create the dir/file if missing), set `"snooze_until"` to that timestamp, and write it back.

Then tell the user, in one line, that nudges are hushed and until when. Do not do anything else.
