#!/usr/bin/env bash
#
# link-local.sh — set up postcommit for local Claude Code iteration without
# publishing the plugin. It:
#   1. installs the Python package as an editable `uv` tool so the `postcommit`
#      CLI (used by the thin hooks and skill) is on PATH and tracks this checkout,
#   2. symlinks this repo's command, skill, and subagent into ~/.claude/,
#   3. registers the thin SessionEnd / SessionStart hooks in ~/.claude/settings.json
#      (backing the file up first).
# Idempotent. Refuses to overwrite non-symlink files at the target. --unlink
# undoes all of it.
#
# Usage:
#   scripts/link-local.sh          # link
#   scripts/link-local.sh --unlink # remove the symlinks
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"

# source_relative_to_repo   target_relative_to_claude_dir
LINKS=(
  "commands/post.md                    commands/post.md"
  "commands/post-snooze.md             commands/post-snooze.md"
  "skills/postcommit-extract           skills/postcommit-extract"
  "agents/post-writer.md               agents/post-writer.md"
)

link_one() {
  local src="$REPO_ROOT/$1"
  local dst="$CLAUDE_DIR/$2"

  if [[ ! -e "$src" ]]; then
    echo "  ✗ source missing: $src" >&2
    return 1
  fi

  mkdir -p "$(dirname "$dst")"

  if [[ -L "$dst" ]]; then
    local current
    current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
      echo "  = already linked: $dst"
      return 0
    fi
    echo "  ↻ replacing existing symlink: $dst (was → $current)"
    rm "$dst"
  elif [[ -e "$dst" ]]; then
    echo "  ✗ refusing to overwrite non-symlink: $dst" >&2
    echo "    move it out of the way and re-run." >&2
    return 1
  fi

  ln -s "$src" "$dst"
  echo "  + linked: $dst → $src"
}

unlink_one() {
  local src="$REPO_ROOT/$1"
  local dst="$CLAUDE_DIR/$2"

  if [[ ! -L "$dst" ]]; then
    echo "  = not a symlink, skipping: $dst"
    return 0
  fi

  local current
  current="$(readlink "$dst")"
  if [[ "$current" != "$src" ]]; then
    echo "  ✗ symlink at $dst points elsewhere ($current), skipping" >&2
    return 0
  fi

  rm "$dst"
  echo "  - removed: $dst"
}

install_package() {
  # Install the CLI as an editable uv tool so it's on PATH and tracks this
  # checkout. The thin hooks and skill shell out to `postcommit`.
  if ! command -v uv >/dev/null 2>&1; then
    echo "  ✗ uv not found — install it (https://docs.astral.sh/uv/) then re-run," >&2
    echo "    or 'pip install -e $REPO_ROOT' yourself so 'postcommit' is on PATH." >&2
    return 1
  fi
  uv tool install --force --editable "$REPO_ROOT"
  echo "  + installed editable uv tool: postcommit ($REPO_ROOT)"
}

uninstall_package() {
  if command -v uv >/dev/null 2>&1; then
    if uv tool uninstall postcommit >/dev/null 2>&1; then
      echo "  - uninstalled uv tool: postcommit"
    fi
  fi
}

# Register/unregister the two hooks in settings.json. We do the JSON surgery in
# python3 (stdlib) so we never hand-edit the user's settings with sed. Our hook
# entries are tagged with the script basenames so unregister can find and drop
# exactly them, leaving any other hooks untouched.
hooks_settings() {
  local mode="$1" # register | unregister
  REPO_ROOT="$REPO_ROOT" SETTINGS="$SETTINGS" MODE="$mode" python3 - <<'PY'
import json, os, shutil, sys

repo = os.environ["REPO_ROOT"]
path = os.environ["SETTINGS"]
mode = os.environ["MODE"]

end_cmd = "python3 %s/hooks/session-end.py" % repo
start_cmd = "python3 %s/hooks/session-start.py" % repo
MARKERS = ("hooks/session-end.py", "hooks/session-start.py")

settings = {}
if os.path.exists(path):
    try:
        with open(path) as fh:
            settings = json.load(fh)
    except ValueError:
        print("  ✗ %s is not valid JSON; leaving hooks unregistered" % path)
        sys.exit(0)

if os.path.exists(path):
    shutil.copyfile(path, path + ".bak")

hooks = settings.setdefault("hooks", {})

def strip_ours(event):
    groups = hooks.get(event) or []
    kept = []
    for g in groups:
        cmds = " ".join(h.get("command", "") for h in (g.get("hooks") or []))
        if any(m in cmds for m in MARKERS):
            continue
        kept.append(g)
    if kept:
        hooks[event] = kept
    elif event in hooks:
        del hooks[event]

# always strip first so this is idempotent
strip_ours("SessionEnd")
strip_ours("SessionStart")

if mode == "register":
    hooks.setdefault("SessionEnd", []).append(
        {"hooks": [{"type": "command", "command": end_cmd}]})
    # no matcher: the script itself no-ops unless source is startup/clear
    hooks.setdefault("SessionStart", []).append(
        {"hooks": [{"type": "command", "command": start_cmd}]})

if not hooks:
    settings.pop("hooks", None)

os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as fh:
    json.dump(settings, fh, indent=2)
    fh.write("\n")

print("  %s hooks in %s" % ("registered" if mode == "register" else "removed", path))
PY
}

action="${1:-link}"
case "$action" in
  link|--link|"")
    echo "linking postcommit → $CLAUDE_DIR"
    # Don't let a missing `uv` (install_package -> return 1) abort the whole
    # script under `set -e` before the symlinks/hooks are wired. Testing it in
    # the `if` condition keeps `set -e` from tripping.
    if ! install_package; then
      echo "  ⚠ continuing without the editable CLI — put 'postcommit' on PATH" \
           "yourself ('pip install -e $REPO_ROOT') so the hooks can find it." >&2
    fi
    for row in "${LINKS[@]}"; do
      read -r src dst <<< "$row"
      link_one "$src" "$dst"
    done
    hooks_settings register
    echo
    echo "done. restart Claude Code once so it discovers the new command/skill/subagent/hooks."
    ;;
  unlink|--unlink)
    echo "unlinking postcommit from $CLAUDE_DIR"
    for row in "${LINKS[@]}"; do
      read -r src dst <<< "$row"
      unlink_one "$src" "$dst"
    done
    uninstall_package
    hooks_settings unregister
    ;;
  *)
    echo "usage: $0 [link|--unlink]" >&2
    exit 2
    ;;
esac
