import re, sys, json, requests
sys.path.insert(0, ".")
from sthlm.parse import jsonld_objects, is_event_type
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/1.0)"}
def get(u):
    return requests.get(u, headers=UA, timeout=25)
def sitemaps(dom):
    out = []
    try:
        for l in get(f"https://{dom}/robots.txt").text.splitlines():
            if l.lower().startswith("sitemap:"): out.append(l.split(":",1)[1].strip())
    except Exception as e: pass
    return out or [f"https://{dom}/sitemap.xml"]
def locs(u, depth=0):
    try: t = get(u).text
    except Exception as e: return []
    ls = re.findall(r"<loc>\s*(.*?)\s*</loc>", t)
    if "<sitemapindex" in t and depth < 1:
        res = []
        for s in ls[:60]:
            if re.search(r"event|evenemang|program|show|konsert|calendar|kalender|arr", s, re.I) or len(ls) < 8:
                res += locs(s, depth+1)
        return res
    return ls
for dom in sys.argv[1:]:
    ss = sitemaps(dom)
    urls = []
    for s in ss[:6]: urls += locs(s)
    ev = [u for u in urls if re.search(r"/(event|events|evenemang|program|show|konsert|kalender|calendar|e|arrangemang|forestallning|performance|biljetter)/", u, re.I)]
    print(f"{dom}: sitemaps={len(ss)} urls={len(urls)} eventlike={len(ev)}  sample={ev[:1]}")
    ok = 0
    for u in (ev[:3] if ev else urls[-2:]):
        try:
            h = get(u).text
            n = sum(1 for o in jsonld_objects(h) if is_event_type(o))
            ok += n > 0
            print("   ", n, u[:100])
        except Exception as e: print("    err", str(e)[:50])
