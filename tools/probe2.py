import sys, re, json, requests
sys.path.insert(0, ".")
from sthlm.parse import jsonld_objects, is_event_type
from sthlm.collectors.llm_pages import page_text
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/1.0)"}
C = {
 "devevents-conf": "https://dev.events/EU/SE/Stockholm",
 "devevents-tech": "https://dev.events/meetups/EU/SE/Stockholm/tech",
 "confs.tech": "https://raw.githubusercontent.com/tech-conferences/conference-data/main/conferences/2026/javascript.json",
 "meetup-find": "https://www.meetup.com/find/?location=se--Stockholm&source=EVENTS&dateRange=this-month",
 "meetup-tech": "https://www.meetup.com/find/?location=se--Stockholm&source=EVENTS&categoryId=546",
 "su-career": "https://www.su.se/english/education/careers/career-events",
 "kth-events": "https://www.kth.se/en/om/evenemang",
 "hhs-events": "https://www.hhs.se/en/events/",
 "ki-events": "https://ki.se/en/events",
 "amcham": "https://www.amcham.se/program",
 "chamber": "https://www.chamber.se/evenemang",
 "stockholmsmassan": "https://stockholmsmassan.se/en/events/",
 "kistamassan": "https://www.kistamassan.se/en/events/",
 "investstockholm": "https://www.investstockholm.com/events/",
 "norrsken": "https://www.norrsken.org/events",
 "sup46": "https://www.sup46.com/events",
 "epicenter": "https://epicenterstockholm.com/events/",
 "almi": "https://www.almi.se/evenemang/",
 "businesssweden": "https://www.business-sweden.com/events/",
 "iva": "https://www.iva.se/en/events/",
 "aws-events": "https://aws.amazon.com/events/",
 "google-cloud": "https://cloud.google.com/events",
 "ms-events": "https://events.microsoft.com/",
 "nordictechweek": "https://nordictechweek.com/",
 "luma-nordic": "https://lu.ma/nordictechweek",
 "luma-norrsken": "https://lu.ma/norrsken",
 "allevents": "https://allevents.in/stockholm/business",
 "10times": "https://10times.com/stockholm-se",
 "stockholm-se": "https://start.stockholm/evenemang/",
 "arbetsformedlingen": "https://arbetsformedlingen.se/for-arbetssokande/evenemang",
 "kth-armada": "https://armada.nu/",
}
for k,u in C.items():
    try:
        r = requests.get(u, headers=UA, timeout=25)
        h = r.text
        ev = sum(1 for o in jsonld_objects(h) if is_event_type(o))
        t = len(page_text(h, u)) if "json" not in r.headers.get("content-type","") else len(h)
        ics = len(re.findall(r"\.ics|webcal:", h))
        print(f"{r.status_code} text={t:>6} ldEvents={ev:>3} ics={ics} next={'__NEXT_DATA__' in h}  {k:<18} {u}")
    except Exception as e:
        print("ERR", k, str(e)[:70])
