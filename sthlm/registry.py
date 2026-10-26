from .collectors.eventbrite import Eventbrite
from .collectors.jsonld_pages import JsonLdPages
from .collectors.llm_pages import LlmPages
from .collectors.luma import Luma
from .collectors.sitemap_jsonld import SitemapJsonLd
from .collectors.ticketmaster import Ticketmaster
from .collectors.tickster import Tickster
from .collectors.visitstockholm import VisitStockholm

COLLECTORS = {c.name: c for c in (Eventbrite, Luma, Ticketmaster, Tickster, VisitStockholm)}
GENERIC = {"jsonld_pages": JsonLdPages, "sitemap_jsonld": SitemapJsonLd, "llm_pages": LlmPages}


def priorities() -> dict[str, int]:
    return {c.name: c.priority for c in COLLECTORS.values()} | {"stockholmlive": 55, "sodrateatern": 65}
