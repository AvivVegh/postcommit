"""postcommit.cloud_client — thin REST client for the postcommit-cloud API.

Pure stdlib (`urllib.request`) so the core stays dependency-free — the MCP SDK
is only pulled in by serve_cloud.py. One method per cloud tool; every request
carries `Authorization: Bearer <id_token>` from the CredentialProvider. Non-2xx
responses are mapped to CloudApiError carrying the backend's `{message}`.

Verified backend contract (source of truth: postcommit-cloud/backend):

  create_post          POST   /posts                -> 201 PostResponse
  list_posts           GET    /posts                -> 200 PostResponse[]
  update_post          PATCH  /posts/{id}           -> 200 PostResponse
  delete_post          DELETE /posts/{id}           -> 204 (no body)
  linkedin_status      GET    /linkedin/status      -> 200 {connected, ...}
  linkedin_disconnect  DELETE /linkedin/connection  -> 200 {ok: true}

Content length and field validation are the backend's job — surface its error
rather than duplicating rules that can drift.
"""

import json
import urllib.error
import urllib.request

from . import cloud_config
from .cloud_auth import CredentialProvider


class CloudApiError(Exception):
    """A cloud REST call returned a non-2xx status.

    `status` is the HTTP code; `message` is the backend's error message when it
    sent one (falling back to the raw body / reason).
    """

    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__("cloud API error (HTTP %s): %s" % (status, message))


class CloudClient:
    def __init__(self, base_url=None, provider=None):
        self._base_url = (base_url or cloud_config.api_url()).rstrip("/")
        self._provider = provider or CredentialProvider()

    # --- tools --------------------------------------------------------------

    def create_post(self, content, scheduled_at=None):
        body = {"content": content}
        if scheduled_at is not None:
            body["scheduled_at"] = scheduled_at
        return self._request("POST", "/posts", body=body)

    def list_posts(self):
        return self._request("GET", "/posts")

    def update_post(self, post_id, content=None, scheduled_at=None):
        body = {}
        if content is not None:
            body["content"] = content
        if scheduled_at is not None:
            body["scheduled_at"] = scheduled_at
        return self._request("PATCH", "/posts/%s" % post_id, body=body)

    def delete_post(self, post_id):
        return self._request("DELETE", "/posts/%s" % post_id)

    def linkedin_status(self):
        return self._request("GET", "/linkedin/status")

    def linkedin_disconnect(self):
        return self._request("DELETE", "/linkedin/connection")

    # --- transport ----------------------------------------------------------

    def _request(self, method, path, body=None):
        url = self._base_url + path
        data = None
        headers = {
            "Authorization": "Bearer %s" % self._provider.get_id_token(),
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            # url = base_url (from config/env) + a fixed REST path; https scheme.
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                status = resp.getcode()
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise CloudApiError(exc.code, self._error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise CloudApiError(0, "could not reach %s: %s" % (url, exc.reason)) from exc

        # 204 No Content (delete) and any empty body -> no JSON to parse.
        if status == 204 or not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    @staticmethod
    def _error_message(exc):
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return exc.reason or "request failed"
        if isinstance(payload, dict):
            return payload.get("message") or payload.get("error") or str(payload)
        return str(payload)
