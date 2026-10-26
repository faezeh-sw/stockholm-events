from __future__ import annotations

import logging
import re
from datetime import timedelta

from bs4 import BeautifulSoup

from ..parse import is_event_type, jsonld_objects
from .base import Collector, event_from_jsonld

log = logging.getLogger(__name__)


class VisitStockholm(Collector):
    """Official city guide: ~30 curated highlights. Each detail page lists every date of the event."""
    name = "visitstockholm"
    priority = 70

    def fetch(self):
        h = self.http.get("https://www.visitstockholm.com/events/").text
        links = sorted({a["href"] for a in BeautifulSoup(h, "html.parser").select('a[href$="/next/"]')})
        for u in links:
            events = self.store.get_url(u, 20) if self.store else None
            if events is None:
                events = self._parse(u)
                if self.store:
                    self.store.put_url(u, events)
            for ev in events:
                if self.in_window(ev.start):
                    ev.extra["curated"] = True
                    yield ev

    def _parse(self, url: str):
        try:
            h = self.http.get(url).text
        except Exception as exc:
            log.warning("visitstockholm %s: %s", url, exc)
            return []
        out = []
        for o in jsonld_objects(h):
            if is_event_type(o):
                ev = event_from_jsonld(o, self.name, url)
                if not ev:
                    continue
                m = re.search(r"/(\d{4}-\d{2}-\d{2})/(\d{2})(\d{2})/(\d{2})(\d{2})/?$", ev.url)
                if m:        # occurrence URLs carry the times: .../2026-10-23/1830/2300/
                    ev.start = ev.start.replace(hour=int(m[2]), minute=int(m[3]))
                    ev.time_known = True
                    ev.end = ev.start.replace(hour=int(m[4]) % 24, minute=int(m[5]))
                    if ev.end < ev.start:
                        ev.end += timedelta(days=1)
                elif ev.end and (ev.end - ev.start).days > 14:
                    ev.extra["ongoing_until"] = ev.end.date().isoformat()
                    ev.end = None
                out.append(ev)
        return out
