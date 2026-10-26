from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Stockholm")

CATEGORIES = [
    "music", "nightlife", "theatre", "art", "film", "food", "family",
    "sports", "tech", "business", "community", "wellness", "festival",
    "market", "talk", "other",
]


@dataclass
class Event:
    source: str
    source_id: str
    title: str
    start: datetime                      # tz-aware
    url: str
    end: datetime | None = None
    time_known: bool = True              # False when only the date is known
    description: str = ""
    venue: str = ""
    address: str = ""
    area: str = ""
    lat: float | None = None
    lon: float | None = None
    price_text: str = ""
    is_free: bool | None = None
    image_url: str = ""
    category: str = ""
    lang: str = ""                       # language the event is held in, if known
    online: bool = False
    cancelled: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.source_id}".encode()).hexdigest()[:16]

    @property
    def local_start(self) -> datetime:
        return self.start.astimezone(TZ)

    @property
    def local_date(self):
        return self.local_start.date()

    @staticmethod
    def from_row(r: dict) -> "Event":
        from .parse import parse_dt
        start, _ = parse_dt(r["start"])
        end, _ = parse_dt(r["end"]) if r.get("end") else (None, False)
        extra = r.get("extra") or {}
        if isinstance(extra, str):
            import json
            extra = json.loads(extra)
        return Event(
            source=r["source"], source_id=r["source_id"], title=r["title"], start=start, end=end, url=r["url"],
            time_known=bool(r["time_known"]), description=r.get("description") or "", venue=r.get("venue") or "",
            address=r.get("address") or "", area=r.get("area") or "", lat=r.get("lat"), lon=r.get("lon"),
            price_text=r.get("price_text") or "", is_free=None if r.get("is_free") is None else bool(r["is_free"]),
            image_url=r.get("image_url") or "", category=r.get("category") or "", lang=r.get("lang") or "",
            online=bool(r.get("online")), cancelled=bool(r.get("cancelled")), extra=extra,
        )

    def to_row(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["start"] = self.start.astimezone(timezone.utc).isoformat()
        d["end"] = self.end.astimezone(timezone.utc).isoformat() if self.end else None
        return d
