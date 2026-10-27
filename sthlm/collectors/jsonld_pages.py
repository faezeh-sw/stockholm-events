from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ..parse import is_event_type, jsonld_objects, parse_dt
from ..geo import held_in_stockholm
from .base import Collector, event_from_jsonld

log = logging.getLogger(__name__)


class JsonLdPages(Collector):
    """Generic collector: fetch a list of pages and read schema.org/Event JSON-LD.

    config: pages: [{url, name, venue, area, category}]
    """
    name = "jsonld"
    priority = 55

    def fetch(self):
        for page in self.cfg["pages"]:
            try:
                r = self.http.get(page["url"])
            except Exception as exc:
                log.warning("%s: %s", page["url"], exc)
                continue
            for o in jsonld_objects(r.text):
                if not is_event_type(o):
                    continue
                ev = event_from_jsonld(o, page.get("name", "jsonld"), page["url"])
                if not ev:
                    continue
                if page.get("naive_time"):     # source labels local clock times as UTC: keep the clock, fix the zone
                    dt, known = parse_dt(re.sub(r"(Z|[+-]\d\d:?\d\d)$", "", o.get("startDate", "")))
                    if dt:
                        ev.start, ev.time_known = dt, known
                if not self.in_window(ev.start):
                    continue
                if not held_in_stockholm(ev, strict=bool(page.get("city"))):
                    continue
                if ev.online:
                    continue
                host = urlparse(ev.url).netloc.removeprefix("www.")
                ev.venue = ev.venue or page.get("venue_by_domain", {}).get(host, "") or page.get("venue", "")
                ev.area = ev.area or page.get("area", "")
                ev.category = page.get("category", "")
                if page.get("audience"):
                    ev.extra["audience_hint"] = page["audience"]
                yield ev
