from __future__ import annotations

from ..models import Event
from ..parse import clean_text, next_data, parse_dt
from .base import Collector

API = "https://api.lu.ma/discover/get-paginated-events"


class Luma(Collector):
    name = "luma"
    priority = 60

    def _place_id(self):
        h = self.http.get("https://lu.ma/stockholm").text
        return next_data(h)["props"]["pageProps"]["initialData"]["data"]["place"]["api_id"]

    def fetch(self):
        place = self._place_id()
        cursor, seen = None, set()
        for _ in range(self.cfg.get("max_pages", 30)):
            params = {"discover_place_api_id": place, "pagination_limit": 50}
            if cursor:
                params["pagination_cursor"] = cursor
            data = self.http.get(API, params=params).json()
            new = 0
            for ent in data.get("entries", []):
                ev = ent["event"]
                if ev["api_id"] in seen:
                    continue
                seen.add(ev["api_id"])
                new += 1
                if ev.get("location_type") == "online" or ev.get("visibility") != "public":
                    continue
                start, _ = parse_dt(ev["start_at"])
                end, _ = parse_dt(ev.get("end_at"))
                if not start or not self.in_window(start):
                    continue
                geo = ev.get("geo_address_info") or {}
                ti = ent.get("ticket_info") or {}
                coord = ev.get("coordinate") or {}
                yield Event(
                    source=self.name, source_id=ev["api_id"], title=clean_text(ev["name"]), start=start, end=end,
                    url=f"https://lu.ma/{ev['url']}", venue=geo.get("address", ""),
                    address=geo.get("short_address", ""), area=geo.get("city", ""),
                    lat=coord.get("latitude"), lon=coord.get("longitude"),
                    is_free=ti.get("is_free"), price_text="Free" if ti.get("is_free") else "",
                    image_url=ev.get("cover_url", ""), extra={"host": (ent.get("calendar") or {}).get("name", "")},
                )
            cursor = data.get("next_cursor")
            if not cursor or (not data.get("has_more") and not new):
                break
