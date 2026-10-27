"""Find an organiser's events page and say how it can be read.

Usage:  python tools/find_events_page.py https://www.example.se [https://other.se ...]
Costs nothing (plain HTTP). Prints, per site, the best candidate page and whether it can be read for free
(schema.org Event JSON-LD, iCal) or needs the LLM reader, plus a ready-to-paste config line.
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

sys.path.insert(0, ".")
from sthlm.collectors.llm_pages import page_text
from sthlm.parse import is_event_type, jsonld_objects

UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/1.0)"}
PATHS = ["/events", "/event", "/evenemang", "/kalender", "/calendar", "/program", "/en/events", "/sv/evenemang",
         "/seminarier", "/aktuellt/evenemang", "/whats-on", "/agenda", "/kommande-event", "/event-calendar",
         "/en/calendar", "/sv/kalender", "/evenemang-och-seminarier", "/webinars", "/en/news-and-events"]
LINK_WORDS = re.compile(r"event|evenemang|calendar|kalender|program|seminar|webinar|konferens|conference|agenda|"
                        r"kommande|upcoming|whats-on|mote|meetup", re.I)
DATE = re.compile(r"\b(?:\d{1,2}\s*(?:nov|dec|jan)\w*|(?:nov|dec|jan)\w*\s*\d{1,2}|2026-1[12]-\d\d|2026-0?1-\d\d|\d{1,2}/1[12])\b", re.I)


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        return r if r.status_code == 200 and "text/html" in r.headers.get("content-type", "") else None
    except Exception:
        return None


def score(url):
    r = get(url)
    if not r:
        return None
    ld = sum(1 for o in jsonld_objects(r.text) if is_event_type(o))
    ics = bool(re.search(r"\.ics|webcal:", r.text))
    text = page_text(r.text, r.url)
    return {"url": r.url, "jsonld": ld, "ics": ics, "chars": len(text), "dates": len(DATE.findall(text))}


def candidates(site):
    root = get(site)
    urls = []
    if root:
        for a in re.findall(r'href="([^"#]+)"[^>]*>(.*?)</a>', root.text, re.S | re.I):
            href, label = urljoin(root.url, a[0]), re.sub(r"<[^>]+>", " ", a[1])
            if urlparse(href).netloc.removeprefix("www.") == urlparse(root.url).netloc.removeprefix("www.") \
                    and (LINK_WORDS.search(label) or LINK_WORDS.search(urlparse(href).path)):
                urls.append(href)
    base = (root.url if root else site).rstrip("/")
    origin = "{0.scheme}://{0.netloc}".format(urlparse(base))
    urls += [origin + p for p in PATHS]
    seen, out = set(), []
    for u in urls:
        k = u.rstrip("/")
        if k not in seen:
            seen.add(k)
            out.append(u)
    return out[:14]


def inspect(site):
    best = None
    for u in candidates(site):
        s = score(u)
        if not s:
            continue
        s["rank"] = s["jsonld"] * 50 + s["dates"] * 2 + (10 if s["ics"] else 0)
        if not best or s["rank"] > best["rank"]:
            best = s
    return site, best


if __name__ == "__main__":
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(inspect, sys.argv[1:]))
    for site, b in sorted(results, key=lambda x: -(x[1]["rank"] if x[1] else -1)):
        if not b:
            print(f"--  no events page found      {site}")
            continue
        how = "FREE (JSON-LD)" if b["jsonld"] else ("iCal link" if b["ics"] else ("LLM" if b["dates"] >= 3 else "weak"))
        print(f"{how:<15} ld={b['jsonld']:<3} dates={b['dates']:<3} chars={b['chars']:<6} {b['url']}")
