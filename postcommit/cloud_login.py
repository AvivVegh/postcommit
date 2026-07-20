"""postcommit.cloud_login — the CLI loopback login flow (core, stdlib-only).

`login()` implements the CLI half of the dashboard CLI-auth handoff:

  1. generate a random `state` and bind a single-shot HTTP server to
     127.0.0.1:0 (an OS-assigned ephemeral port);
  2. open `<dashboard>/cli-auth?port=<port>&state=<state>` in the browser;
  3. await one `POST /callback` from that page (answering the CORS preflight),
     verify the echoed `state`, and write the returned tokens to
     ~/.postcommit/credentials.json (chmod 600) — exactly the shape
     `cloud_auth.CredentialProvider` reads back.

`logout()` deletes that credentials file.

Everything here is stdlib-only (http.server / secrets / webbrowser): the login
flow needs no third-party deps, so `postcommit-cloud-mcp login` works even when
the `[cloud]`/`mcp` extra isn't installed. Tokens only ever arrive in the POST
*body*, never a URL, and the server binds 127.0.0.1 only — never 0.0.0.0.
"""

import base64
import binascii
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import cloud_auth, cloud_config

# Match the ticket: the browser handoff must complete within five minutes.
DEFAULT_TIMEOUT_SECONDS = 300

_CALLBACK_PATH = "/callback"


class LoginError(Exception):
    """The loopback login could not be completed."""


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the single OPTIONS preflight + POST callback from /cli-auth.

    State lives on the server instance (`expected_state`, `creds_path`,
    `allow_origin`); results are recorded back onto it (`result`, `error`,
    `done`) so the serve loop can stop after the terminal request.
    """

    # Silence the default stderr request logging — this is a CLI, not a daemon.
    def log_message(self, *args):  # noqa: D401
        pass

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):  # noqa: N802  (http.server naming)
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802  (http.server naming)
        if urllib.parse.urlsplit(self.path).path != _CALLBACK_PATH:
            self._respond(404, {"error": "not found"})
            return

        payload = self._read_json_body()
        if payload is None:
            self._respond(400, {"error": "invalid JSON body"})
            self.server.error = "callback sent an invalid JSON body"
            self.server.done = True
            return

        if payload.get("state") != self.server.expected_state:
            # Reject a mismatched/forged callback without writing anything.
            self._respond(403, {"error": "state mismatch"})
            self.server.error = "state parameter did not match"
            self.server.done = True
            return

        id_token = payload.get("idToken")
        refresh_token = payload.get("refreshToken")
        if not id_token or not refresh_token:
            self._respond(400, {"error": "missing idToken/refreshToken"})
            self.server.error = "callback omitted idToken or refreshToken"
            self.server.done = True
            return

        try:
            expires_in = float(payload.get("expiresIn", 3600))
        except (TypeError, ValueError):
            expires_in = 3600.0

        creds = {
            "refresh_token": refresh_token,
            "id_token": id_token,
            "expires_at": time.time() + expires_in,
            "api_key": payload.get("apiKey"),
        }
        _write_credentials(self.server.creds_path, creds)

        self._respond(200, {"ok": True})
        self.server.result = creds
        self.server.done = True

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _respond(self, status, body):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _write_credentials(path, data):
    """Write credentials.json and tighten it to 0o600 (holds refresh/id tokens)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _build_server(creds_path, expected_state, allow_origin):
    # 127.0.0.1 only (never 0.0.0.0); port 0 → OS-assigned ephemeral port.
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.expected_state = expected_state
    server.creds_path = creds_path
    server.allow_origin = allow_origin
    server.result = None
    server.error = None
    server.done = False
    return server


def _origin_of(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme and parts.netloc:
        return "%s://%s" % (parts.scheme, parts.netloc)
    return url


def _identity_line(id_token):
    """Best-effort 'Signed in as <email>' from the JWT payload (unverified)."""
    try:
        payload_b64 = id_token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return "Signed in to postcommit-cloud."
    who = claims.get("email") or claims.get("name")
    return "Signed in as %s." % who if who else "Signed in to postcommit-cloud."


def login(dashboard_url=None, timeout=DEFAULT_TIMEOUT_SECONDS,
          open_browser=None, creds_path=None):
    """Run the loopback login; write credentials.json and return its contents.

    dashboard_url / creds_path default to cloud_config.dashboard_url() and
    cloud_auth.credentials_path(). open_browser defaults to webbrowser.open and
    is injectable for tests. Raises LoginError on timeout or a rejected callback.
    """
    dashboard = (dashboard_url or cloud_config.dashboard_url()).rstrip("/")
    creds_path = creds_path or cloud_auth.credentials_path()
    open_browser = open_browser or webbrowser.open

    state = secrets.token_urlsafe(32)
    server = _build_server(creds_path, state, _origin_of(dashboard))
    port = server.server_address[1]
    try:
        auth_url = "%s/cli-auth?%s" % (
            dashboard, urllib.parse.urlencode({"port": port, "state": state}))
        print("Opening %s in your browser to authorize…" % auth_url)
        open_browser(auth_url)

        deadline = time.monotonic() + timeout
        while not server.done:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            server.timeout = remaining
            server.handle_request()
    finally:
        server.server_close()

    if server.error:
        raise LoginError(server.error)
    if not server.done or server.result is None:
        raise LoginError(
            "timed out after %ds waiting for the browser authorization. "
            "Re-run `postcommit-cloud-mcp login` and complete the Authorize step."
            % int(timeout))

    print(_identity_line(server.result["id_token"]))
    print("Credentials written to %s" % creds_path)
    return server.result


def logout(creds_path=None):
    """Delete ~/.postcommit/credentials.json (a no-op if it is already absent)."""
    creds_path = creds_path or cloud_auth.credentials_path()
    try:
        os.remove(creds_path)
    except FileNotFoundError:
        print("Already signed out (no credentials found).")
        return
    print("Signed out; removed %s" % creds_path)
