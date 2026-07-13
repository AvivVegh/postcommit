"""postcommit.serve — the `postcommit-mcp` MCP server (optional).

Exposes the local work bundle over MCP so hosts beyond Claude Code (Cursor,
Codex, opencode, …) can pull it. Everything runs locally; the tools only read
git state and Claude Code transcripts on this machine — no network calls.

The MCP SDK is an optional dependency (`postcommit[mcp]`). It is imported lazily
so the core CLI and hooks install with zero dependencies; running
`postcommit-mcp` without the extra prints an install hint and exits non-zero.
"""

import os
import sys
from typing import Optional

INSTALL_HINT = (
    "postcommit-mcp needs the MCP SDK. Install the extra, e.g.:\n"
    "  uv tool install 'postcommit[mcp]'\n"
    "  # or: pip install 'postcommit[mcp]'"
)


def build_server():
    """Construct the FastMCP server. Raises ImportError if the extra is absent."""
    from mcp.server.fastmcp import FastMCP  # type: ignore

    from . import extract as _extract
    from . import state as _st

    server = FastMCP("postcommit")

    @server.tool()
    def extract_work_bundle(window: str, cwd: Optional[str] = None) -> str:
        """Build a local-only work bundle (git + Claude Code sessions) for a window.

        window: 1d | 4h | 30m | today | <sha>..<sha> | since=YYYY-MM-DD
        cwd:    repository path (defaults to the server's working directory)
        """
        return _extract.build_bundle(window, cwd or os.getcwd())

    @server.tool()
    def post_recommendation(cwd: Optional[str] = None) -> str:
        """Return the staged post-worthiness recommendation for a repo, if any."""
        import json
        rec = _st.read_json(_st.recommendation_path(cwd or os.getcwd()), None)
        return json.dumps(rec, indent=2) if rec else "(no recommendation staged)"

    return server


def main(argv=None):
    try:
        server = build_server()
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    server.run()  # stdio transport by default
    return 0


if __name__ == "__main__":
    sys.exit(main())
