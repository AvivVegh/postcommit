"""postcommit.cloud_auth — the CredentialProvider seam (core, stdlib-only).

`CredentialProvider.get_id_token()` returns a Firebase id_token for the cloud
REST client to send as `Authorization: Bearer <token>`. Resolution order:

  1. POSTCOMMIT_CLOUD_TOKEN set  → use it verbatim (v0 paste path, no refresh).
  2. ~/.postcommit/credentials.json holds a still-valid `id_token`  → use it.
  3. …holds a `refresh_token` (+ POSTCOMMIT_FIREBASE_API_KEY)  → refresh against
     Google securetoken, cache the new id_token/expires_at back (chmod 600), use it.
  4. Otherwise  → raise AuthError with a clear next step.

This is the exact interface Ticket B (the loopback login flow) plugs into: B's
job is to *populate* ~/.postcommit/credentials.json with a real refresh_token.
Nothing here is throwaway scaffolding.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import cloud_config

SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# Refresh a little early so a token that is about to expire mid-request doesn't
# come back 401 from the gateway.
_EXPIRY_SKEW_SECONDS = 60

_LOGIN_HINT = (
    "not authenticated with postcommit-cloud. Run `postcommit-cloud-mcp login` "
    "to sign in via your browser, or set POSTCOMMIT_CLOUD_TOKEN to a Firebase "
    "id_token. Either populates ~/.postcommit/credentials.json."
)


class AuthError(Exception):
    """No usable credential could be obtained."""


def credentials_path():
    return os.path.join(os.path.expanduser("~"), ".postcommit", "credentials.json")


class CredentialProvider:
    """Resolves a Firebase id_token, refreshing and caching as needed."""

    def __init__(self, path=None):
        self._path = path or credentials_path()

    def get_id_token(self):
        token = cloud_config.cloud_token()
        if token:
            return token

        creds = self._read_credentials()
        cached = creds.get("id_token")
        if cached and not self._expired(creds.get("expires_at")):
            return cached

        refresh_token = creds.get("refresh_token")
        # The env var wins when set; otherwise fall back to the api_key the login
        # flow stored in credentials.json, so refresh works with zero env config.
        api_key = cloud_config.firebase_api_key() or creds.get("api_key")
        if refresh_token and api_key:
            return self._refresh(refresh_token, api_key, creds)

        raise AuthError(_LOGIN_HINT)

    # --- internals ----------------------------------------------------------

    def _read_credentials(self):
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _expired(expires_at):
        # No expiry recorded → treat as expired so we refresh rather than send a
        # possibly-stale token.
        if not expires_at:
            return True
        try:
            return time.time() >= float(expires_at) - _EXPIRY_SKEW_SECONDS
        except (TypeError, ValueError):
            return True

    def _refresh(self, refresh_token, api_key, creds):
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode("utf-8")
        url = "%s?key=%s" % (SECURETOKEN_URL, urllib.parse.quote(api_key, safe=""))
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            # Fixed https securetoken endpoint (not user-controlled scheme).
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise AuthError(
                "token refresh failed (HTTP %s): %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, ValueError, OSError) as exc:
            raise AuthError("token refresh failed: %s" % exc) from exc

        id_token = payload.get("id_token")
        if not id_token:
            raise AuthError("token refresh returned no id_token")

        updated = dict(creds)
        updated["id_token"] = id_token
        # securetoken returns a *new* refresh_token; keep it if present.
        if payload.get("refresh_token"):
            updated["refresh_token"] = payload["refresh_token"]
        expires_in = payload.get("expires_in")
        if expires_in is not None:
            try:
                updated["expires_at"] = time.time() + float(expires_in)
            except (TypeError, ValueError):
                pass
        self._write_credentials(updated)
        return id_token

    def _write_credentials(self, data):
        directory = os.path.dirname(self._path)
        os.makedirs(directory, exist_ok=True)
        # Write then tighten perms to 600 — this file holds refresh/id tokens.
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass
