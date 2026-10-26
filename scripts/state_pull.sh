#!/usr/bin/env bash
# Restore data/events.sqlite from the "state" branch (if it exists yet).
set -e
mkdir -p data
if git ls-remote --exit-code --heads origin state >/dev/null 2>&1; then
  git fetch --depth=1 origin state
  git show FETCH_HEAD:events.sqlite > data/events.sqlite
  echo "state restored: $(du -h data/events.sqlite | cut -f1)"
else
  echo "no state branch yet: starting fresh"
fi
