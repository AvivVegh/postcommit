"""Tests for postcommit.cloud_client — the thin REST client.

No network: `urlopen` is monkeypatched and each test asserts the request the
client *built* (method, path, headers, JSON body) and how it parses the
response (success, 204-no-body, non-2xx -> CloudApiError with backend message).
A stub CredentialProvider supplies a fixed Bearer token.
"""

import io
import json
import unittest
import urllib.error

from _support import state  # noqa: F401  (ensures repo root on sys.path)

from postcommit import cloud_client


class _StubProvider:
    def get_id_token(self):
        return "test-token"


class _FakeResponse:
    def __init__(self, status=200, payload=None, raw=None):
        self._status = status
        if raw is not None:
            self._body = raw
        elif payload is None:
            self._body = b""
        else:
            self._body = json.dumps(payload).encode("utf-8")

    def getcode(self):
        return self._status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ClientBase(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.response = _FakeResponse(200, {"ok": True})
        self.client = cloud_client.CloudClient(
            base_url="https://api.test", provider=_StubProvider())
        saved = cloud_client.urllib.request.urlopen
        cloud_client.urllib.request.urlopen = self._fake_urlopen
        self.addCleanup(setattr, cloud_client.urllib.request, "urlopen", saved)

    def _fake_urlopen(self, req, timeout=None):
        self.calls.append(req)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def last(self):
        return self.calls[-1]

    def body_json(self):
        return json.loads(self.last().data.decode("utf-8"))


class RequestShape(ClientBase):
    def test_create_post_builds_post_with_bearer_and_json_body(self):
        self.response = _FakeResponse(201, {"id": "p1", "status": "draft"})
        out = self.client.create_post("hello", scheduled_at="2026-01-01T00:00:00Z")
        self.assertEqual(out, {"id": "p1", "status": "draft"})
        req = self.last()
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://api.test/posts")
        self.assertEqual(req.headers["Authorization"], "Bearer test-token")
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(self.body_json(),
                         {"content": "hello", "scheduled_at": "2026-01-01T00:00:00Z"})

    def test_create_post_omits_scheduled_at_when_none(self):
        self.client.create_post("just a draft")
        self.assertEqual(self.body_json(), {"content": "just a draft"})

    def test_list_posts_is_a_get_with_no_body(self):
        self.response = _FakeResponse(200, [{"id": "p1"}])
        out = self.client.list_posts()
        self.assertEqual(out, [{"id": "p1"}])
        self.assertEqual(self.last().get_method(), "GET")
        self.assertIsNone(self.last().data)

    def test_update_post_patches_only_provided_fields(self):
        self.client.update_post("p9", content="edited")
        req = self.last()
        self.assertEqual(req.get_method(), "PATCH")
        self.assertEqual(req.full_url, "https://api.test/posts/p9")
        self.assertEqual(self.body_json(), {"content": "edited"})

    def test_delete_post_handles_204_no_body(self):
        self.response = _FakeResponse(204, raw=b"")
        out = self.client.delete_post("p9")
        self.assertIsNone(out)
        self.assertEqual(self.last().get_method(), "DELETE")
        self.assertEqual(self.last().full_url, "https://api.test/posts/p9")

    def test_linkedin_status_get(self):
        self.response = _FakeResponse(200, {"connected": False})
        self.assertEqual(self.client.linkedin_status(), {"connected": False})
        self.assertEqual(self.last().full_url, "https://api.test/linkedin/status")

    def test_linkedin_disconnect_delete(self):
        self.response = _FakeResponse(200, {"ok": True})
        self.assertEqual(self.client.linkedin_disconnect(), {"ok": True})
        req = self.last()
        self.assertEqual(req.get_method(), "DELETE")
        self.assertEqual(req.full_url, "https://api.test/linkedin/connection")


class ErrorMapping(ClientBase):
    def test_non_2xx_maps_to_cloud_api_error_with_backend_message(self):
        self.response = urllib.error.HTTPError(
            "https://api.test/posts", 400, "Bad Request", {},
            io.BytesIO(b'{"message":"content too long"}'))
        with self.assertRaises(cloud_client.CloudApiError) as cm:
            self.client.create_post("x" * 5000)
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.message, "content too long")

    def test_401_surfaces_status(self):
        self.response = urllib.error.HTTPError(
            "https://api.test/posts", 401, "Unauthorized", {},
            io.BytesIO(b'{"message":"expired token"}'))
        with self.assertRaises(cloud_client.CloudApiError) as cm:
            self.client.list_posts()
        self.assertEqual(cm.exception.status, 401)

    def test_unreachable_host_maps_to_status_zero(self):
        self.response = urllib.error.URLError("connection refused")
        with self.assertRaises(cloud_client.CloudApiError) as cm:
            self.client.list_posts()
        self.assertEqual(cm.exception.status, 0)


if __name__ == "__main__":
    unittest.main()
