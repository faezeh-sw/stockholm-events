"""Meetup.com events around Stockholm via Meetup's public GraphQL endpoint (no login needed).

The search requires a non-empty keyword, so we run a list of keywords (see config) and merge the results by event id.
"""
from __future__ import annotations

import logging

from ..models import Event
from ..parse import clean_text, parse_dt
from .base import Collector

log = logging.getLogger(__name__)

API = "https://www.meetup.com/gql2"
QUERY = """query($filter: EventSearchFilter!, $first: Int, $after: String) {
  eventSearch(filter: $filter, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title eventUrl dateTime endTime isOnline eventType status description
      venue { name address city lat lon } group { name urlname } feeSettings { amount currency }
      featuredEventPhoto { highResUrl } } }
  }
}"""

DEFAULT_KEYWORDS = [
    "tech", "startup", "AI", "developer", "data", "product", "design", "marketing", "career", "networking", "business",
    "finance", "founders", "leadership", "cloud", "security", "engineering", "sales", "women", "entrepreneur",
    "python", "java", "UX", "investor", "consulting", "agile", "blockchain", "healthcare", "biotech", "sustainability",
    "climate", "fintech", "game", "professionals", "job", "freelance", "workshop", "conference", "meetup",
    "social", "language exchange", "expats", "international", "hiking", "board games", "running", "yoga", "music",
    "art", "food", "film", "book club", "photography", "dance", "sports", "volunteer", "parents", "board",
]


class Meetup(Collector):
    name = "meetup"
    priority = 62

    def fetch(self):
        seen: set[str] = set()
        keywords = self.cfg.get("keywords", DEFAULT_KEYWORDS)
        for kw in keywords:
            n_new = 0
            after = None
            for _ in range(self.cfg.get("max_pages", 4)):
                variables = {"first": 100, "after": after, "filter": {
                    "query": kw, "lat": 59.3293, "lon": 18.0686, "radius": self.cfg.get("radius_km", 35),
                    "startDateRange": self.start.isoformat(), "endDateRange": self.end.isoformat()}}
                data = self.http.post(API, json={"query": QUERY, "variables": variables}).json()
                if data.get("errors") and not data.get("data"):
                    raise RuntimeError(f"meetup graphql: {data['errors'][0]['message'][:120]}")
                es = data["data"]["eventSearch"]
                for edge in es["edges"]:
                    ev = self._to_event(edge["node"])
                    if ev and ev.source_id not in seen:
                        seen.add(ev.source_id)
                        n_new += 1
                        yield ev
                if not es["pageInfo"]["hasNextPage"]:
                    break
                after = es["pageInfo"]["endCursor"]
            log.debug("meetup %r: %d new", kw, n_new)

    def _to_event(self, n: dict) -> Event | None:
        if n.get("isOnline") or n.get("eventType") == "ONLINE" or n.get("status") not in (None, "ACTIVE", "PUBLISHED"):
            return None
        start, _ = parse_dt(n.get("dateTime"))
        end, _ = parse_dt(n.get("endTime"))
        if not start or not self.in_window(start):
            return None
        v = n.get("venue") or {}
        fee = n.get("feeSettings")
        amount = fee.get("amount") if fee else None
        cur = ((fee or {}).get("currency") or "").replace("SEK", "kr")
        photo = (n.get("featuredEventPhoto") or {}).get("highResUrl") or ""
        return Event(
            source=self.name, source_id=n["id"], title=clean_text(n["title"]), start=start, end=end, time_known=True,
            url=n["eventUrl"], description=clean_text(n.get("description"), 1200), venue=clean_text(v.get("name")),
            address=", ".join(x for x in (v.get("address"), v.get("city")) if x), area=v.get("city") or "",
            lat=v.get("lat"), lon=v.get("lon"), image_url=photo,
            is_free=True if not fee else (amount == 0 or None),
            price_text=("Free" if (not fee or amount == 0) else f"{amount:g} {cur}".strip()),
            extra={"host": (n.get("group") or {}).get("name", "")},
        )
