"""Render events into Telegram HTML messages (<= 4096 chars each).

Layout: one block per day. Every message starts with a big day header (repeated, marked "continued", when a day
needs several messages). Inside a day events are grouped by category, each with a short description and price.
"""
from __future__ import annotations

import hashlib
import html
from datetime import datetime, timedelta
from itertools import groupby
from urllib.parse import quote_plus

from .dedupe import Merged
from .models import TZ, Event

LIMIT = 3900
RULE = "━━━━━━━━━━━━━━━━━━"

EMOJI = {
    "music": "🎵", "nightlife": "🪩", "theatre": "🎭", "art": "🖼", "film": "🎬", "food": "🍽", "family": "🧸",
    "sports": "🏟", "tech": "💻", "business": "🤝", "community": "👥", "wellness": "🧘", "festival": "🎪",
    "market": "🛍", "talk": "🎤", "other": "✨",
}
CAT_LABEL = {
    "music": "Music", "nightlife": "Nightlife", "theatre": "Theatre, comedy & dance", "art": "Art & exhibitions",
    "film": "Film", "food": "Food & drink", "family": "Family & kids", "sports": "Sports", "tech": "Tech",
    "business": "Business & networking", "community": "Community & social", "wellness": "Wellness",
    "festival": "Festivals", "market": "Markets", "talk": "Talks & books", "other": "More events",
}
CAT_ORDER = ["festival", "music", "theatre", "art", "film", "family", "food", "nightlife", "sports", "tech",
             "business", "talk", "community", "wellness", "market", "other"]
# Sources that sell tickets: when no price is known we say "tickets" rather than guessing.
TICKETED = {"tickster", "ticketmaster", "stockholmlive", "sodrateatern", "konserthuset", "dramaten", "debaser"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def map_url(ev: Event) -> str:
    if ev.lat is not None:
        q = f"{ev.lat},{ev.lon}"
    else:
        q = quote_plus(f"{ev.venue} {ev.address} Stockholm".strip())
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def when(ev: Event, with_date: bool = False) -> str:
    t = ev.local_start
    clock = t.strftime("%H:%M") if ev.time_known else "Time TBA"
    if ev.end and ev.time_known and ev.end.astimezone(TZ).date() == t.date() and ev.end > ev.start:
        clock += "–" + ev.end.astimezone(TZ).strftime("%H:%M")
    return f"{t.strftime('%a')} {t.day} {t.strftime('%b')}, {clock}" if with_date else clock


def is_free(ev: Event) -> bool:
    return bool(ev.is_free) or ev.price_text.lower() == "free"


LANG_LABEL = {
    "en": "🗣 English", "sv": "🗣 Swedish", "both": "🗣 English &amp; Swedish", "other": "🗣 Other language",
    "none": "🗣 No language needed", "unknown": "🗣 Language: see event page",
}


def cost_of(ev: Event, sources: set[str] = frozenset()) -> str:
    """'free' | 'paid' | 'unknown': trust structured data first, then the model's reading of the text."""
    if is_free(ev):
        return "free"
    if ev.price_text:
        return "paid"
    c = ev.extra.get("cost")
    if c in ("free", "paid"):
        return c
    return "paid" if (ev.source in TICKETED or sources & TICKETED) else "unknown"


def price_line(ev: Event, sources: set[str] = frozenset()) -> str:
    c = cost_of(ev, sources)
    if c == "free":
        return "🆓 <b>Free</b>"
    if c == "paid":
        return f"💰 <b>Paid</b> · {esc(ev.price_text)}" if ev.price_text else "💰 <b>Paid</b> · see link"
    return "💰 Price: see event page"


def language_line(ev: Event) -> str:
    return LANG_LABEL[ev.lang if ev.lang in LANG_LABEL else "unknown"]


def title_of(ev: Event) -> str:
    return ev.extra.get("title_en") or ev.title


def item(m: Merged, with_date: bool = False) -> str:
    ev = m.event
    lines = [f'<b><a href="{esc(ev.url)}">{esc(title_of(ev))}</a></b>']
    # Every listing has exactly the same four lines in the same order, whatever data the source gave us.
    summary = ev.extra.get("summary_en") or "See the event page for details."
    lines.append(f"<i>{esc(summary)}</i>")
    place = f'<a href="{map_url(ev)}">{esc(ev.venue or ev.address or "Stockholm")}</a>'
    if ev.area and ev.area.lower() not in (ev.venue or "").lower():
        place += f", {esc(ev.area)}"
    lines.append(f"🕒 {esc(when(ev, with_date))} · 📍 {place}")
    meta = f"{price_line(ev, {s for s, _ in m.sources})} · {language_line(ev)}"
    if ev.cancelled:
        meta += " · ❌ <b>CANCELLED</b>"
    lines.append(meta)
    return "\n".join(lines)


def day_header(d, today=None, cont: bool = False, n: int = 0, n_free: int = 0) -> str:
    """Just the weekday and date, repeated on every message of that day."""
    return f"{RULE}\n📅 <b>{d.strftime('%A').upper()}, {d.day} {d.strftime('%B').upper()}</b>\n{RULE}"


def _cat_heading(cat: str, cont: bool) -> str:
    return f"{EMOJI.get(cat, '✨')} <b>{esc(CAT_LABEL.get(cat, cat).upper())}</b>" + (" <i>(cont.)</i>" if cont else "")


def day_messages(d, today, day_ms: list[Merged], per_day: int, site_url: str = "") -> list[str]:
    """All messages for one day. Top `per_day` by score are shown, grouped by category, in time order."""
    ranked = sorted(day_ms, key=lambda m: -m.event.extra.get("score", 3))
    shown = ranked[:per_day]
    hidden = len(day_ms) - len(shown)
    n_free = sum(1 for m in day_ms if is_free(m.event))
    key = lambda m: CAT_ORDER.index(m.event.category) if m.event.category in CAT_ORDER else len(CAT_ORDER)
    shown.sort(key=lambda m: (key(m), not m.event.time_known, m.event.start))

    msgs: list[str] = []
    cur = day_header(d, today, False, len(day_ms), n_free)
    for cat_idx, grp in groupby(shown, key=key):
        cat = CAT_ORDER[cat_idx] if cat_idx < len(CAT_ORDER) else "other"
        first = True
        for m in grp:
            block = item(m)
            heading = _cat_heading(cat, cont=not first)
            piece = f"{heading}\n\n{block}" if first else block
            if len(cur) + 2 + len(piece) > LIMIT:
                msgs.append(cur)
                cur = day_header(d, today, True)
                piece = f"{_cat_heading(cat, cont=not first)}\n\n{block}" if not first else piece
            cur += "\n\n" + piece
            first = False
    if hidden:
        more = f"➕ <i>{hidden} more events on this day</i>"
        if site_url:
            more += f' — <a href="{esc(site_url)}">see all</a>'
        if len(cur) + 2 + len(more) > LIMIT:
            msgs.append(cur)
            cur = day_header(d, today, True)
        cur += "\n\n" + more
    msgs.append(cur)
    return msgs


def digest(merged: list[Merged], days: list, today, per_day: int, site_url: str = "") -> list[str]:
    out: list[str] = []
    for d in days:
        day_ms = [m for m in merged if m.event.local_date == d and not m.event.cancelled
                  and not m.event.extra.get("tourist") and not m.event.extra.get("ongoing_until")]
        if day_ms:
            out.extend(day_messages(d, today, day_ms, per_day, site_url))
    return out


def daily(merged: list[Merged], now: datetime, site_url: str = "") -> list[str]:
    today = now.astimezone(TZ).date()
    return digest(merged, [today, today + timedelta(days=1)], today, per_day=22, site_url=site_url)


def next_week_start(today):
    """The Monday of the coming week (a Monday run plans the week that starts 7 days later)."""
    return today + timedelta(days=7 - today.weekday())


FUN_PER_DAY = 25      # the Fun topic lists free events only; if a day still has more, the best-ranked 25 are shown


def weekly(merged: list[Merged], now: datetime, site_url: str = "", audience: str = "professional") -> list[str]:
    """Everything happening next Monday-Sunday: one opening line, then every day in full.

    Professional: every event, free or paid. Fun: free events only, best-ranked first when a day is crowded."""
    today = now.astimezone(TZ).date()
    mon = next_week_start(today)
    days = [mon + timedelta(days=i) for i in range(7)]
    if audience == "fun":
        merged = [m for m in merged if cost_of(m.event, {src for src, _ in m.sources}) == "free"]
    day_msgs = digest(merged, days, today, per_day=FUN_PER_DAY if audience == "fun" else 80, site_url=site_url)
    if not day_msgs:
        return []
    sun = days[-1]
    span = (f"{mon.day}–{sun.day} {mon.strftime('%B').upper()}" if mon.month == sun.month
            else f"{mon.day} {mon.strftime('%B').upper()} – {sun.day} {sun.strftime('%B').upper()}")
    if audience == "fun":
        intro = f"🗓 <b>FREE EVENTS · {span}</b>\n<i>Free things to do this week, day by day.</i>"
    else:
        intro = f"🗓 <b>WEEK AHEAD · {span}</b>\n<i>Every professional, career and networking event we found.</i>"
    return [intro] + day_msgs


LEGEND = """📖 <b>HOW TO READ OUR LISTINGS</b>

Every event is written exactly the same way, so you always know where to look:

<b>Event title</b> (tap to open the event page)
<i>One-line description of what it is</i>
🕒 <b>Time</b> · 📍 <b>Venue, area</b> (tap for the map)
🆓 <b>Free</b> or 💰 <b>Paid</b> · 🗣 <b>Language</b>

<b>Price</b>
🆓 Free · 💰 Paid with the price when we know it · "see link" or "see event page" when it is not published

<b>Language</b>
🗣 English · Swedish · English &amp; Swedish · Other language
🗣 No language needed (concerts, exhibitions, sports, club nights)
🗣 Language: see event page (we could not tell)

<b>What is listed where</b>
💼 Professional &amp; Career: every event we find, free or paid.
🎉 Fun &amp; Entertainment: free events only.

<b>How it is organised</b>
Every Monday we post the whole coming week, one day at a time. Inside each day events are grouped by category and sorted by time.

⚠️ Information is collected automatically from public sources. Times, prices and cancellations can change: always check the event page before you go."""


def legend() -> str:
    return LEGEND


def content_hash(msgs: list[str]) -> str:
    return hashlib.sha1("\x00".join(msgs).encode()).hexdigest()
