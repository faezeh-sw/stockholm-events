from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, source TEXT, source_id TEXT, title TEXT, start TEXT, end TEXT, time_known INT,
    description TEXT, venue TEXT, address TEXT, area TEXT, lat REAL, lon REAL, price_text TEXT, is_free INT,
    url TEXT, image_url TEXT, category TEXT, lang TEXT, online INT, cancelled INT, extra TEXT,
    first_seen TEXT, last_seen TEXT, missing_runs INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_events_start ON events(start);
CREATE TABLE IF NOT EXISTS url_cache (
    url TEXT PRIMARY KEY, fetched_at TEXT, events TEXT
);
CREATE TABLE IF NOT EXISTS enrich (
    key TEXT PRIMARY KEY, data TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    kind TEXT, key TEXT, message_ids TEXT, content_hash TEXT, posted_at TEXT, PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS source_runs (
    run_at TEXT, source TEXT, ok INT, count INT, error TEXT, seconds REAL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- events -----------------------------------------------------------------------------
    def known_ids(self) -> set[str]:
        return {r["id"] for r in self.db.execute("SELECT id FROM events")}

    def upsert(self, ev: Event) -> None:
        row = ev.to_row()
        row["extra"] = json.dumps(row["extra"], ensure_ascii=False)
        ts = now_iso()
        exists = self.db.execute("SELECT 1 FROM events WHERE id=?", (row["id"],)).fetchone()
        cols = ["id", "source", "source_id", "title", "start", "end", "time_known", "description", "venue", "address",
                "area", "lat", "lon", "price_text", "is_free", "url", "image_url", "category", "lang", "online",
                "cancelled", "extra"]
        vals = [row[c] for c in cols]
        if exists:
            sets = ",".join(f"{c}=?" for c in cols[1:])
            self.db.execute(f"UPDATE events SET {sets}, last_seen=?, missing_runs=0 WHERE id=?", vals[1:] + [ts, row["id"]])
        else:
            self.db.execute(f"INSERT INTO events ({','.join(cols)}, first_seen, last_seen) VALUES ({','.join('?' * len(cols))},?,?)",
                            vals + [ts, ts])

    def mark_missing(self, source: str, seen_ids: set[str], after: datetime) -> int:
        """Events of a healthy source that were not returned this run: count a miss; cancel after 3."""
        rows = self.db.execute("SELECT id FROM events WHERE source=? AND start>? AND cancelled=0",
                               (source, after.astimezone(timezone.utc).isoformat())).fetchall()
        n = 0
        for r in rows:
            if r["id"] not in seen_ids:
                self.db.execute("UPDATE events SET missing_runs=missing_runs+1 WHERE id=?", (r["id"],))
                n += 1
        return n

    def load_events(self, since: datetime, until: datetime, max_missing: int = 2) -> list[Event]:
        q = "SELECT * FROM events WHERE start>=? AND start<=? AND missing_runs<=? ORDER BY start"
        rows = self.db.execute(q, (since.astimezone(timezone.utc).isoformat(), until.astimezone(timezone.utc).isoformat(), max_missing))
        return [Event.from_row(dict(r)) for r in rows]

    # --- per-URL cache for detail-page collectors ---------------------------------------------
    def get_url(self, url: str, max_age_hours: float, empty_max_age_hours: float | None = None) -> list[Event] | None:
        r = self.db.execute("SELECT fetched_at, events FROM url_cache WHERE url=?", (url,)).fetchone()
        if not r:
            return None
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["fetched_at"])).total_seconds() / 3600
        rows = json.loads(r["events"])
        limit = empty_max_age_hours if (not rows and empty_max_age_hours) else max_age_hours
        if age > limit:
            return None
        return [Event.from_row(d) for d in rows]

    def put_url(self, url: str, events: list[Event]) -> None:
        self.db.execute("INSERT OR REPLACE INTO url_cache VALUES (?,?,?)",
                        (url, now_iso(), json.dumps([e.to_row() for e in events], ensure_ascii=False)))

    # --- enrichment cache -------------------------------------------------------------------
    def get_enrich(self, key: str) -> dict | None:
        r = self.db.execute("SELECT data FROM enrich WHERE key=?", (key,)).fetchone()
        return json.loads(r["data"]) if r else None

    def put_enrich(self, key: str, data: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO enrich VALUES (?,?,?)", (key, json.dumps(data, ensure_ascii=False), now_iso()))

    # --- posts ------------------------------------------------------------------------------
    def get_post(self, kind: str, key: str):
        r = self.db.execute("SELECT * FROM posts WHERE kind=? AND key=?", (kind, key)).fetchone()
        return (json.loads(r["message_ids"]), r["content_hash"]) if r else None

    def put_post(self, kind: str, key: str, message_ids: list[int], content_hash: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                        (kind, key, json.dumps(message_ids), content_hash, now_iso()))

    # --- health -----------------------------------------------------------------------------
    def log_run(self, source: str, ok: bool, count: int, error: str, seconds: float) -> None:
        self.db.execute("INSERT INTO source_runs VALUES (?,?,?,?,?,?)", (now_iso(), source, int(ok), count, error[:500], seconds))

    def last_good_count(self, source: str) -> int | None:
        r = self.db.execute("SELECT count FROM source_runs WHERE source=? AND ok=1 ORDER BY run_at DESC LIMIT 1", (source,)).fetchone()
        return r["count"] if r else None

    def commit(self) -> None:
        self.db.commit()
