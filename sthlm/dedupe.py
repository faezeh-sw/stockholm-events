"""Merge the same real-world event reported by several sources."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .models import Event

_NOISE = re.compile(r"\b(live|tickets?|biljetter|konsert|concert|stockholm|sthlm|presents?|2026|2027)\b")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NOISE.sub(" ", s)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def _km(a: Event, b: Event) -> float | None:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return None
    dx = (a.lon - b.lon) * math.cos(math.radians(a.lat)) * 111.3
    dy = (a.lat - b.lat) * 111.3
    return math.hypot(dx, dy)


def same_event(a: Event, b: Event, priority: dict[str, int]) -> bool:
    if a.local_date != b.local_date:
        return False
    ta, tb = norm(a.title), norm(b.title)
    if not ta or not tb:
        return False
    sim = max(fuzz.token_set_ratio(ta, tb), fuzz.ratio(ta, tb))
    if a.time_known and b.time_known and abs((a.start - b.start).total_seconds()) > 3 * 3600:
        return False        # same title, same day, but a matinee vs an evening show
    if sim >= 96:
        return True
    if sim < 82:
        return False
    # moderately similar titles: require the place to agree too
    d = _km(a, b)
    if d is not None:
        return d < 0.35
    va, vb = norm(a.venue), norm(b.venue)
    return bool(va and vb and fuzz.token_set_ratio(va, vb) >= 85)


@dataclass
class Merged:
    event: Event
    sources: list[tuple[str, str]] = field(default_factory=list)   # (source, url)


def merge(events: list[Event], priority: dict[str, int]) -> list[Merged]:
    """Cluster duplicates (blocked by local date) and return one richer event per cluster."""
    by_day: dict = defaultdict(list)
    for e in events:
        by_day[e.local_date].append(e)

    out: list[Merged] = []
    for day_events in by_day.values():
        parent = list(range(len(day_events)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(day_events)):
            for j in range(i + 1, len(day_events)):
                if find(i) != find(j) and same_event(day_events[i], day_events[j], priority):
                    parent[find(j)] = find(i)
        groups = defaultdict(list)
        for i, e in enumerate(day_events):
            groups[find(i)].append(e)
        for g in groups.values():
            g.sort(key=lambda e: -priority.get(e.source, 50))
            best = _combine(g)
            out.append(Merged(best, [(e.source, e.url) for e in g]))
    out.sort(key=lambda m: m.event.start)
    return out


def _combine(group: list[Event]) -> Event:
    """Take the highest-priority record and fill its gaps from the others."""
    base = group[0]
    for other in group[1:]:
        for f in ("description", "venue", "address", "area", "price_text", "image_url", "category", "lang"):
            if not getattr(base, f) and getattr(other, f):
                setattr(base, f, getattr(other, f))
        if base.lat is None and other.lat is not None:
            base.lat, base.lon = other.lat, other.lon
        if base.is_free is None:
            base.is_free = other.is_free
        if not base.time_known and other.time_known:
            base.start, base.time_known = other.start, True
        if len(other.description) > len(base.description):
            base.description = other.description
        base.cancelled = base.cancelled or other.cancelled
        if other.extra.get("audience_hint") and not base.extra.get("audience_hint"):
            base.extra["audience_hint"] = other.extra["audience_hint"]
    return base
