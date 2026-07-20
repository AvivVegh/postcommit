"""postcommit — turn real dev work into candidate LinkedIn posts, locally.

This is the code-first core. What used to live in prompt files and stdlib hooks
now lives here as importable modules with a stable CLI:

  postcommit.extract   deterministic git + session-transcript -> work bundle
  postcommit.scoring   cheap post-worthiness signals + scoring
  postcommit.state     per-repo/global state (watermark, recommendation, snooze)
  postcommit.hooks     SessionEnd / SessionStart hook logic
  postcommit.serve     optional MCP server (postcommit-mcp)

The Claude Code skill, command, agent, and hooks are thin adapters that shell
out to this package. Everything stays local — no network calls, ever.
"""

__version__ = "0.3.0"

__all__ = ["__version__"]
