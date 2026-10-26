import re, json, requests, sys
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/0.1)"}
def nd(u):
    h = requests.get(u, headers=UA, timeout=20).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1)) if m else None
def walk(o, path="", depth=0, maxd=6):
    if depth>maxd: return
    if isinstance(o, dict):
        for k,v in o.items():
            p=f"{path}.{k}"
            if isinstance(v,(list,dict)): print(p, type(v).__name__, len(v)); walk(v,p,depth+1,maxd)
    elif isinstance(o, list) and o:
        walk(o[0], path+"[0]", depth+1, maxd)
u=sys.argv[1]
d=nd(u)
walk(d)
