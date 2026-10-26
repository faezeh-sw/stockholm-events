from __future__ import annotations

import logging
import re

from ..parse import is_event_type, jsonld_objects
from .base import Collector, event_from_jsonld
from .sitemaps import sitemap_urls

log = logging.getLogger(__name__)


class SitemapJsonLd(Collector):
    """Venue sites that expose one page per event with schema.org/Event JSON-LD, discovered via sitemap.

    config: sites: [{name, sitemap, include (regex), venue, area, category, cache_hours, max_urls}]
    Detail pages are cached, so a daily run only re-fetches pages older than `cache_hours`.
    """
    name = "sitemap_jsonld"
    priority = 58

    def fetch(self):
        for site in self.cfg["sites"]:
            try:
                urls = sitemap_urls(self.http, site["sitemap"], site.get("include"))
            except Exception as exc:
                log.warning("%s: %s", site["name"], exc)
                continue
            for u in urls[: site.get("max_urls", 600)]:
                events = self.store.get_url(u, site.get("cache_hours", 24)) if self.store else None
                if events is None:
                    events = self._parse(u, site)
                    if self.store:
                        self.store.put_url(u, events)
                for ev in events:
                    if self.in_window(ev.start):
                        yield ev

    def _parse(self, url: str, site: dict):
        try:
            h = self.http.get(url).text
        except Exception as exc:
            log.debug("%s: %s", url, exc)
            return []
        out = []
        for o in jsonld_objects(h):
            if not is_event_type(o):
                continue
            ev = event_from_jsonld(o, site["name"], url)
            if not ev:
                continue
            ev.venue = ev.venue or site.get("venue", "")
            ev.area = ev.area or site.get("area", "Stockholm")
            ev.category = ev.category or site.get("category", "")
            if not ev.url:
                ev.url = url
            out.append(ev)
        return out
