"""Luma (lu.ma / luma.com): the Stockholm Discover page plus the calendars of the organisers behind it.

Discover only lists ~25 featured events; most startup and professional events live on organiser calendars
(Nutty Ventures, Epicenter, Norrsken...). We follow every calendar that shows up on Discover and any calendar
named in the config. All of this is free (plain HTTP).
"""
from __future__ import annotations

import logging

from ..geo import held_in_stockholm
from ..models import Event
from ..parse import clean_text, next_data, parse_dt
from .base import Collector

log = logging.getLogger(__name__)

API = "https://api.lu.ma/discover/get-paginated-events"
CAL_API = "https://api.lu.ma/calendar/get-items"


class Luma(Collector):
    name = "luma"
    priority = 60

    def _place_id(self):
        h = self.http.get("https://lu.ma/stockholm").text
        return next_data(h)["props"]["pageProps"]["initialData"]["data"]["place"]["api_id"]

    def fetch(self):
        place = self._place_id()
        cursor, seen, calendars = None, set(), {}
        for _ in range(self.cfg.get("max_pages", 30)):
            params = {"discover_place_api_id": place, "pagination_limit": 50}
            if cursor:
                params["pagination_cursor"] = cursor
            data = self.http.get(API, params=params).json()
            new = 0
            for ent in data.get("entries", []):
                cal = ent.get("calendar") or {}
                if cal.get("api_id"):
                    calendars[cal["api_id"]] = cal.get("name") or ""
                ev = self._to_event(ent)
                if ev and ev.source_id not in seen:
                    seen.add(ev.source_id)
                    new += 1
                    yield ev
            cursor = data.get("next_cursor")
            if not cursor or (not data.get("has_more") and not new):
                break

        for slug in self.cfg.get("calendars", []):             # organisers named in the config
            cid = self._resolve_calendar(slug)
            if cid:
                calendars.setdefault(cid, slug)
        followed = 0
        for cid, name in calendars.items():
            try:
                for ent in self._calendar_entries(cid):
                    ev = self._to_event(ent, strict=True)
                    if ev and ev.source_id not in seen:
                        seen.add(ev.source_id)
                        yield ev
                followed += 1
            except Exception as exc:
                log.warning("luma calendar %s (%s): %s", cid, name, exc)
        log.info("luma: followed %d calendars", followed)

    def _resolve_calendar(self, slug: str) -> str | None:
        try:
            nd = next_data(self.http.get(f"https://lu.ma/{slug}").text)
            return nd["props"]["pageProps"]["initialData"]["data"]["calendar"]["api_id"]
        except Exception as exc:
            log.warning("luma calendar slug %r could not be resolved: %s", slug, exc)
            return None

    def _calendar_entries(self, calendar_id: str):
        cursor = None
        for _ in range(5):
            params = {"calendar_api_id": calendar_id, "period": "future", "pagination_limit": 50}
            if cursor:
                params["pagination_cursor"] = cursor
            data = self.http.get(CAL_API, params=params).json()
            yield from data.get("entries", [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break

    def _to_event(self, ent: dict, strict: bool = False) -> Event | None:
        ev = ent["event"]
        if ev.get("location_type") == "online" or ev.get("visibility") != "public":
            return None
        start, _ = parse_dt(ev["start_at"])
        end, _ = parse_dt(ev.get("end_at"))
        if not start or not self.in_window(start):
            return None
        geo = ev.get("geo_address_info") or {}
        ti = ent.get("ticket_info") or {}
        coord = ev.get("coordinate") or {}
        out = Event(
            source=self.name, source_id=ev["api_id"], title=clean_text(ev["name"]), start=start, end=end,
            url=f"https://lu.ma/{ev['url']}", venue=geo.get("address", ""),
            address=geo.get("short_address", ""), area=geo.get("city", ""),
            lat=coord.get("latitude"), lon=coord.get("longitude"),
            is_free=ti.get("is_free"), price_text="Free" if ti.get("is_free") else "",
            image_url=ev.get("cover_url", ""), extra={"host": (ent.get("calendar") or {}).get("name", "")},
        )
        # organiser calendars can hold events in other cities: keep only Greater Stockholm
        if strict and not held_in_stockholm(out, strict=True):
            return None
        return out
