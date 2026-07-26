"""Tests for postcommit.cloud_login — the CLI loopback login flow.

No real browser and no outbound network: `webbrowser.open` is replaced with a
fake that drives a real localhost `POST /callback` against the loopback server
`login()` binds. Every test uses a throwaway credentials path.
"""

import base64
import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import cloud_login


def _post(url, body):
    """POST a JSON body, returning (status, response_dict)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _parse_query(auth_url):
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(auth_url).query)
    return q["port"][0], q["state"][0]


class LoginBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.creds = os.path.join(self.tmp.name, ".postcommit", "credentials.json")

    def _run_login(self, callback, timeout=5):
        """Run login() with a fake browser that runs `callback(port, state)` in a
        background thread, and return (result_or_exc, thread_capture)."""
        capture = {}

        def fake_open(auth_url):
            port, st = _parse_query(auth_url)
            capture["state"] = st

            def worker():
                capture["response"] = callback(int(port), st)

            t = threading.Thread(target=worker)
            t.start()
            capture["thread"] = t
            return True

        outcome = {}
        with redirect_stdout(io.StringIO()):
            try:
                outcome["result"] = cloud_login.login(
                    dashboard_url="http://localhost:3000",
                    timeout=timeout, open_browser=fake_open,
                    creds_path=self.creds)
            except cloud_login.LoginError as exc:
                outcome["error"] = exc
        if capture.get("thread"):
            capture["thread"].join(timeout=5)
        return outcome, capture


class HappyPath(LoginBase):
    def test_writes_credentials_with_600_perms(self):
        def cb(port, st):
            return _post("http://127.0.0.1:%d/callback" % port, {
                "state": st,
                "idToken": "id-abc",
                "refreshToken": "refresh-xyz",
                "apiKey": "key-123",
                "expiresIn": 3600,
            })

        outcome, capture = self._run_login(cb)

        self.assertNotIn("error", outcome)
        status, body = capture["response"]
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        with open(self.creds, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["id_token"], "id-abc")
        self.assertEqual(saved["refresh_token"], "refresh-xyz")
        self.assertEqual(saved["api_key"], "key-123")
        self.assertGreater(saved["expires_at"], 0)

        mode = stat.S_IMODE(os.stat(self.creds).st_mode)
        self.assertEqual(mode, 0o600)


class SnakeCasePayload(LoginBase):
    def test_loopback_accepts_snake_case_fields(self):
        def cb(port, st):
            return _post("http://127.0.0.1:%d/callback" % port, {
                "state": st,
                "id_token": "id-abc",
                "refresh_token": "refresh-xyz",
                "api_key": "key-123",
                "expires_in": 3600,
            })

        outcome, capture = self._run_login(cb)

        self.assertNotIn("error", outcome)
        status, _body = capture["response"]
        self.assertEqual(status, 200)
        with open(self.creds, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["id_token"], "id-abc")
        self.assertEqual(saved["refresh_token"], "refresh-xyz")
        self.assertEqual(saved["api_key"], "key-123")


class StateMismatch(LoginBase):
    def test_mismatch_is_rejected_and_writes_nothing(self):
        def cb(port, _st):
            return _post("http://127.0.0.1:%d/callback" % port, {
                "state": "not-the-right-state",
                "idToken": "id-abc",
                "refreshToken": "refresh-xyz",
            })

        outcome, capture = self._run_login(cb)

        self.assertIn("error", outcome)
        status, _body = capture["response"]
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(self.creds))


class Preflight(LoginBase):
    def test_options_returns_cors_headers_then_post_completes(self):
        seen = {}

        def cb(port, st):
            base = "http://127.0.0.1:%d/callback" % port
            req = urllib.request.Request(base, method="OPTIONS")
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
                seen["status"] = resp.status
                seen["origin"] = resp.headers.get("Access-Control-Allow-Origin")
                seen["methods"] = resp.headers.get("Access-Control-Allow-Methods")
                seen["headers"] = resp.headers.get("Access-Control-Allow-Headers")
            return _post(base, {
                "state": st, "idToken": "id", "refreshToken": "r", "apiKey": "k"})

        outcome, _capture = self._run_login(cb)

        self.assertNotIn("error", outcome)
        self.assertEqual(seen["status"], 204)
        self.assertEqual(seen["origin"], "http://localhost:3000")
        self.assertIn("POST", seen["methods"])
        self.assertIn("OPTIONS", seen["methods"])
        self.assertIn("Content-Type", seen["headers"])


class Timeout(LoginBase):
    def test_no_callback_raises_login_error(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(cloud_login.LoginError) as cm:
                cloud_login.login(
                    dashboard_url="http://localhost:3000",
                    timeout=0.3, open_browser=lambda _url: True,
                    creds_path=self.creds)
        self.assertIn("timed out", str(cm.exception))
        # The retry hint must name the main-CLI verb: `postcommit-cloud-mcp` is
        # a console script the plugin-bundled launcher cannot reach.
        self.assertIn("postcommit cloud login --browser", str(cm.exception))
        self.assertFalse(os.path.exists(self.creds))


class Logout(LoginBase):
    def test_removes_existing_file(self):
        os.makedirs(os.path.dirname(self.creds), exist_ok=True)
        with open(self.creds, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with redirect_stdout(io.StringIO()):
            cloud_login.logout(creds_path=self.creds)
        self.assertFalse(os.path.exists(self.creds))

    def test_absent_file_is_a_noop(self):
        with redirect_stdout(io.StringIO()) as out:
            cloud_login.logout(creds_path=self.creds)
        self.assertIn("Already signed out", out.getvalue())


def _bundle(payload, urlsafe=False):
    """base64(JSON) blob mirroring the dashboard's copy-token output."""
    raw = json.dumps(payload).encode("utf-8")
    encode = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    return encode(raw).decode("ascii")


class PasteLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.creds = os.path.join(self.tmp.name, ".postcommit", "credentials.json")

    def _load(self):
        with open(self.creds, encoding="utf-8") as fh:
            return json.load(fh)

    def test_snake_case_bundle_writes_refresh_creds_with_600_perms(self):
        blob = _bundle({
            "refresh_token": "refresh-xyz",
            "id_token": "id-abc",
            "api_key": "key-123",
            "expires_in": 3600,
        })
        with redirect_stdout(io.StringIO()):
            cloud_login.login_paste(blob=blob, creds_path=self.creds)

        saved = self._load()
        self.assertEqual(saved["refresh_token"], "refresh-xyz")
        self.assertEqual(saved["id_token"], "id-abc")
        self.assertEqual(saved["api_key"], "key-123")
        self.assertGreater(saved["expires_at"], time.time())
        self.assertEqual(stat.S_IMODE(os.stat(self.creds).st_mode), 0o600)

    def test_camelcase_and_urlsafe_bundle_is_accepted(self):
        blob = _bundle({
            "refreshToken": "r2",
            "idToken": "i2",
            "apiKey": "k2",
            "expiresIn": 1800,
        }, urlsafe=True)
        with redirect_stdout(io.StringIO()):
            cloud_login.login_paste(blob=blob, creds_path=self.creds)

        saved = self._load()
        self.assertEqual(saved["refresh_token"], "r2")
        self.assertEqual(saved["api_key"], "k2")

    def test_absolute_expires_at_is_preserved(self):
        blob = _bundle({
            "refresh_token": "r", "api_key": "k", "expires_at": 42.0})
        with redirect_stdout(io.StringIO()):
            cloud_login.login_paste(blob=blob, creds_path=self.creds)
        self.assertEqual(self._load()["expires_at"], 42.0)

    def test_interactive_read_uses_input_fn(self):
        blob = _bundle({"refresh_token": "r", "api_key": "k"})
        with redirect_stdout(io.StringIO()):
            cloud_login.login_paste(
                creds_path=self.creds, input_fn=lambda _prompt: blob)
        self.assertEqual(self._load()["refresh_token"], "r")

    def test_missing_refresh_token_raises_and_writes_nothing(self):
        blob = _bundle({"id_token": "id-only", "api_key": "k"})
        with self.assertRaises(cloud_login.LoginError) as cm:
            cloud_login.login_paste(blob=blob, creds_path=self.creds)
        self.assertIn("refresh_token", str(cm.exception))
        self.assertFalse(os.path.exists(self.creds))

    def test_not_base64_raises(self):
        with self.assertRaises(cloud_login.LoginError):
            cloud_login.login_paste(blob="!!!not base64!!!", creds_path=self.creds)
        self.assertFalse(os.path.exists(self.creds))

    def test_base64_but_not_json_raises(self):
        blob = base64.b64encode(b"plain text, not json").decode("ascii")
        with self.assertRaises(cloud_login.LoginError) as cm:
            cloud_login.login_paste(blob=blob, creds_path=self.creds)
        self.assertIn("JSON", str(cm.exception))

    def test_empty_token_raises(self):
        with self.assertRaises(cloud_login.LoginError):
            cloud_login.login_paste(blob="   ", creds_path=self.creds)


if __name__ == "__main__":
    unittest.main()


class StatusStates(unittest.TestCase):
    """cloud_login.status must answer "can I use the cloud", not "has the
    id_token expired" — and must never print the token itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.creds = os.path.join(self.tmp.name, "credentials.json")

    class _Provider:
        def __init__(self, token=None, error=None):
            self._token, self._error = token, error

        def get_id_token(self):
            if self._error:
                raise self._error
            return self._token

    class _Client:
        def __init__(self, exc=None):
            self._exc = exc

        def linkedin_status(self):
            if self._exc:
                raise self._exc
            return {"connected": True}

    def _run(self, provider, client):
        buf = io.StringIO()
        with redirect_stdout(buf):
            state_name, code = cloud_login.status(
                creds_path=self.creds, provider=provider, client=client)
        return state_name, code, buf.getvalue()

    def test_no_credentials_is_signed_out(self):
        p = self._Provider(error=cloud_login.cloud_auth.AuthError("nope"))
        name, code, out = self._run(p, self._Client())
        self.assertEqual((name, code), ("signed-out", 1))
        self.assertIn("status: signed-out", out)

    def test_expired_id_token_that_refreshes_is_active(self):
        """The whole point: an expired id_token is the normal steady state."""
        p = self._Provider(token=_jwt({"email": "a@b.c"}))
        name, code, out = self._run(p, self._Client())
        self.assertEqual((name, code), ("active", 0))
        self.assertIn("status: active", out)
        self.assertIn("a@b.c", out)

    def test_server_rejection_is_rejected_not_active(self):
        err = cloud_login.LoginError("denied")
        err.status = 401
        name, code, out = self._run(self._Provider(token=_jwt({})), self._Client(err))
        self.assertEqual((name, code), ("rejected", 1))
        self.assertIn("status: rejected", out)

    def test_network_failure_does_not_force_a_relogin(self):
        name, code, out = self._run(
            self._Provider(token=_jwt({})), self._Client(OSError("dns")))
        self.assertEqual((name, code), ("active-unverified", 0))
        self.assertIn("status: active-unverified", out)

    def test_never_prints_the_token(self):
        token = _jwt({"email": "a@b.c"})
        for client in (self._Client(), self._Client(OSError("x"))):
            _, _, out = self._run(self._Provider(token=token), client)
            self.assertNotIn(token, out)


def _jwt(claims):
    """A syntactically valid unsigned JWT carrying `claims`."""
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return "%s.%s.%s" % (seg({"alg": "none"}), seg(claims), "sig")
