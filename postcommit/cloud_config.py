"""postcommit.cloud_config — resolve cloud-client configuration from the env.

Pure stdlib. This is the *core* (dependency-free) half of the cloud client: it
holds no MCP or network code, just reads and validates environment configuration
so both the REST client and the credential provider can share one source of truth.

Env vars:

  POSTCOMMIT_CLOUD_API_URL   base URL of the postcommit-cloud REST API. Optional;
                             defaults to the production gateway. Point this at a
                             local backend (e.g. http://localhost:8080) for dev.
  POSTCOMMIT_FIREBASE_API_KEY  Firebase Web API key, used only to refresh an
                             id_token against Google's securetoken endpoint.
  POSTCOMMIT_CLOUD_TOKEN     a pasted Firebase id_token (v0 auth). When set it is
                             used verbatim and no refresh is attempted.
  POSTCOMMIT_DASHBOARD_URL   base URL of the postcommit-cloud dashboard, whose
                             /cli-auth page completes the loopback login. Optional;
                             defaults to the production dashboard. Point this at a
                             local dashboard (e.g. http://localhost:3000) for dev.

The core stays stdlib-only; only serve_cloud.py imports the MCP SDK.
"""

import os

# Production API Gateway base URL. Override with POSTCOMMIT_CLOUD_API_URL for
# local development (the ticket ships prod-default, local-for-testing).
# TODO(cloud): confirm the final prod gateway / custom domain before release.
DEFAULT_API_URL = "https://api.postcommit.app"

# Production dashboard base URL, whose /cli-auth page hands tokens back to the
# CLI loopback server during `postcommit-cloud-mcp login`. Override with
# POSTCOMMIT_DASHBOARD_URL for local development.
# TODO(cloud): confirm the final dashboard domain before release.
DEFAULT_DASHBOARD_URL = "https://app.postcommit.app"


class ConfigError(Exception):
    """A required cloud config value is missing or malformed."""


def api_url():
    """Base URL for the cloud REST API, without a trailing slash.

    Falls back to the production gateway when POSTCOMMIT_CLOUD_API_URL is unset.
    """
    url = os.environ.get("POSTCOMMIT_CLOUD_API_URL", "").strip() or DEFAULT_API_URL
    return url.rstrip("/")


def cloud_token():
    """A pasted id_token (POSTCOMMIT_CLOUD_TOKEN), or None."""
    return os.environ.get("POSTCOMMIT_CLOUD_TOKEN", "").strip() or None


def firebase_api_key():
    """The Firebase Web API key used for token refresh, or None."""
    return os.environ.get("POSTCOMMIT_FIREBASE_API_KEY", "").strip() or None


def dashboard_url():
    """Base URL for the cloud dashboard, without a trailing slash.

    Falls back to the production dashboard when POSTCOMMIT_DASHBOARD_URL is unset.
    """
    url = os.environ.get("POSTCOMMIT_DASHBOARD_URL", "").strip() or DEFAULT_DASHBOARD_URL
    return url.rstrip("/")
