"""postcommit.serve_cloud — the `postcommit-cloud-mcp` MCP server (optional).

A SECOND, separate MCP server from serve.py. Where serve.py is strictly local
(git + transcripts, no network), this one is a thin passthrough to the
postcommit-cloud REST API — so it lives behind its own `[cloud]` extra and never
touches the local-only guarantee of the free plugin.

Six tools, each a thin wrapper over CloudClient returning JSON text:

  create_post · list_posts · update_post · delete_post
  linkedin_status · linkedin_disconnect

The MCP SDK is an optional dependency (`postcommit[cloud]`), imported lazily so
the dependency-free core still installs; running `postcommit-cloud-mcp` without
the extra prints an install hint and exits non-zero — mirroring serve.py.

`main()` also dispatches the `login` / `logout` subcommands to cloud_login
*before* touching the MCP SDK, so authenticating works without the extra.
"""

import json
import sys
from typing import Optional

INSTALL_HINT = (
    "postcommit-cloud-mcp needs the MCP SDK. Install the cloud extra, e.g.:\n"
    "  uv tool install 'postcommit[cloud]'\n"
    "  # or: pip install 'postcommit[cloud]'"
)

# The unambiguous next step for an auth failure. A stdio MCP server gets no
# client-driven OAuth prompt, so this hands the calling model an explicit command
# to run (or offer to the user) instead of a bare "not authenticated".
AUTH_ACTION = "run: postcommit-cloud-mcp login"


def _run(fn):
    """Call a CloudClient method, returning JSON text for the MCP tool result.

    Errors are surfaced as JSON rather than raised so the calling model sees a
    structured, actionable message instead of a transport-level failure.
    """
    from .cloud_auth import AuthError
    from .cloud_client import CloudApiError, CloudClient

    try:
        result = fn(CloudClient())
    except AuthError as exc:
        return json.dumps({
            "error": "auth", "action": AUTH_ACTION, "message": str(exc)})
    except CloudApiError as exc:
        return json.dumps({"error": "api", "status": exc.status, "message": exc.message})
    return json.dumps({"ok": True, "result": result}, indent=2)


def build_server():
    """Construct the FastMCP server. Raises ImportError if the extra is absent."""
    from mcp.server.fastmcp import FastMCP  # type: ignore

    server = FastMCP("postcommit-cloud")

    @server.tool()
    def create_post(content: str, scheduled_at: Optional[str] = None) -> str:
        """Create a draft or scheduled LinkedIn post.

        content:      post body (backend caps at 3000 chars)
        scheduled_at: ISO-8601 time to schedule, or omit for an unscheduled draft
        """
        return _run(lambda c: c.create_post(content, scheduled_at))

    @server.tool()
    def list_posts() -> str:
        """List all posts (drafts, scheduled, published, failed)."""
        return _run(lambda c: c.list_posts())

    @server.tool()
    def update_post(post_id: str, content: Optional[str] = None,
                    scheduled_at: Optional[str] = None) -> str:
        """Edit a post's content and/or scheduled time (pass at least one)."""
        return _run(lambda c: c.update_post(post_id, content, scheduled_at))

    @server.tool()
    def delete_post(post_id: str) -> str:
        """Delete a post by id."""
        return _run(lambda c: c.delete_post(post_id))

    @server.tool()
    def linkedin_status() -> str:
        """Report whether a LinkedIn account is connected, and its details."""
        return _run(lambda c: c.linkedin_status())

    @server.tool()
    def linkedin_disconnect() -> str:
        """Disconnect the linked LinkedIn account."""
        return _run(lambda c: c.linkedin_disconnect())

    return server


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # `login` / `logout` are handled *before* build_server() so they work even
    # when the `[cloud]`/`mcp` extra isn't installed — cloud_login is stdlib-only.
    if argv[:1] == ["login"]:
        from . import cloud_login
        try:
            cloud_login.login()
        except cloud_login.LoginError as exc:
            print("Login failed: %s" % exc, file=sys.stderr)
            return 1
        return 0
    if argv[:1] == ["logout"]:
        from . import cloud_login
        cloud_login.logout()
        return 0

    try:
        server = build_server()
    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    server.run()  # stdio transport by default
    return 0


if __name__ == "__main__":
    sys.exit(main())
