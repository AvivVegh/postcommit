"""Tests for postcommit.cloud_auth — the CredentialProvider seam.

No network: the securetoken refresh call is exercised by monkeypatching
`urlopen`. Every test runs against a throwaway credentials file and a scrubbed
environment so a developer's real POSTCOMMIT_* vars never leak in.
"""

import io
import json
import os
import stat
import tempfile
import unittest

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import cloud_auth

_CLOUD_ENV_VARS = (
    "POSTCOMMIT_CLOUD_TOKEN",
    "POSTCOMMIT_FIREBASE_API_KEY",
    "POSTCOMMIT_CLOUD_API_URL",
)


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CloudAuthBase(unittest.TestCase):
    def setUp(self):
        # Scrub cloud env so tests are hermetic; restore on teardown.
        self._saved_env = {k: os.environ.pop(k, None) for k in _CLOUD_ENV_VARS}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.creds = os.path.join(self.tmp.name, "credentials.json")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _write_creds(self, data):
        with open(self.creds, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


class EnvTokenPath(CloudAuthBase):
    def test_env_token_used_verbatim_without_refresh(self):
        os.environ["POSTCOMMIT_CLOUD_TOKEN"] = "pasted-token"
        provider = cloud_auth.CredentialProvider(self.creds)
        self.assertEqual(provider.get_id_token(), "pasted-token")


class CachedTokenPath(CloudAuthBase):
    def test_valid_cached_token_is_returned(self):
        self._write_creds({"id_token": "cached", "expires_at": 9_999_999_999})
        provider = cloud_auth.CredentialProvider(self.creds)
        self.assertEqual(provider.get_id_token(), "cached")

    def test_missing_credentials_raises_clear_error(self):
        provider = cloud_auth.CredentialProvider(self.creds)
        with self.assertRaises(cloud_auth.AuthError) as cm:
            provider.get_id_token()
        self.assertIn("POSTCOMMIT_CLOUD_TOKEN", str(cm.exception))


class RefreshPath(CloudAuthBase):
    def test_expired_token_triggers_refresh_and_caches(self):
        os.environ["POSTCOMMIT_FIREBASE_API_KEY"] = "fake-key"
        self._write_creds({
            "refresh_token": "r-old",
            "id_token": "stale",
            "expires_at": 0,  # already expired -> must refresh
        })
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = req.data
            return _FakeResponse({
                "id_token": "fresh",
                "refresh_token": "r-new",
                "expires_in": "3600",
            })

        self._patch_urlopen(fake_urlopen)
        provider = cloud_auth.CredentialProvider(self.creds)
        self.assertEqual(provider.get_id_token(), "fresh")

        # request shape
        self.assertIn("securetoken.googleapis.com", captured["url"])
        self.assertIn("key=fake-key", captured["url"])
        self.assertIn(b"grant_type=refresh_token", captured["body"])
        self.assertIn(b"refresh_token=r-old", captured["body"])

        # new token + rotated refresh token cached to disk
        with open(self.creds, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["id_token"], "fresh")
        self.assertEqual(saved["refresh_token"], "r-new")
        self.assertGreater(saved["expires_at"], 0)

        # file perms tightened to 600
        mode = stat.S_IMODE(os.stat(self.creds).st_mode)
        self.assertEqual(mode, 0o600)

    def test_refresh_without_api_key_raises(self):
        # refresh_token present but no api key -> cannot refresh -> clear error
        self._write_creds({"refresh_token": "r-old", "expires_at": 0})
        provider = cloud_auth.CredentialProvider(self.creds)
        with self.assertRaises(cloud_auth.AuthError):
            provider.get_id_token()

    def test_refresh_http_error_surfaces_as_auth_error(self):
        import urllib.error

        os.environ["POSTCOMMIT_FIREBASE_API_KEY"] = "fake-key"
        self._write_creds({"refresh_token": "r-old", "expires_at": 0})

        def boom(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 400, "Bad Request", {},
                io.BytesIO(b'{"error":"TOKEN_EXPIRED"}'))

        self._patch_urlopen(boom)
        provider = cloud_auth.CredentialProvider(self.creds)
        with self.assertRaises(cloud_auth.AuthError) as cm:
            provider.get_id_token()
        self.assertIn("400", str(cm.exception))

    def _patch_urlopen(self, fn):
        saved = cloud_auth.urllib.request.urlopen
        cloud_auth.urllib.request.urlopen = fn
        self.addCleanup(setattr, cloud_auth.urllib.request, "urlopen", saved)


if __name__ == "__main__":
    unittest.main()
