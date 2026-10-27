"""Turn raw events into channel-ready English content: translation, short summary, category, ranking.

LLMEnricher uses the Anthropic API (cached per event text, so each event is paid for once).
RuleEnricher is the offline fallback: keyword categories, no translation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from . import usage
from .models import CATEGORIES, Event

log = logging.getLogger(__name__)

MODEL = os.environ.get("ENRICH_MODEL", "claude-haiku-5-5")
BATCH = 12

SYSTEM = """You prepare event listings for an English-language Telegram channel about what's on in Stockholm, Sweden.
Readers are expats, students, tourists and locals who do not read Swedish.

For every event you receive, return:
- title_en: the title in natural English. Keep proper names (artists, venues, festivals, shows) untranslated; translate descriptive Swedish words. Fix SHOUTING CAPS. Remove clock times, dates, venue repeats and noise such as "Biljetter"/"Tickets"/"Admission" from the title (e.g. "Cinema: Arkipelag, 15:00" -> "Cinema: Arkipelag"). Max 90 chars.
- summary_en: one or two short factual sentences, max 200 chars in total, saying what the event is and what a visitor should know (genre, format, who it suits, what is included). No hype, no marketing language, no invented facts. Never comment on the listing itself or guess (no "the listing gives no details", "likely", "probably"): if the input is thin, write one short sentence stating only what is certain from the title and venue, and never restate the title as a sentence.
- category: exactly one of: {cats}
- language: the language the event is held in: "en", "sv", "both" (English and Swedish), "other", "none" (no spoken language involved: concerts, exhibitions, sports, dance, DJ nights) or "unknown" (only if it is truly impossible to tell). Decide from the title, description, venue and kind of event: an English title or description means "en"; a Swedish-only description for a talk, play, tour or workshop means "sv"
- cost: "free" only if the text states free entry (free, gratis, fri entré, 0 kr, kostnadsfritt); "paid" if a price or ticket sale is evident; otherwise "unknown". Never assume
- english_ok: true if a non-Swedish speaker can enjoy it (English-language, or language-independent), false if it needs Swedish
- score: integer 0-10 for how interesting it is to a general audience of newcomers (10 = major concert/festival/headline show, 5 = solid regular event, 1 = niche, routine or low-effort listing, recurring tourist-trap tour)
- is_event: false for things that are not a specific event: plain admission/entry tickets, gift cards, vouchers, parking, menus, or permanent attractions with no programme. true otherwise
- audience: "professional" for events whose main purpose is work or career: conferences, business/tech/startup talks and meetups, networking, job fairs, workshops for professionals, industry or academic seminars. "fun" for everything leisure: music, nightlife, theatre, film, art, food, sports, family, markets, social/hobby/language meetups, general-interest talks
- evergreen: true for ongoing exhibitions, long-running shows or daily attractions rather than a one-off occasion

Call submit_listings once with one object per input event (same "id" as the input)."""

TOOL = {
    "name": "submit_listings",
    "description": "Submit the enriched listings, one per input event.",
    "input_schema": {"type": "object", "required": ["events"], "properties": {"events": {"type": "array", "items": {
        "type": "object",
        "required": ["id", "title_en", "summary_en", "category", "language", "english_ok", "score", "evergreen", "is_event", "audience", "cost"],
        "properties": {
            "id": {"type": "integer"}, "title_en": {"type": "string"}, "summary_en": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "language": {"type": "string", "enum": ["en", "sv", "both", "other", "none", "unknown"]},
            "cost": {"type": "string", "enum": ["free", "paid", "unknown"]},
            "english_ok": {"type": "boolean"}, "score": {"type": "integer"}, "evergreen": {"type": "boolean"}, "is_event": {"type": "boolean"},
            "audience": {"type": "string", "enum": ["fun", "professional"]},
        }}}}},
}


def text_key(ev: Event) -> str:
    raw = f"v5|{ev.title}|{ev.description[:300]}|{ev.venue}"
    return hashlib.sha1(raw.encode()).hexdigest()


RULES = [
    ("music", r"concert|konsert|live|band|orkester|orchestra|jazz|dj |festival|opera|choir|kör|gig|quartet|symphon"),
    ("nightlife", r"club|klubb|party|pub crawl|nightlife|afterwork|disco|rave"),
    ("theatre", r"theat|teater|musical|dans|dance|ballet|comedy|stand-?up|show|revy|cirkus|circus"),
    ("art", r"exhibit|utställning|museum|museet|gallery|galleri|art |konst|photograph|fotograf"),
    ("film", r"film|cinema|bio\b|screening|premiere"),
    ("food", r"food|mat\b|wine|vin\b|beer|öl\b|whisky|tasting|dinner|brunch|restaurant|cooking|coffee|fika"),
    ("family", r"kids|barn|family|familj|children|sago|saga"),
    ("sports", r"match|hockey|football|fotboll|allsvenskan|shl|marathon|run\b|lopp|tennis|basket|bandy|innebandy|open\b"),
    ("tech", r"\bai\b|startup|tech|hackathon|developer|data|crypto|python|cloud|founders"),
    ("business", r"network|nätverk|summit|conference|konferens|workshop|business|leadership|career"),
    ("market", r"market|marknad|julmarknad|christmas|bazaar|loppis"),
    ("wellness", r"yoga|meditation|sauna|wellness|mindful|breathwork"),
    ("talk", r"lecture|föreläsning|talk|panel|seminar|book|bok|author"),
    ("community", r"meetup|social|language|språk|expat|friends|community|walk"),
]


def rule_category(ev: Event) -> str:
    text = f"{ev.title} {ev.venue} {ev.description[:200]}".lower()
    seg = ev.extra.get("segment", "").lower()
    if seg == "sports":
        return "sports"
    if seg == "music":
        return "music"
    if seg == "arts & theatre":
        return "theatre"
    for cat, pat in RULES:
        if re.search(pat, text):
            return cat
    return "other"


def base_score(ev: Event) -> float:
    s = 3.0
    s += 2.5 if ev.extra.get("curated") else 0
    s += 1.0 if ev.image_url else 0
    s += 0.5 if ev.time_known else 0
    s += 1.0 if len(ev.description) > 200 else 0
    s += 1.5 if ev.source in ("ticketmaster", "stockholmlive") else 0
    return min(s, 9.0)


class RuleEnricher:
    def enrich(self, events: list[Event], store) -> None:
        for ev in events:
            ev.extra.setdefault("title_en", ev.title)
            ev.extra.setdefault("summary_en", "")
            ev.category = ev.category or rule_category(ev)
            ev.extra["score"] = base_score(ev)
            ev.extra["audience"] = "professional" if ev.category in ("tech", "business") else "fun"
            ev.extra.setdefault("english_ok", True)


class LLMEnricher(RuleEnricher):
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()
        self.unresolved = 0          # events that could not be processed (API error, no credit...)
        self.last_error = ""

    def enrich(self, events: list[Event], store) -> None:
        super().enrich(events, store)
        todo = []
        for ev in events:
            cached = store.get_enrich(text_key(ev))
            if cached:
                self._apply(ev, cached)
            else:
                todo.append(ev)
        log.info("enrich: %d cached, %d to translate", len(events) - len(todo), len(todo))
        from concurrent.futures import ThreadPoolExecutor
        chunks = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

        def run(chunk):
            try:
                return self._call(chunk)
            except Exception as exc:
                self.last_error = str(exc)[:200]
                if len(chunk) == 1:
                    log.error("LLM enrichment failed for %r: %s", chunk[0].title, exc)
                    return [None]
                log.warning("LLM batch of %d failed (%s): retrying in halves", len(chunk), exc)
                mid = len(chunk) // 2
                return run(chunk[:mid]) + run(chunk[mid:])

        with ThreadPoolExecutor(6) as pool:        # API calls in parallel; SQLite writes stay on this thread
            for chunk, results in zip(chunks, pool.map(run, chunks)):
                for ev, res in zip(chunk, results):
                    if res is None:
                        self.unresolved += 1
                        continue
                    store.put_enrich(text_key(ev), res)
                    self._apply(ev, res)
                store.commit()
        self._deep(events, store)

    # --- second pass: read the event's own page when language or price is still unknown -----------
    def _deep(self, events: list[Event], store) -> None:
        import dataclasses
        from concurrent.futures import ThreadPoolExecutor
        from .collectors.llm_pages import page_text
        from .http import Http

        need = []
        for ev in events:
            # reading an event page costs tokens: only for the audience we care most about, and only for the language
            professional = (ev.extra.get("audience_hint") or ev.extra.get("audience")) == "professional"
            unknown_cost = not ev.price_text and not ev.is_free and ev.extra.get("cost") in (None, "unknown")
            if not (professional and (ev.lang in ("", "unknown") or unknown_cost)):
                continue
            key = text_key(ev) + "|deep"
            cached = store.get_enrich(key)
            if cached is not None:
                self._apply_deep(ev, cached)
            else:
                need.append((ev, key))
        if not need:
            return
        log.info("enrich: reading %d event pages for language/price", len(need))
        http = Http(delay=0.1)

        def fetch(item):
            try:
                return page_text(http.get(item[0].url).text, item[0].url)[:3000]
            except Exception as exc:
                log.debug("deep fetch failed %s: %s", item[0].url, exc)
                return ""

        with ThreadPoolExecutor(8) as pool:
            texts = list(pool.map(fetch, need))
        work = [(ev, key, dataclasses.replace(ev, description=t)) for (ev, key), t in zip(need, texts) if len(t) > 200][:150]
        for ev, key in ((ev, key) for (ev, key), t in zip(need, texts) if len(t) <= 200):
            store.put_enrich(key, {})                  # nothing readable (JS-only page): do not retry every day
        for i in range(0, len(work), 8):
            batch = work[i:i + 8]
            try:
                results = self._call([c for _, _, c in batch], desc_limit=3000)
            except Exception as exc:
                log.warning("deep enrichment batch failed: %s", exc)
                continue
            for (ev, key, _), res in zip(batch, results):
                if res is None:
                    continue
                keep = {k: res.get(k) for k in ("language", "cost", "summary_en")}
                store.put_enrich(key, keep)
                self._apply_deep(ev, keep)
            store.commit()
        store.commit()

    def _apply_deep(self, ev: Event, r: dict) -> None:
        if r.get("language") and r["language"] != "unknown":
            ev.lang = r["language"]
        if r.get("cost") in ("free", "paid"):
            ev.extra["cost"] = r["cost"]
        if r.get("summary_en") and len(ev.extra.get("summary_en", "")) < 40:
            ev.extra["summary_en"] = _shorten(r["summary_en"], 220)

    def _call(self, chunk: list[Event], desc_limit: int = 350) -> list[dict | None]:
        payload = [{
            "id": i, "title": ev.title, "description": ev.description[:desc_limit], "venue": ev.venue,
            "area": ev.area, "source": ev.source, "price": ev.price_text,
        } for i, ev in enumerate(chunk)]
        msg = self.client.messages.create(
            model=MODEL, max_tokens=6000,
            system=SYSTEM.format(cats=", ".join(CATEGORIES)),
            tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        usage.record("enrich", getattr(msg, "usage", None))
        data = next(b.input["events"] for b in msg.content if b.type == "tool_use")
        by_id = {d.get("id"): d for d in data if isinstance(d, dict)}
        return [by_id.get(i) for i in range(len(chunk))]

    @staticmethod
    def _apply(ev: Event, r: dict) -> None:
        ev.extra["title_en"] = (r.get("title_en") or ev.title)[:120]
        ev.extra["summary_en"] = _shorten(r.get("summary_en") or "", 220)
        if r.get("category") in CATEGORIES:
            ev.category = r["category"]
        ev.lang = r.get("language") or ev.lang
        ev.extra["english_ok"] = bool(r.get("english_ok", True))
        ev.extra["evergreen"] = bool(r.get("evergreen", False))
        ev.extra["skip"] = r.get("is_event", True) is False
        ev.extra["cost"] = r.get("cost", "unknown")
        if r.get("audience") in ("fun", "professional"):
            ev.extra["audience"] = r["audience"]
        try:
            ev.extra["score"] = float(r["score"])
        except (KeyError, TypeError, ValueError):
            pass


def _shorten(text: str, limit: int) -> str:
    """Cut at a sentence end if possible, else at a word, so descriptions never stop mid-sentence."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > limit * 0.5:
        return cut[:end + 1]
    return cut[:cut.rfind(" ")].rstrip(",;:- ") + "…"


def make_enricher():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMEnricher()
    log.warning("ANTHROPIC_API_KEY not set: using rule-based enrichment (no translation)")
    return RuleEnricher()
