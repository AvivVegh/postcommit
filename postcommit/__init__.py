"""postcommit — turn real dev work into candidate LinkedIn posts, locally.

This is the code-first core. What used to live in prompt files and stdlib hooks
now lives here as importable modules with a stable CLI:

  postcommit.extract       deterministic git + session-transcript -> work bundle
  postcommit.scoring       cheap post-worthiness signals + scoring
  postcommit.state         per-repo/global state (watermark, recommendation, snooze)
  postcommit.hooks         SessionEnd / SessionStart hook logic

And the optional cloud client, which is the *only* part that touches the network:

  postcommit.cloud_config  cloud client config from the environment
  postcommit.cloud_auth    credential storage + id_token refresh
  postcommit.cloud_login   interactive login/logout/status (`postcommit cloud`)
  postcommit.cloud_client  thin REST client for postcommit-cloud
  postcommit.serve_cloud   optional MCP server (postcommit-cloud-mcp, [cloud] extra)

The Claude Code skill, command, agent, and hooks are thin adapters that shell
out to this package. The extraction and drafting path stays entirely local — no
network calls, ever; only the cloud modules above make outbound requests, and
only with already-approved draft text.
"""

__version__ = "0.9.0"
