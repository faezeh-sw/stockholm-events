import re, json, sys, requests
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/0.1; +https://t.me/)"}
URLS = sys.argv[1:] or """
https://www.visitstockholm.com/events/
https://kulturhusetstadsteatern.se/kalender
https://www.eventbrite.com/d/sweden--stockholm/events/
https://lu.ma/stockholm
https://www.meetup.com/find/?location=se--stockholm&source=EVENTS
https://www.operan.se/
https://www.konserthuset.se/program-och-biljetter/kalender/
https://www.fotografiska.com/sto/en/events/
https://ra.co/events/se/stockholm
https://www.dramaten.se/
https://debaser.se/
https://www.sodrateatern.com/
https://www.billetto.se/en/s/events-stockholm
https://www.tekniskamuseet.se/
https://www.skansen.se/en/calendar/
https://www.nobelprize.org/events/
https://www.tickster.com/en/events
https://stockholmlive.com/
https://www.stockholmsmassan.se/
https://www.kungligaslotten.se/
""".split()
def types(o, out):
    if isinstance(o, list):
        for x in o: types(x, out)
    elif isinstance(o, dict):
        t = o.get("@type")
        if t: out.append(t if isinstance(t,str) else ",".join(t))
        for v in o.values(): types(v, out)
for u in URLS:
    try:
        r = requests.get(u, headers=UA, timeout=20)
        h = r.text
        blocks = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, re.S)
        ts = []
        for b in blocks:
            try: types(json.loads(b), ts)
            except Exception: pass
        ev = sum(1 for t in ts if "Event" in t)
        ics = len(re.findall(r'\.ics|webcal:', h))
        nxt = "__NEXT_DATA__" in h
        print(f"{r.status_code} len={len(h):>7} ld={len(blocks)} Event={ev} ics={ics} next={nxt} {u}")
    except Exception as e:
        print("ERR", u, str(e)[:80])
