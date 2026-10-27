from .collectors.discovery import Discovery
from .collectors.eventbrite import Eventbrite
from .collectors.ics_feeds import IcsFeeds
from .collectors.jsonld_pages import JsonLdPages
from .collectors.llm_pages import LlmPages
from .collectors.luma import Luma
from .collectors.meetup import Meetup
from .collectors.sitemap_jsonld import SitemapJsonLd
from .collectors.ticketmaster import Ticketmaster
from .collectors.tickster import Tickster
from .collectors.visitstockholm import VisitStockholm

COLLECTORS = {c.name: c for c in (Eventbrite, Luma, Meetup, Ticketmaster, Tickster, VisitStockholm, Discovery)}
GENERIC = {"ics_feeds": IcsFeeds, "jsonld_pages": JsonLdPages, "sitemap_jsonld": SitemapJsonLd, "llm_pages": LlmPages}


def priorities() -> dict[str, int]:
    return {c.name: c.priority for c in COLLECTORS.values()} | {"stockholmlive": 55, "sodrateatern": 65}
