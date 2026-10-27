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

from .. import usage
from ..models import Event, TZ
from ..parse import clean_text, is_event_type, jsonld_objects, parse_dt
from .base import Collector, event_from_jsonld
from .. import browser
from ..geo import held_in_stockholm
from .tickster import CITIES

log = logging.getLogger(__name__)

MODEL = os.environ.get("EXTRACT_MODEL", "claude-haiku-5-5")
MAX_CHARS = 12000

PROMPT = """You extract upcoming events from the text of a venue's calendar web page (Swedish or English).
Today is {today} (Europe/Stockholm). Only return events that START between {start} and {end}.

Rules:
- Call submit_events with the list. Each item: {{"title": str, "start": "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", "end": same format or null,
  "url": the event's own page URL taken from the text or null, "price": short text like "250 kr" / "Free" or null,
  "description": one short sentence in the page's language or null, "venue": the place if the page names it, else null, "city": the city where THIS event is held, else null, "online": true if it is online / a webinar / on Zoom or Teams}}.
- Use "YYYY-MM-DD" when the clock time is not stated. Infer the year from today's date (dates never lie in the past).
- Never invent events, dates, times or URLs. If something is ambiguous, skip it.
- Skip navigation, ads, ticket-policy text, gift cards, and permanent attractions without a specific date.
- An event on several dates becomes one item per date shown on the page.
- If the page contains no qualifying events, return []."""


TOOL = {
    "name": "submit_events",
    "description": "Submit the events found on the page (an empty list if none qualify).",
    "input_schema": {"type": "object", "required": ["events"], "properties": {"events": {"type": "array", "items": {
        "type": "object", "required": ["title", "start"],
        "properties": {
            "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": ["string", "null"]},
            "url": {"type": ["string", "null"]}, "price": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]}, "venue": {"type": ["string", "null"]},
            "city": {"type": ["string", "null"]}, "online": {"type": ["boolean", "null"]},
        }}}}},
}


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
                    html = browser.render_html(url) if page.get("render") else self.http.get(url).text
                except browser.BrowserUnavailable as exc:
                    log.warning("%s needs a browser: %s", url, exc)
                    continue
                except Exception as exc:
                    log.warning("%s: %s", url, exc)
                    continue
                # free path first: schema.org Event markup needs no LLM at all
                structured = [e for e in (event_from_jsonld(o, page["name"], url) for o in jsonld_objects(html) if is_event_type(o)) if e]
                if structured:
                    for ev in structured:
                        ev.venue = ev.venue or page.get("venue", "")
                        ev.area = ev.area or page.get("area", "Stockholm")
                        ev.category = ev.category or page.get("category", "")
                        if page.get("audience"):
                            ev.extra["audience_hint"] = page["audience"]
                        if self.in_window(ev.start) and not ev.online and held_in_stockholm(ev, strict=bool(page.get("city"))):
                            yield ev
                    continue
                text = page_text(html, url)
                if len(text) < 200:
                    log.warning("%s: almost no text (JS-rendered page?)", url)
                    continue
                key = f"llm:{url}:{hashlib.sha1(text.encode()).hexdigest()[:12]}"
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
            model=MODEL, max_tokens=8000,
            system=PROMPT.format(today=today.isoformat(), start=self.start.date().isoformat(), end=self.end.date().isoformat())
            + (f"\nThis page lists events from many places: only return events held in {page['city']}." if page.get("city") else ""),
            tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
            messages=[{"role": "user", "content": f"Page URL: {url}\n\n{text}"}],
        )
        usage.record("pages", getattr(msg, "usage", None))
        items = next((b.input.get("events", []) for b in msg.content if b.type == "tool_use"), [])
        return [e for e in (self._to_event(i, url, page) for i in items if isinstance(i, dict)) if e]

    @staticmethod
    def _to_event(i: dict, page_url: str, page: dict) -> Event | None:
        start, known = parse_dt(i.get("start"))
        title = clean_text(i.get("title"))
        if not start or not title or i.get("online"):
            return None
        city = (i.get("city") or "").strip()
        if page.get("city") and not city:              # a multi-city page: no stated city means we cannot trust it
            return None
        if city and city.lower() not in CITIES:       # held somewhere else (Västerås, Warsaw, Helsinki...)
            return None
        if re.search(r"\b(online|zoom|webinar|ms teams)\b", i.get("venue") or "", re.I):
            return None
        end, _ = parse_dt(i.get("end"))
        link = i.get("url") or page_url
        price = (i.get("price") or "").strip()
        return Event(
            source=page["name"], source_id=f"{link}|{start.isoformat()}", title=title, start=start, end=end,
            time_known=known, url=link, description=clean_text(i.get("description"), 400),
            venue=i.get("venue") or page.get("venue", ""), area=city or page.get("area", "Stockholm"), category=page.get("category", ""),
            extra={"audience_hint": page["audience"]} if page.get("audience") else {},
            price_text="Free" if price.lower() in ("free", "gratis", "fri entré") else price,
            is_free=True if price.lower() in ("free", "gratis", "fri entré") else None,
        )
