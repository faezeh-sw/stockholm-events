#!/usr/bin/env bash
# Store data/events.sqlite as the single commit of the orphan "state" branch (no history growth).
set -e
[ -f data/events.sqlite ] || exit 0
python - <<'PY'
import sqlite3
db = sqlite3.connect("data/events.sqlite")
db.execute("DELETE FROM url_cache WHERE fetched_at < datetime('now','-35 days')")
db.execute("DELETE FROM events WHERE start < datetime('now','-3 days')")
db.commit(); db.execute("VACUUM"); db.close()
PY
tmp=$(mktemp -d)
cp data/events.sqlite "$tmp/events.sqlite"
git config user.name "events-bot"
git config user.email "events-bot@users.noreply.github.com"
git checkout --orphan state-new
git rm -rf --cached . >/dev/null 2>&1 || true
cp "$tmp/events.sqlite" ./events.sqlite
git add -f events.sqlite
git commit -m "state $(date -u +%FT%TZ)" >/dev/null
git push -f origin state-new:state
