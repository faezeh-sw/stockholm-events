from __future__ import annotations

import os
from datetime import timezone

from ..models import Event
from ..parse import clean_text, parse_dt
from .base import Collector

API = "https://app.ticketmaster.com/discovery/v2/events.json"


class Ticketmaster(Collector):
    name = "ticketmaster"
    priority = 80

    def fetch(self):
        key = os.environ.get("TICKETMASTER_API_KEY")
        if not key:
            raise RuntimeError("TICKETMASTER_API_KEY not set (free key: developer.ticketmaster.com)")
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        params = {"apikey": key, "countryCode": "SE", "city": "Stockholm", "size": 200, "sort": "date,asc",
                  "startDateTime": self.start.astimezone(timezone.utc).strftime(fmt),
                  "endDateTime": self.end.astimezone(timezone.utc).strftime(fmt)}
        for page in range(0, 20):
            params["page"] = page
            data = self.http.get(API, params=params).json()
            for e in data.get("_embedded", {}).get("events", []):
                dates = e["dates"]["start"]
                start, known = parse_dt(dates.get("dateTime") or dates.get("localDate"))
                if not start:
                    continue
                known = known and not dates.get("noSpecificTime") and not dates.get("timeTBA")
                v = (e.get("_embedded", {}).get("venues") or [{}])[0]
                loc = v.get("location") or {}
                pr = (e.get("priceRanges") or [{}])[0]
                cls = (e.get("classifications") or [{}])[0]
                imgs = sorted(e.get("images", []), key=lambda i: -i.get("width", 0))
                price = f"from {pr['min']:g} {pr.get('currency', 'SEK')}".replace("SEK", "kr") if pr.get("min") else ""
                yield Event(
                    source=self.name, source_id=e["id"], title=clean_text(e["name"]), start=start, time_known=known,
                    url=e["url"], description=clean_text(e.get("info") or e.get("pleaseNote"), 800),
                    venue=v.get("name", ""), address=(v.get("address") or {}).get("line1", ""),
                    area=(v.get("city") or {}).get("name", ""),
                    lat=float(loc["latitude"]) if loc.get("latitude") else None,
                    lon=float(loc["longitude"]) if loc.get("longitude") else None,
                    price_text=price, image_url=imgs[0]["url"] if imgs else "",
                    cancelled=e["dates"].get("status", {}).get("code") == "cancelled",
                    extra={"segment": (cls.get("segment") or {}).get("name", ""),
                           "genre": (cls.get("genre") or {}).get("name", "")},
                )
            if page + 1 >= data.get("page", {}).get("totalPages", 0):
                break
