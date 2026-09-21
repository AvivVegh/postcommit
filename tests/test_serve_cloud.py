"""Tests for postcommit.serve_cloud — the cloud MCP server wrapper.

Two things worth testing without the network or the MCP SDK:

  1. main() graceful-degrades when the `[cloud]` extra (mcp) is absent — mirrors
     test_cli.py::Serve for the local server.
  2. build_server() registers all six thin tools (skipped when mcp isn't
     installed, since the server class can't be constructed).

The `_run` helper's error-to-JSON mapping is covered directly — it needs no MCP.
`_server_class`'s version resolution is covered with stub modules, so both SDK
majors are exercised on a machine that only has one of them installed.
"""

import io
import json
import sys
import types
import unittest
import unittest.mock
from contextlib import redirect_stderr

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import serve_cloud


def _mcp_installed():
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


class GracefulDegrade(unittest.TestCase):
    def test_main_without_cloud_extra_hints_and_exits_nonzero(self):
        if _mcp_installed():
            self.skipTest("mcp installed; graceful-degradation path not exercised")
        err = io.StringIO()
        with redirect_stderr(err):
            rc = serve_cloud.main([])
        self.assertEqual(rc, 1)
        self.assertIn("postcommit[cloud]", err.getvalue())


class ServerClassResolution(unittest.TestCase):
    """`_server_class` spans both SDK majors.

    mcp 2.x renamed `FastMCP` to `MCPServer` and removed the v1 import path, so
    a single hard-coded import breaks on one major or the other. Stub modules
    stand in for the SDK here: the installed version only ever exercises one of
    these branches, and CI installs one version per job.
    """

    def _install(self, root_attr=None, mcpserver_attr=None, fastmcp_attr=None):
        """Fake `mcp.server` (+ submodules) with only the given names present."""
        mods = {"mcp": types.ModuleType("mcp"),
                "mcp.server": types.ModuleType("mcp.server")}
        if root_attr is not None:
            mods["mcp.server"].MCPServer = root_attr
        if mcpserver_attr is not None:
            sub = types.ModuleType("mcp.server.mcpserver")
            sub.MCPServer = mcpserver_attr
            mods["mcp.server.mcpserver"] = sub
        if fastmcp_attr is not None:
            sub = types.ModuleType("mcp.server.fastmcp")
            sub.FastMCP = fastmcp_attr
            mods["mcp.server.fastmcp"] = sub
        # patch.dict snapshots the whole of sys.modules and restores it on stop,
        # so deleting entries inside the patch is safe.
        patcher = unittest.mock.patch.dict(sys.modules, mods, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A real SDK already imported by an earlier test leaves its submodules
        # in sys.modules, and `from mcp.server.x import Y` resolves straight
        # off that — which would satisfy a branch this case means to close.
        for name in ("mcp.server.mcpserver", "mcp.server.fastmcp"):
            if name not in mods:
                sys.modules.pop(name, None)

    def test_prefers_the_2x_class(self):
        sentinel = object()
        self._install(root_attr=sentinel, fastmcp_attr=object())
        self.assertIs(sentinel, serve_cloud._server_class())

    def test_falls_back_to_the_2x_submodule_path(self):
        sentinel = object()
        self._install(mcpserver_attr=sentinel, fastmcp_attr=object())
        self.assertIs(sentinel, serve_cloud._server_class())

    def test_falls_back_to_the_1x_class(self):
        sentinel = object()
        self._install(fastmcp_attr=sentinel)
        self.assertIs(sentinel, serve_cloud._server_class())

    def test_raises_import_error_when_the_extra_is_absent(self):
        self._install()  # `mcp.server` present but empty — no server class
        with self.assertRaises(ImportError):
            serve_cloud._server_class()


class ToolRegistration(unittest.TestCase):
    def setUp(self):
        if not _mcp_installed():
            self.skipTest("mcp not installed; the server class can't be constructed")

    def test_build_server_registers_all_six_tools(self):
        import asyncio

        server = serve_cloud.build_server()
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {
            "create_post", "list_posts", "update_post",
            "delete_post", "linkedin_status", "linkedin_disconnect",
        })


class LoginDispatch(unittest.TestCase):
    """main() routes login/logout to cloud_login before touching the MCP SDK, so
    they work even without the `[cloud]` extra installed."""

    def setUp(self):
        from postcommit import cloud_login
        self.cloud_login = cloud_login
        self._saved = (cloud_login.login, cloud_login.login_paste, cloud_login.logout)
        self.addCleanup(self._restore)

    def _restore(self):
        (self.cloud_login.login, self.cloud_login.login_paste,
         self.cloud_login.logout) = self._saved

    def test_login_argv_defaults_to_paste(self):
        calls = []
        self.cloud_login.login_paste = lambda blob=None: calls.append(("paste", blob))
        rc = serve_cloud.main(["login"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("paste", None)])

    def test_login_forwards_inline_token_to_paste(self):
        calls = []
        self.cloud_login.login_paste = lambda blob=None: calls.append(("paste", blob))
        rc = serve_cloud.main(["login", "the-token"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("paste", "the-token")])

    def test_login_browser_flag_calls_loopback(self):
        calls = []
        self.cloud_login.login = lambda: calls.append("browser")
        rc = serve_cloud.main(["login", "--browser"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["browser"])

    def test_login_error_returns_nonzero(self):
        def boom(blob=None):
            raise self.cloud_login.LoginError("bad token")
        self.cloud_login.login_paste = boom
        err = io.StringIO()
        with redirect_stderr(err):
            rc = serve_cloud.main(["login"])
        self.assertEqual(rc, 1)
        self.assertIn("bad token", err.getvalue())

    def test_logout_argv_calls_cloud_login_logout(self):
        calls = []
        self.cloud_login.logout = lambda: calls.append("logout")
        rc = serve_cloud.main(["logout"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["logout"])


class RunHelper(unittest.TestCase):
    """_run maps client outcomes to structured JSON without needing MCP."""

    def test_success_wraps_result(self):
        out = serve_cloud._run(lambda c: {"id": "p1"})
        self.assertEqual(json.loads(out), {"ok": True, "result": {"id": "p1"}})

    def test_auth_error_becomes_structured_error(self):
        from postcommit.cloud_auth import AuthError

        def raiser(_c):
            raise AuthError("not authenticated")

        out = serve_cloud._run(raiser)
        self.assertEqual(json.loads(out), {
            "error": "auth",
            "action": "run: postcommit-cloud-mcp login",
            "message": "not authenticated",
        })

    def test_api_error_carries_status_and_message(self):
        from postcommit.cloud_client import CloudApiError

        def raiser(_c):
            raise CloudApiError(400, "content too long")

        out = serve_cloud._run(raiser)
        self.assertEqual(json.loads(out),
                         {"error": "api", "status": 400, "message": "content too long"})


if __name__ == "__main__":
    unittest.main()
