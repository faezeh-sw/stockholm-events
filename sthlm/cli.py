from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import catalog, render
from .dedupe import merge
from .http import Http
from .models import TZ
from .registry import COLLECTORS, GENERIC, priorities
from .store import Store

log = logging.getLogger("sthlm")
ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def window(cfg: dict) -> tuple[datetime, datetime]:
    now = datetime.now(TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=cfg["window_days"], hours=23, minutes=59)


def cmd_collect(cfg: dict, only: list[str] | None) -> None:
    store = Store(ROOT / cfg["db_path"])
    win = window(cfg)
    known = store.known_ids()
    http = Http()
    classes = COLLECTORS | GENERIC
    for key, scfg in cfg["sources"].items():
        if not scfg.get("enabled", True) or (only and key not in only):
            continue
        cls = classes[key]
        t0 = time.time()
        seen: dict[str, set[str]] = {}
        count, err = 0, ""
        try:
            for ev in cls(scfg, http, win, known, store).fetch():
                store.upsert(ev)
                seen.setdefault(ev.source, set()).add(ev.id)
                count += 1
            prev = store.last_good_count(key)
            if prev and count < prev * 0.4:
                raise RuntimeError(f"suspicious drop: {count} events vs {prev} last time")
            for src, ids in seen.items():
                store.mark_missing(src, ids, win[0])
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log.error("source %s failed: %s", key, err)
        store.log_run(key, not err, count, err, time.time() - t0)
        store.commit()
        print(f"{'OK ' if not err else 'ERR'} {key:<14} {count:>5} events  {time.time() - t0:5.1f}s  {err}")


def cmd_stats(cfg: dict) -> None:
    store = Store(ROOT / cfg["db_path"])
    s, e = window(cfg)
    events = store.load_events(s, e)
    merged = merge(events, priorities())
    print(f"raw events in window: {len(events)}  ->  after dedupe: {len(merged)}")
    from collections import Counter
    print("by source:", dict(Counter(ev.source for ev in events)))
    multi = [m for m in merged if len(m.sources) > 1]
    print(f"events confirmed by 2+ sources: {len(multi)}")
    for m in merged[:15]:
        ev = m.event
        t = ev.local_start.strftime("%a %d %b %H:%M" if ev.time_known else "%a %d %b")
        print(f"  {t:<16} {ev.title[:60]:<60} | {ev.venue[:28]}")


def sync_messages(tg, store, kind: str, key: str, msgs: list[str]) -> str:
    """Post or update a multi-message digest idempotently. Returns what happened."""
    h = render.content_hash(msgs)
    prev = store.get_post(kind, key)
    if prev and prev[1] == h:
        return "unchanged"
    ids: list[int] = []
    old = prev[0] if prev else []
    for i, text in enumerate(msgs):
        if i < len(old):
            tg.edit(old[i], text)
            ids.append(old[i])
        else:
            ids.append(tg.send(text, silent=bool(prev)))
    for mid in old[len(msgs):]:
        tg.delete(mid)
    store.put_post(kind, key, ids, h)
    store.commit()
    return "updated" if prev else "posted"


AUDIENCES = {"fun": "🎉 <b>FUN &amp; ENTERTAINMENT</b>", "professional": "💼 <b>PROFESSIONAL &amp; CAREER</b>"}


def cmd_post(cfg: dict, kind: str, dry: bool, test: bool, no_llm: bool, on: str | None = None) -> None:
    from .telegram import Telegram
    store = Store(ROOT / cfg["db_path"])
    now = datetime.fromisoformat(on).replace(hour=7, tzinfo=TZ) if on else datetime.now(TZ)
    s, e = window(cfg)
    site = cfg.get("site_url", "")
    if kind == "legend":
        for audience in AUDIENCES:
            if dry:
                print(render.legend())
                return
            tg = Telegram.from_env(test=test, audience=audience)
            stored = f"{'test-' if test else ''}legend-{audience}"
            first = not store.get_post(stored, "v1")
            print(stored, sync_messages(tg, store, stored, "v1", [render.legend()]))
            if first:
                try:
                    tg.pin(store.get_post(stored, "v1")[0][0])
                except Exception as exc:          # needs the bot's "pin messages" right
                    print("  could not pin (give the bot the Pin Messages permission):", exc)
        return
    merged = catalog.build(store, s, e, enrich=not no_llm)
    build = {"daily": render.daily, "weekly": render.weekly}[kind]
    key = now.date().isoformat() if kind == "daily" else render.next_week_start(now.date()).isoformat()
    for audience, banner in AUDIENCES.items():
        mine = [m for m in merged if m.event.extra.get("audience", "fun") == audience]
        msgs = build(mine, now, site)
        if not msgs:
            print(f"{audience}: nothing to post")
            continue
        if dry:
            for i, m in enumerate(msgs, 1):
                print(f"\n----- {audience} message {i}/{len(msgs)} ({len(m)} chars) -----\n{m}")
            continue
        tg = Telegram.from_env(test=test, audience=audience)
        stored = f"{'test-' if test else ''}{kind}-{audience}"
        if test and not store.get_post(stored, key):
            # the test channel has no topics: separate the two sections with a banner message
            tg.send(banner, silent=True)
        print(stored, key, sync_messages(tg, store, stored, key, msgs))


def cmd_report(cfg: dict, send: bool) -> None:
    """Health summary: latest run per source + coverage numbers. Sent to the admin chat."""
    store = Store(ROOT / cfg["db_path"])
    rows = store.db.execute("""SELECT source, ok, count, error, seconds, run_at FROM source_runs
        WHERE rowid IN (SELECT MAX(rowid) FROM source_runs GROUP BY source) ORDER BY source""").fetchall()
    s, e = window(cfg)
    merged = catalog.build(store, s, e, enrich=False)
    lines = [f"<b>Stockholm Events — health</b> {datetime.now(TZ):%Y-%m-%d %H:%M}",
             f"Unique upcoming events (30d): <b>{len(merged)}</b>", ""]
    for r in rows:
        lines.append(f"{'✅' if r['ok'] else '❌'} {r['source']}: {r['count']} events, {r['seconds']:.0f}s"
                     + (f" — {render.esc(r['error'])}" if r["error"] else ""))
    text = "\n".join(lines)
    if send:
        from .telegram import Telegram
        Telegram.from_env(admin=True).send(text, silent=True)
    else:
        print(text)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_env()
    ap = argparse.ArgumentParser(prog="sthlm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--only", nargs="*")
    sub.add_parser("stats")
    rp = sub.add_parser("report")
    rp.add_argument("--send", action="store_true")
    pp = sub.add_parser("post")
    pp.add_argument("kind", choices=["weekly", "daily", "legend"])
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--test", action="store_true", help="send to the test channel instead of the public one")
    pp.add_argument("--no-llm", action="store_true")
    pp.add_argument("--date", help="pretend today is this date (YYYY-MM-DD), for previews")
    args = ap.parse_args()
    cfg = load_config()
    if args.cmd == "collect":
        cmd_collect(cfg, args.only)
    elif args.cmd == "post":
        cmd_post(cfg, args.kind, args.dry_run, args.test, args.no_llm, args.date)
    elif args.cmd == "report":
        cmd_report(cfg, args.send)
    elif args.cmd == "stats":
        cmd_stats(cfg)


if __name__ == "__main__":
    main()
