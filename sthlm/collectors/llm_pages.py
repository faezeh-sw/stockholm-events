"""Generic collector for venue sites with no structured data: Claude reads the page text and returns events.

config: pages: [{name, urls: [...], venue, area, category, cache_hours}]
The page text is hashed; unchanged pages are served from cache, so the LLM is only paid when a calendar changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Event, TZ
from ..parse import clean_text, parse_dt
from .base import Collector

log = logging.getLogger(__name__)

MODEL = os.environ.get("EXTRACT_MODEL", "claude-haiku-5-5")
MAX_CHARS = 28000

PROMPT = """You extract upcoming events from the text of a venue's calendar web page (Swedish or English).
Today is {today} (Europe/Stockholm). Only return events that START between {start} and {end}.

Rules:
- Return ONLY a JSON array. Each item: {{"title": str, "start": "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", "end": same format or null,
  "url": the event's own page URL taken from the text or null, "price": short text like "250 kr" / "Free" or null,
  "description": one short sentence in the page's language or null}}.
- Use "YYYY-MM-DD" when the clock time is not stated. Infer the year from today's date (dates never lie in the past).
- Never invent events, dates, times or URLs. If something is ambiguous, skip it.
- Skip navigation, ads, ticket-policy text, gift cards, and permanent attractions without a specific date.
- An event on several dates becomes one item per date shown on the page.
- If the page contains no qualifying events, return []."""


def page_text(html: str, base: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        t.decompose()
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if href.startswith("http"):
            a.replace_with(f"{a.get_text(' ', strip=True)} <{href}>")
    lines, seen = [], set()
    for ln in soup.get_text("\n").splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln and ln not in seen:
            seen.add(ln)
            lines.append(ln)
    return "\n".join(lines)[:MAX_CHARS]


class LlmPages(Collector):
    name = "llm_pages"
    priority = 52

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
        for page in self.cfg["pages"]:
            for url in page.get("urls") or [page["url"]]:
                try:
                    html = self.http.get(url).text
                except Exception as exc:
                    log.warning("%s: %s", url, exc)
                    continue
                text = page_text(html, url)
                if len(text) < 200:
                    log.warning("%s: almost no text (JS-rendered page?)", url)
                    continue
                key = f"llm:{url}:{hashlib.sha1(text.encode()).hexdigest()[:12]}:{datetime.now(TZ).date()}"
                events = self.store.get_url(key, page.get("cache_hours", 72)) if self.store else None
                if events is None:
                    events = self._extract(text, url, page)
                    if self.store:
                        self.store.put_url(key, events)
                for ev in events:
                    if self.in_window(ev.start):
                        yield ev

    def _extract(self, text: str, url: str, page: dict) -> list[Event]:
        today = datetime.now(TZ).date()
        msg = self.client.messages.create(
            model=MODEL, max_tokens=6000,
            system=PROMPT.format(today=today.isoformat(), start=self.start.date().isoformat(), end=self.end.date().isoformat()),
            messages=[{"role": "user", "content": f"Page URL: {url}\n\n{text}"}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("%s: model returned invalid JSON", url)
            return []
        return [e for e in (self._to_event(i, url, page) for i in items if isinstance(i, dict)) if e]

    @staticmethod
    def _to_event(i: dict, page_url: str, page: dict) -> Event | None:
        start, known = parse_dt(i.get("start"))
        title = clean_text(i.get("title"))
        if not start or not title:
            return None
        end, _ = parse_dt(i.get("end"))
        link = i.get("url") or page_url
        price = (i.get("price") or "").strip()
        return Event(
            source=page["name"], source_id=f"{link}|{start.isoformat()}", title=title, start=start, end=end,
            time_known=known, url=link, description=clean_text(i.get("description"), 400),
            venue=page.get("venue", ""), area=page.get("area", "Stockholm"), category=page.get("category", ""),
            price_text="Free" if price.lower() in ("free", "gratis", "fri entré") else price,
            is_free=True if price.lower() in ("free", "gratis", "fri entré") else None,
        )
