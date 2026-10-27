import sys, re, requests
sys.path.insert(0, ".")
from sthlm.collectors.llm_pages import page_text
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/1.0)"}
C = {
 "stockholmsmassan": "https://stockholmsmassan.se/en/calendar/",
 "kistamassan": "https://www.kistamassan.se/en/calendar/",
 "handelskammare": "https://stockholmshandelskammare.se/events/",
 "kth-calendar": "https://www.kth.se/en/om/upptack/kalender",
 "swisscham": "https://swisscham.se/events/upcoming-events/",
 "businesseventnetwork": "https://businesseventnetwork.se/kommande-natverkstraffar/",
 "kista-science-city": "https://kistasciencecity.com/event-calendar/",
 "sbr-business-events": "https://en.stockholmbusinessregion.se/business-events-stockholm/",
 "allamassor-kista": "https://www.allamassor.se/venue/kistamassan/",
 "amcham": "https://www.amcham.se/program",
 "norrsken": "https://www.norrsken.org/events",
 "su-career": "https://www.su.se/english/education/careers/career-events",
 "hhs-site": "https://www.hhs.se/research/institutes/site/",
 "aievents": "https://aievents.se/en/events/",
 "hyperight": "https://hyperight.com/events/",
 "scilifelab": "https://www.scilifelab.se/events/",
 "founderslive": "https://www.founderslive.com/events-list/stockholm-2026-11",
 "sxc": "https://www.sxc.se/",
 "digitalize": "https://digitalizeinsthlm.se/",
 "ki-calendar": "https://ki.se/en/about-ki/events-at-ki",
 "sundbyberg": "https://www.sundbyberg.se/arkiv/evenemang-och-aktiviteter",
 "nacka": "https://www.nacka.se/evenemang/",
 "svenskt-naringsliv": "https://www.svensktnaringsliv.se/event",
 "eventsforgamers": "https://www.eventsforgamers.com/events/?country=Sweden",
 "infosec-conf": "https://infosec-conferences.com/country/sweden/",
 "lund-uni": "https://www.kth.se/en/om/upptack/kalender?page=2",
}
for k,u in C.items():
    try:
        r = requests.get(u, headers=UA, timeout=25)
        t = page_text(r.text, u)
        dates = len(re.findall(r"\b(?:Nov(?:ember)?|nov(?:ember)?|2026-1[12]-\d\d|\d{1,2}\s+nov)", t))
        print(f"{r.status_code} text={len(t):>6} dateHits={dates:>3}  {k:<22} {u}")
    except Exception as e:
        print("ERR", k, str(e)[:60])
