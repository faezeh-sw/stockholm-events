"""iCal (.ics) feeds: the most precise free source there is. No LLM involved.

config: feeds: [{name, url, audience, category, city, venue}]
`city` (optional) keeps only events whose LOCATION/GEO is in Greater Stockholm (for feeds that cover several cities).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..geo import held_in_stockholm
from ..models import Event, TZ
from ..parse import clean_text
from .base import Collector

log = logging.getLogger(__name__)


def unfold(text: str) -> list[str]:
    """RFC 5545: a line starting with a space or tab continues the previous one."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def unescape(v: str) -> str:
    return (v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def parse_dt(value: str, params: dict) -> tuple[datetime | None, bool]:
    """(aware datetime in Stockholm, time_known)."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            d = datetime.strptime(value[:8], "%Y%m%d")
            return d.replace(tzinfo=TZ), False
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ), True
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
        tz = ZoneInfo(params["TZID"]) if params.get("TZID") else TZ
        return dt.replace(tzinfo=tz).astimezone(TZ), True
    except (ValueError, KeyError, Exception):
        return None, False


def parse_ics(text: str) -> list[dict]:
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, _, value = line.partition(":")
            name, *plist = head.split(";")
            params = dict(p.split("=", 1) for p in plist if "=" in p)
            cur[name.upper()] = (value, params)
    return events


class IcsFeeds(Collector):
    name = "ics_feeds"
    priority = 57

    def fetch(self):
        for feed in self.cfg["feeds"]:
            try:
                text = self.http.get(feed["url"]).text
            except Exception as exc:
                log.warning("%s: %s", feed["url"], exc)
                continue
            for raw in parse_ics(text):
                ev = self._to_event(raw, feed)
                if ev and self.in_window(ev.start) and held_in_stockholm(ev, strict=bool(feed.get("city"))):
                    yield ev

    @staticmethod
    def _to_event(raw: dict, feed: dict) -> Event | None:
        if raw.get("STATUS", ("",))[0].upper() == "CANCELLED":
            return None
        start, known = parse_dt(*raw["DTSTART"]) if "DTSTART" in raw else (None, False)
        title = clean_text(unescape(raw.get("SUMMARY", ("",))[0]))
        if not start or not title:
            return None
        end, _ = parse_dt(*raw["DTEND"]) if "DTEND" in raw else (None, False)
        if end and not known:                       # all-day events: DTEND is exclusive
            end = None
        location = unescape(raw.get("LOCATION", ("",))[0])
        lat = lon = None
        if "GEO" in raw:
            try:
                lat, lon = (float(x) for x in raw["GEO"][0].split(";"))
            except ValueError:
                pass
        url = unescape(raw.get("URL", ("",))[0]) or feed["url"]
        uid = raw.get("UID", (url,))[0]
        if re.search(r"\b(online|zoom|webinar|teams)\b", location, re.I) and not re.search(r"stockholm", location, re.I):
            return None
        parts = [p.strip() for p in location.split(",") if p.strip()]
        return Event(
            source=feed["name"], source_id=f"{uid}|{start.isoformat()}", title=title, start=start, end=end,
            time_known=known, url=url, description=clean_text(unescape(raw.get("DESCRIPTION", ("",))[0]), 800),
            venue=feed.get("venue") or (parts[0] if parts else ""), address=location, area=parts[-1] if len(parts) > 1 else "",
            lat=lat, lon=lon, category=feed.get("category", ""),
            extra={"audience_hint": feed["audience"]} if feed.get("audience") else {},
        )
