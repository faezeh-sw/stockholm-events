from __future__ import annotations

import logging

from ..parse import is_event_type, jsonld_objects
from .base import Collector, event_from_jsonld

log = logging.getLogger(__name__)

BASE = "https://www.eventbrite.se/d/sweden--stockholm/{cat}events/"


class Eventbrite(Collector):
    name = "eventbrite"
    priority = 40

    def fetch(self):
        s, e = self.start.date().isoformat(), self.end.date().isoformat()
        seen: set[str] = set()
        for cat in self.cfg.get("categories", [""]):
            prefix = f"{cat}--" if cat else ""
            for page in range(1, self.cfg.get("max_pages", 40) + 1):
                r = self.http.get(BASE.format(cat=prefix), params={"page": page, "start_date": s, "end_date": e})
                new = 0
                for o in jsonld_objects(r.text):
                    if not is_event_type(o):
                        continue
                    ev = event_from_jsonld(o, self.name)
                    if not ev or ev.url in seen:
                        continue
                    seen.add(ev.url)
                    new += 1
                    if ev.id not in self.known_ids and self.cfg.get("detail", True):
                        self._add_detail(ev)
                    if self.in_window(ev.start) and not ev.online:
                        yield ev
                if new == 0:
                    break

    def _add_detail(self, ev):
        """Search pages only carry a date; the event page has the start time, price and venue."""
        try:
            r = self.http.get(ev.url)
        except Exception as exc:  # detail is best-effort
            log.debug("eventbrite detail failed %s: %s", ev.url, exc)
            return
        for o in jsonld_objects(r.text):
            if is_event_type(o):
                full = event_from_jsonld(o, self.name, ev.url)
                if full:
                    ev.start, ev.end, ev.time_known = full.start, full.end, full.time_known
                    ev.price_text, ev.is_free = full.price_text or ev.price_text, full.is_free
                    ev.description = full.description or ev.description
                    ev.venue = full.venue or ev.venue
                    ev.online = full.online
                break
