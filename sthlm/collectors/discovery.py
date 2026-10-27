"""Long-tail discovery: Claude searches the web for Stockholm events that no aggregator lists.

Covers company events (AWS, Google, Microsoft...), university and association seminars, conferences, job fairs.
Each query runs the Anthropic web-search tool; an event is accepted only when its URL appeared in the search results
(so the model cannot invent a page) and its date falls in the window. Results are cached for a few days, so the
daily run only pays when the cache is stale.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

from .. import usage
from ..models import Event, TZ
from ..parse import clean_text, parse_dt
from .base import Collector

log = logging.getLogger(__name__)

MODEL = os.environ.get("DISCOVERY_MODEL", "claude-haiku-5-5")

SYSTEM = """You are researching upcoming in-person events in Stockholm, Sweden (including Solna, Sundbyberg, Kista, Nacka).
Today is {today}. Only report events that START between {start} and {end}.

Use web search. Prefer the organiser's own event page over aggregators. Skip online-only events, past events,
permanent attractions, and anything whose date or city you could not confirm from a page.

When finished, reply with ONLY a JSON array (no prose, no code fence). One object per event:
{{"title": str, "start": "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", "end": same or null, "venue": str or null,
  "url": the specific event page URL you found, "organizer": str or null, "price": "Free" / "250 kr" / null,
  "description": one short factual sentence}}
Never invent events, dates or URLs. If nothing qualifies, reply with []."""

DEFAULT_QUERIES = [
    "AWS Google Cloud Microsoft events Stockholm {m1}", "tech meetup conference Stockholm {m1} {y1}",
    "startup founders investors events Stockholm {m1}", "networking events Stockholm {m1} professionals",
    "career fair job fair Stockholm {m1}", "business seminar conference Stockholm {m2} {y2}",
    "AI data machine learning event Stockholm {m1}", "cybersecurity fintech event Stockholm {m1}",
    "women in tech leadership event Stockholm {m1}", "KTH Stockholm University SSE public lecture professionals {m1}",
    "international professionals job market workshop Stockholm {m1}", "affärsnätverk seminarium evenemang Stockholm {m1}",
    "mässa konferens Stockholm {m1} {y1}", "product design UX developer event Stockholm {m1}",
]


class Discovery(Collector):
    name = "discovery"
    priority = 44

    def __init__(self, *a, client=None, **kw):
        super().__init__(*a, **kw)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def fetch(self):
        if not self._client and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        m1, m2 = self.start, self.end
        fmt = {"m1": m1.strftime("%B"), "y1": m1.year, "m2": m2.strftime("%B"), "y2": m2.year}
        queries = [q.format(**fmt) for q in self.cfg.get("queries", DEFAULT_QUERIES)]
        cache_h = self.cfg.get("cache_hours", 24 * 6)
        todo, seen = [], set()
        for q in queries:
            key = f"disc:{q}"
            cached = self.store.get_url(key, cache_h) if self.store else None
            if cached is None:
                todo.append((q, key))
            else:
                for ev in cached:
                    if ev.source_id not in seen and self.in_window(ev.start):
                        seen.add(ev.source_id)
                        yield ev
        log.info("discovery: %d queries to run, %d cached", len(todo), len(queries) - len(todo))
        with ThreadPoolExecutor(self.cfg.get("workers", 4)) as pool:
            for (q, key), evs in zip(todo, pool.map(lambda t: self._run(t[0]), todo)):
                if evs is None:                       # failed: do not cache, try again next run
                    continue
                if self.store:
                    self.store.put_url(key, evs)
                    self.store.commit()
                for ev in evs:
                    if ev.source_id not in seen and self.in_window(ev.start):
                        seen.add(ev.source_id)
                        yield ev

    def _run(self, query: str) -> list[Event] | None:
        system = SYSTEM.format(today=datetime.now(TZ).date().isoformat(), start=self.start.date().isoformat(),
                               end=self.end.date().isoformat())
        messages = [{"role": "user", "content": f"Search: {query}"}]
        urls: set[str] = set()
        text = ""
        try:
            for _ in range(4):                        # a long search can pause; continue until it finishes
                msg = self.client.messages.create(
                    model=MODEL, max_tokens=4000, system=system, messages=messages,
                    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": self.cfg.get("max_uses", 4)}])
                usage.record("discovery", getattr(msg, "usage", None))
                for b in msg.content:
                    if b.type == "web_search_tool_result" and isinstance(b.content, list):
                        urls.update(norm_url(r.url) for r in b.content if getattr(r, "url", None))
                text = "".join(b.text for b in msg.content if b.type == "text")
                if msg.stop_reason != "pause_turn":
                    break
                messages.append({"role": "assistant", "content": msg.content})
        except Exception as exc:
            log.warning("discovery %r failed: %s", query, exc)
            return None
        return [e for e in (self._to_event(i, urls) for i in parse_json_array(text)) if e]

    def _to_event(self, i: dict, urls: set[str]) -> Event | None:
        url = i.get("url") or ""
        start, known = parse_dt(i.get("start"))
        title = clean_text(i.get("title"))
        if not (url and start and title) or norm_url(url) not in urls:
            return None                                # not a page the search actually returned
        end, _ = parse_dt(i.get("end"))
        price = (i.get("price") or "").strip()
        free = price.lower() in ("free", "gratis", "fri entré")
        return Event(
            source=self.name, source_id=f"{norm_url(url)}|{start.date()}", title=title, start=start, end=end,
            time_known=known, url=url, description=clean_text(i.get("description"), 400),
            venue=clean_text(i.get("venue")), area="Stockholm", price_text="Free" if free else price,
            is_free=True if free else None, extra={"host": clean_text(i.get("organizer")), "found_by": "web search"},
        )


def norm_url(u: str) -> str:
    p = urlparse(u.strip())
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def parse_json_array(text: str) -> list[dict]:
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]
