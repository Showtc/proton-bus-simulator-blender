#!/usr/bin/env bash
# Build the GitHub release notes for a tag:
#
#   # What's Changed
#   <content of changelog.md>
#
#   # Changelog
#   <commits since the previous tag>
#
# Usage: release_notes.sh <tag> [owner/repo] > notes.md
set -euo pipefail

tag="$1"
repo="${2:-}"

if [ ! -f changelog.md ] || [ -z "$(tr -d '[:space:]' < changelog.md)" ]; then
  echo "changelog.md is missing or empty" >&2
  exit 1
fi

# Previous tag reachable from this one (none for the first release: list all commits)
previous=$(git describe --tags --abbrev=0 --match 'v*' "${tag}^" 2>/dev/null || true)
if [ -n "$previous" ]; then
  range="${previous}..${tag}"
else
  range="$tag"
fi

if [ -n "$repo" ]; then
  format="- %s ([%h](https://github.com/${repo}/commit/%H))"
else
  format="- %s (%h)"
fi

echo "# What's Changed"
echo
cat changelog.md
echo
echo "# Changelog"
echo
commits=$(git log --no-merges --pretty=format:"$format" "$range")
if [ -n "$commits" ]; then
  echo "$commits"
else
  echo "- No new commits"
fi
if [ -n "$previous" ] && [ -n "$repo" ]; then
  echo
  echo "**Full diff**: https://github.com/${repo}/compare/${previous}...${tag}"
fi
