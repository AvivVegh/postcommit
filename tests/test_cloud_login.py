"""Tests for postcommit.cloud_login — the CLI loopback login flow.

No real browser and no outbound network: `webbrowser.open` is replaced with a
fake that drives a real localhost `POST /callback` against the loopback server
`login()` binds. Every test uses a throwaway credentials path.
"""

import io
import json
import os
import stat
import tempfile
import threading
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


if __name__ == "__main__":
    unittest.main()
