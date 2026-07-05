#!/usr/bin/env bash
#
# link-local.sh — symlink this repo's command, skill, and subagent into
# ~/.claude/ so /post is available in Claude Code without publishing the
# plugin. Idempotent. Refuses to overwrite non-symlink files at the target.
#
# Usage:
#   scripts/link-local.sh          # link
#   scripts/link-local.sh --unlink # remove the symlinks
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"

# source_relative_to_repo   target_relative_to_claude_dir
LINKS=(
  "commands/post.md                    commands/post.md"
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

action="${1:-link}"
case "$action" in
  link|--link|"")
    echo "linking postcommit → $CLAUDE_DIR"
    for row in "${LINKS[@]}"; do
      read -r src dst <<< "$row"
      link_one "$src" "$dst"
    done
    echo
    echo "done. restart Claude Code once so it discovers the new command/skill/subagent."
    ;;
  unlink|--unlink)
    echo "unlinking postcommit from $CLAUDE_DIR"
    for row in "${LINKS[@]}"; do
      read -r src dst <<< "$row"
      unlink_one "$src" "$dst"
    done
    ;;
  *)
    echo "usage: $0 [link|--unlink]" >&2
    exit 2
    ;;
esac
