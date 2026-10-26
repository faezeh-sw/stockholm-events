"""Raw events in the DB -> clean, merged, enriched list ready to render."""
from __future__ import annotations

import logging
import re

from .dedupe import Merged, merge
from .enrich import make_enricher
from .geo import in_stockholm, label_area
from .models import Event
from .registry import priorities

log = logging.getLogger(__name__)

# Commercial, permanently recurring tourist products: not worth a daily slot, shown in their own section.
TOURIST = re.compile(r"pub crawl|scavenger hunt|escape game|walking tour|guided tour|sightseeing|archipelago cruise|"
                     r"stockholm: .*(tour|cruise|entry)|nightlife tour|club crawl|bar crawl|city tour|bus tour|boat tour|ghost walk|segway", re.I)


def keep(ev: Event) -> bool:
    return not ev.online and in_stockholm(ev) and bool(ev.title.strip())


def build(store, since, until, enrich: bool = True) -> list[Merged]:
    events = [e for e in store.load_events(since, until) if keep(e)]
    for e in events:
        label_area(e)
        if TOURIST.search(e.title):
            e.extra["tourist"] = True
    merged = merge(events, priorities())
    log.info("catalog: %d raw -> %d unique", len(events), len(merged))
    if enrich:
        make_enricher().enrich([m.event for m in merged], store)
    else:
        from .enrich import RuleEnricher
        RuleEnricher().enrich([m.event for m in merged], store)
    merged = [m for m in merged if not m.event.extra.get("skip")]
    for m in merged:
        m.event.extra["n_sources"] = len({s for s, _ in m.sources})
        if m.event.extra["n_sources"] > 1:
            m.event.extra["score"] = min(10, m.event.extra.get("score", 3) + 0.7)
        if m.event.extra.get("tourist"):
            m.event.extra["score"] = min(m.event.extra.get("score", 3), 2)
    return merged
