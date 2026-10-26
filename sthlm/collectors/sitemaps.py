from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def sitemap_urls(http, root: str, include: str | None = None, max_depth: int = 2) -> list[str]:
    """Collect <loc> URLs from a sitemap or sitemap index (or from robots.txt Sitemap: lines)."""
    if root.endswith("robots.txt"):
        roots = [l.split(":", 1)[1].strip() for l in http.get(root).text.splitlines() if l.lower().startswith("sitemap:")]
    else:
        roots = [root]
    inc = re.compile(include) if include else None
    out: list[str] = []

    def walk(u: str, depth: int):
        try:
            text = http.get(u).text
        except Exception as exc:
            log.warning("sitemap %s: %s", u, exc)
            return
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
        if "<sitemapindex" in text and depth < max_depth:
            for l in locs:
                walk(l, depth + 1)
        else:
            out.extend(l for l in locs if not inc or inc.search(l))

    for r in roots:
        walk(r, 0)
    return out
