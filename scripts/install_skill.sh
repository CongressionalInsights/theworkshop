#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_NAME="theworkshop"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
TARGET_DIR="$CODEX_HOME_DIR/skills/$TARGET_NAME"

usage() {
  cat <<USAGE
Install TheWorkshop skill into Codex/Claude skill directory.

Usage:
  $(basename "$0") [--target DIR] [--force] [--link]

Options:
  --target DIR   Override install destination (default: $TARGET_DIR)
  --force        Remove existing target first
  --link         Symlink instead of copy
USAGE
}

FORCE=0
LINK=0
CUSTOM_TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      CUSTOM_TARGET="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --link)
      LINK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -n "$CUSTOM_TARGET" ]]; then
  TARGET_DIR="$CUSTOM_TARGET"
fi

mkdir -p "$(dirname "$TARGET_DIR")"

if [[ -e "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    rm -rf "$TARGET_DIR"
  else
    echo "Target already exists: $TARGET_DIR" >&2
    echo "Use --force to replace." >&2
    exit 1
  fi
fi

if [[ "$LINK" -eq 1 ]]; then
  ln -s "$SKILL_ROOT" "$TARGET_DIR"
else
  rsync -a \
    --exclude '.git' \
    --exclude '_test_runs' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$SKILL_ROOT/" "$TARGET_DIR/"
fi

echo "Installed TheWorkshop -> $TARGET_DIR"
