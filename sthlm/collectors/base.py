from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from ..http import Http
from ..models import Event
from ..parse import clean_text, parse_dt

log = logging.getLogger(__name__)


class Collector:
    """A source of events. Subclasses implement `fetch`."""

    name = "base"
    priority = 50           # higher wins when merging duplicates (richer / more official data)

    def __init__(self, cfg: dict, http: Http, window: tuple[datetime, datetime], known_ids: set[str], store=None):
        self.cfg = cfg
        self.http = http
        self.start, self.end = window
        self.known_ids = known_ids
        self.store = store

    def fetch(self) -> Iterable[Event]:  # pragma: no cover
        raise NotImplementedError

    def in_window(self, dt: datetime) -> bool:
        return self.start <= dt <= self.end


def event_from_jsonld(o: dict, source: str, default_url: str = "") -> Event | None:
    """Convert a schema.org Event object to our Event, or None if unusable."""
    name = clean_text(o.get("name"))
    start, known = parse_dt(o.get("startDate"))
    if not name or not start:
        return None
    end, _ = parse_dt(o.get("endDate"))
    url = o.get("url") or default_url
    if isinstance(url, list):
        url = url[0]

    loc = o.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if not isinstance(loc, dict):
        loc = {"name": str(loc)}
    mode = str(o.get("eventAttendanceMode", ""))
    online = ("Online" in mode and "Offline" not in mode) or loc.get("@type") == "VirtualLocation"
    addr = loc.get("address", {})
    if isinstance(addr, str):
        addr = {"streetAddress": addr}
    street = addr.get("streetAddress", "")
    locality = addr.get("addressLocality", "")
    geo = loc.get("geo", {}) or {}
    try:
        lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
    except (TypeError, ValueError):
        lat = lon = None

    venue = clean_text(loc.get("name"))
    if venue and venue == street:      # Eventbrite puts the street in "name"
        venue = ""

    offers = o.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    price_text, is_free = "", None
    prices = []
    for of in offers or []:
        try:
            prices.append(float(str(of.get("price", of.get("lowPrice", ""))).replace(",", ".")))
        except ValueError:
            pass
    if prices:
        lo, hi = min(prices), max(prices)
        is_free = hi == 0
        cur = (offers[0].get("priceCurrency") or "SEK").replace("SEK", "kr")
        price_text = "Free" if is_free else (f"from {lo:g} {cur}" if hi != lo else f"{lo:g} {cur}")

    image = o.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    if isinstance(image, dict):
        image = image.get("url", "")

    status = str(o.get("eventStatus", ""))
    sid = o.get("@id") or url or f"{name}|{start.isoformat()}"
    return Event(
        source=source, source_id=str(sid), title=name, start=start, end=end, time_known=known,
        url=url or default_url, description=clean_text(o.get("description"), 1200),
        venue=venue, address=", ".join(x for x in (street, locality) if x), area=locality,
        lat=lat, lon=lon, price_text=price_text, is_free=is_free, image_url=image or "",
        online=bool(online), cancelled="Cancelled" in status,
    )
