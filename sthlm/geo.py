"""Greater-Stockholm filtering and neighbourhood labelling (no external geocoder needed)."""
from __future__ import annotations

import math

from .models import Event

CENTER = (59.3293, 18.0686)
MAX_KM = 40

# name -> (lat, lon); nearest centroid wins. Good enough for hashtags like #Södermalm.
DISTRICTS = {
    "City": (59.3326, 18.0649), "Gamla Stan": (59.3250, 18.0711), "Södermalm": (59.3150, 18.0710),
    "Östermalm": (59.3380, 18.0900), "Vasastan": (59.3450, 18.0500), "Kungsholmen": (59.3330, 18.0350),
    "Djurgården": (59.3260, 18.1150), "Norrmalm": (59.3400, 18.0620), "Hammarby Sjöstad": (59.3040, 18.1030),
    "Bromma": (59.3380, 17.9400), "Solna": (59.3600, 18.0000), "Hagastaden": (59.3480, 18.0330),
    "Globen / Johanneshov": (59.2940, 18.0830), "Nacka": (59.3100, 18.1650), "Kista": (59.4030, 17.9450),
    "Sundbyberg": (59.3610, 17.9710), "Lidingö": (59.3640, 18.1340), "Älvsjö": (59.2780, 18.0120),
    "Täby": (59.4430, 18.0690), "Huddinge": (59.2370, 17.9810), "Hägersten": (59.2950, 17.9650),
    "Årsta": (59.2980, 18.0470), "Södertälje": (59.1950, 17.6260),
}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[1] - b[1]) * math.cos(math.radians(a[0])) * 111.3
    dy = (a[0] - b[0]) * 111.3
    return math.hypot(dx, dy)


def district(lat: float, lon: float) -> str:
    return min(DISTRICTS, key=lambda d: km((lat, lon), DISTRICTS[d]))


def in_stockholm(ev: Event) -> bool:
    if ev.lat is not None and ev.lon is not None:
        return km((ev.lat, ev.lon), CENTER) <= MAX_KM
    # no coordinates: trust the source unless it names a city that is clearly elsewhere
    place = f"{ev.area} {ev.address} {ev.venue}".lower()
    elsewhere = ("göteborg", "malmö", "norrköping", "uppsala", "västerås", "örebro", "linköping", "gothenburg",
                 "malmo", "helsingborg", "jönköping", "umeå", "lund", "halmstad", "kalmar", "borås", "eskilstuna")
    return not any(c in place for c in elsewhere)


def label_area(ev: Event) -> None:
    if ev.lat is not None and ev.lon is not None:
        ev.area = district(ev.lat, ev.lon)
