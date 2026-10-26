from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import Event, TZ
from ..parse import clean_text
from .base import Collector
from .sitemaps import sitemap_urls

log = logging.getLogger(__name__)

URL_RE = re.compile(r"/events/(?P<id>[a-z0-9]+)/(?P<date>\d{4}-\d{2}-\d{2})/(?P<slug>[^/?#]+)")
DESC_RE = re.compile(r"^(?P<t>.*) på (?P<v>.*) i (?P<c>.*?) den \d{1,2} \w+(?: \d{4})? - Tickster", re.S)
START_RE = re.compile(r"Startar\s+\d{1,2}\s+\w{3}\s+(\d{2}):(\d{2})")
# Tickster sells tickets nationwide; we keep Greater Stockholm.
CITIES = {"stockholm", "solna", "sundbyberg", "nacka", "lidingö", "täby", "kista", "huddinge", "järfälla", "danderyd",
          "sollentuna", "tyresö", "värmdö", "haninge", "botkyrka", "södertälje", "upplands väsby", "vallentuna",
          "bromma", "hägersten", "farsta", "skärholmen", "gustavsberg", "saltsjöbaden", "jakobsberg", "älvsjö",
          "johanneshov", "hammarbyhöjden", "årsta", "spånga", "hässelby", "vällingby", "kungsholmen", "södermalm"}


class Tickster(Collector):
    name = "tickster"
    priority = 45

    def fetch(self):
        urls = sitemap_urls(self.http, "https://tickster.com/robots.txt")
        wanted = []
        for u in urls:
            m = URL_RE.search(u)
            if not m:
                continue
            d = datetime.fromisoformat(m["date"]).replace(tzinfo=TZ)
            if self.start.replace(hour=0, minute=0) <= d <= self.end:
                wanted.append(u)
        log.info("tickster: %d of %d sitemap urls in window", len(wanted), len(urls))
        wanted = wanted[: self.cfg.get("max_urls", 4000)]
        todo = []
        for u in wanted:
            cached = self.store.get_url(u, 48, empty_max_age_hours=24 * 30) if self.store else None
            if cached is None:
                todo.append(u)
            else:
                yield from cached
        log.info("tickster: fetching %d pages (%d served from cache)", len(todo), len(wanted) - len(todo))
        from concurrent.futures import ThreadPoolExecutor
        # A first run may need thousands of pages; stop at the time budget and finish on the next run (cache keeps progress).
        deadline = time.monotonic() + self.cfg.get("time_budget_s", 1500)
        workers = self.cfg.get("workers", 16)
        with ThreadPoolExecutor(workers) as pool:
            for i in range(0, len(todo), workers * 4):
                if time.monotonic() > deadline:
                    log.warning("tickster: time budget hit, %d pages left for the next run", len(todo) - i)
                    break
                chunk = todo[i:i + workers * 4]
                for u, evs in zip(chunk, pool.map(self._parse, chunk)):
                    if self.store:
                        self.store.put_url(u, evs)
                    yield from evs
                if self.store:
                    self.store.commit()

    def _parse(self, url: str) -> list[Event]:
        try:
            h = self.http.get(url, delay=self.cfg.get("delay", 0.08)).text
        except Exception as exc:
            log.debug("tickster %s: %s", url, exc)
            return []
        s = BeautifulSoup(h, "html.parser")
        desc = (s.find("meta", attrs={"name": "description"}) or {}).get("content", "")
        m = DESC_RE.match(desc)
        if not m or m["c"].strip().lower() not in CITIES:
            return []
        u = URL_RE.search(url)
        title = clean_text((s.find("meta", property="og:title") or {}).get("content") or m["t"])
        text = s.get_text(" ", strip=True)
        tm = START_RE.search(text)
        start = datetime.fromisoformat(u["date"]).replace(tzinfo=TZ)
        known = False
        if tm:
            start, known = start.replace(hour=int(tm[1]), minute=int(tm[2])), True
        cancelled = bool(re.search(r"\b(Inställt|Inställd)\b", text[:1500]))
        return [Event(
            source=self.name, source_id=u["id"] + u["date"], title=title, start=start, time_known=known, url=url,
            venue=clean_text(m["v"]), area=clean_text(m["c"]), cancelled=cancelled,
            image_url=(s.find("meta", property="og:image") or {}).get("content", ""),
        )]
