import json
from datetime import datetime, timedelta

from sthlm import render
from sthlm.collectors.base import event_from_jsonld
from sthlm.collectors.tickster import DESC_RE, START_RE, URL_RE
from sthlm.dedupe import merge, norm
from sthlm.geo import district, in_stockholm
from sthlm.models import TZ, Event
from sthlm.parse import clean_text, parse_dt


def ev(title, day=datetime(2026, 11, 5, 19, 0, tzinfo=TZ), source="a", venue="", lat=None, lon=None, **kw):
    return Event(source=source, source_id=title + source, title=title, start=day, url="https://x/" + title,
                 venue=venue, lat=lat, lon=lon, **kw)


def test_parse_dt_date_only_and_time():
    d, known = parse_dt("2026-11-03")
    assert d.hour == 0 and not known
    d, known = parse_dt("2026-11-03T19:30:00+01:00")
    assert known and d.hour == 19
    d, known = parse_dt("2026-07-01T18:00:00Z")          # UTC converted to Stockholm summer time
    assert d.hour == 20


def test_clean_text_strips_html():
    assert clean_text("<p>Hello&nbsp;&amp; <b>world</b></p>") == "Hello & world"


def test_jsonld_conversion_prices_and_online():
    o = {"@type": "Event", "name": "Concert", "startDate": "2026-11-05T19:00:00+01:00",
         "location": {"name": "Venue", "address": {"streetAddress": "Gatan 1", "addressLocality": "Stockholm"},
                      "geo": {"latitude": "59.33", "longitude": "18.06"}},
         "offers": [{"price": "0", "priceCurrency": "SEK"}], "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}
    e = event_from_jsonld(o, "t")
    assert e.is_free and e.price_text == "Free" and e.lat == 59.33 and not e.online
    o["eventAttendanceMode"] = "https://schema.org/OnlineEventAttendanceMode"
    assert event_from_jsonld(o, "t").online


def test_dedupe_merges_same_event_across_sources():
    a = ev("Joe Bonamassa - Live in Concert", source="ticketmaster", venue="Avicii Arena", lat=59.2936, lon=18.0833)
    b = ev("Joe Bonamassa Live in Concert", source="visitstockholm", venue="Avicii Arena", description="long text " * 5)
    out = merge([a, b], {"ticketmaster": 80, "visitstockholm": 70})
    assert len(out) == 1
    assert out[0].event.source == "ticketmaster" and "long text" in out[0].event.description
    assert {s for s, _ in out[0].sources} == {"ticketmaster", "visitstockholm"}


def test_dedupe_keeps_different_events_and_matinee_vs_evening():
    a = ev("Hamlet", day=datetime(2026, 11, 5, 13, 0, tzinfo=TZ))
    b = ev("Hamlet", day=datetime(2026, 11, 5, 19, 0, tzinfo=TZ), source="b")
    c = ev("Totally different", source="c")
    assert len(merge([a, b, c], {})) == 3


def test_norm_ignores_noise_and_accents():
    assert norm("Biljetter: Café Ö – Live!") == "cafe o"


def test_tickster_patterns():
    desc = "Breddtrav på Halmstadtravet i Halmstad den 7 november - Tickster.com"
    m = DESC_RE.match(desc)
    assert m["v"] == "Halmstadtravet" and m["c"] == "Halmstad"
    assert URL_RE.search("https://www.tickster.com/se/sv/events/9huf855mz2zjzvr/2026-11-07/breddtrav")["date"] == "2026-11-07"
    assert START_RE.search("Startar 07 nov 11:10")[1] == "11"


def test_geo():
    assert in_stockholm(ev("x", lat=59.33, lon=18.07))
    assert not in_stockholm(ev("x", lat=58.59, lon=16.18))       # Norrköping
    assert district(59.3150, 18.0710) == "Södermalm"


def test_render_escapes_and_splits_under_limit():
    from sthlm.dedupe import Merged
    ms = [Merged(ev(f"Show <{i}> & Co", day=datetime(2026, 11, 5, 18, i % 60, tzinfo=TZ), venue="Venue", category="music"))
          for i in range(60)]
    for m in ms:
        m.event.extra["score"] = 5
    now = datetime(2026, 11, 5, 8, 0, tzinfo=TZ)
    msgs = render.digest(ms, [now.date()], now.date(), per_day=60)
    assert len(msgs) > 1 and all(len(m) <= 4096 for m in msgs)
    assert "&lt;3&gt;" in "".join(msgs) and "<3>" not in "".join(msgs)


def test_price_and_when_formatting():
    e = ev("x", end=datetime(2026, 11, 5, 21, 30, tzinfo=TZ))
    e.time_known = True
    assert render.when(e) == "19:00–21:30"
    e.time_known = False
    assert render.when(e) == "Time TBA"


def test_llm_pages_extraction_with_mock():
    import json as _json
    from types import SimpleNamespace
    from sthlm.collectors.llm_pages import LlmPages, page_text

    html = '<html><nav>menu</nav><body><h1>Program</h1><a href="/e/1">Opera Gala</a> 28 nov 19:00<footer>x</footer>' + "<p>filler text</p>" * 30 + "</body></html>"
    txt = page_text(html, "https://venue.se/program")
    assert "Opera Gala <https://venue.se/e/1>" in txt and "menu" not in txt

    reply = _json.dumps([{"title": "Opera Gala", "start": "2026-11-28T19:00", "end": None, "url": "https://venue.se/e/1",
                          "price": "Free", "description": "Gala"}, {"title": "Broken", "start": None}])
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"events": _json.loads(reply)})])))
    win = (datetime(2026, 10, 23, tzinfo=TZ), datetime(2026, 11, 30, tzinfo=TZ))
    c = LlmPages({"pages": []}, None, win, set(), None, client=client)
    evs = c._extract(txt, "https://venue.se/program", {"name": "venue", "venue": "Venue"})
    assert len(evs) == 1 and evs[0].is_free and evs[0].start.hour == 19 and evs[0].venue == "Venue"


def test_day_header_repeats_on_every_message_and_groups_categories():
    from sthlm.dedupe import Merged
    ms = []
    for i in range(40):
        e = ev(f"Event {i}", day=datetime(2026, 11, 5, 10 + i % 12, 0, tzinfo=TZ), venue="V", category="music" if i % 2 else "art")
        e.extra.update(score=5, summary_en="A short description of the event. " * 3)
        ms.append(Merged(e, [("tickster", e.url)]))
    day = datetime(2026, 11, 5).date()
    msgs = render.digest(ms, [day], day, per_day=40)
    assert len(msgs) >= 2 and all(len(m) <= 4096 for m in msgs)
    assert all("THURSDAY, 5 NOVEMBER" in m for m in msgs)
    assert "continued" not in "".join(msgs) and "events ·" not in "".join(msgs)
    assert "MUSIC" in msgs[0] and "<i>A short description" in msgs[0]
    assert "Paid" in msgs[0]


def test_price_and_language_always_shown():
    from sthlm.dedupe import Merged
    a = ev("Free show"); a.is_free = True; a.lang = "en"
    b = ev("Priced", price_text="from 200 kr"); b.lang = "sv"
    c = ev("Unknown", source="meetup")
    d = ev("Text says free", source="meetup"); d.extra["cost"] = "free"; d.lang = "none"
    ta, tb, tc, td = (render.item(Merged(x, [(x.source, "u")])) for x in (a, b, c, d))
    assert "Free" in ta and "🗣 English" in ta
    assert "Paid</b> · from 200 kr" in tb and "🗣 Swedish" in tb
    assert "Price: see event page" in tc and "Language: see event page" in tc
    assert "Free" in td and "No language needed" in td


def _item_lines(m):
    import re
    return re.sub(r"<[^>]+>", "", render.item(m)).split("\n")


def test_every_listing_has_the_same_four_lines_even_with_missing_data():
    from sthlm.dedupe import Merged
    full = ev("Full", venue="Venue", category="music", is_free=True)
    full.lang = "en"; full.time_known = True
    full.extra["summary_en"] = "A nice event."
    bare = ev("Bare")                       # no venue, no summary, no time, no price, no language
    bare.time_known = False
    swedish = ev("Pjäs", price_text="from 250 kr", venue="Teatern", area="Södermalm")
    swedish.lang = "sv"; swedish.time_known = True
    for e in (full, bare, swedish):
        lines = _item_lines(Merged(e, [(e.source, "u")]))
        assert len(lines) == 4, lines
        assert lines[2].startswith("🕒") and "📍" in lines[2]
        assert lines[3].startswith(("🆓", "💰")) and "🗣" in lines[3]
    assert _item_lines(Merged(bare, [("a", "u")]))[1] == "See the event page for details."


def test_weekly_covers_next_monday_to_sunday_with_intro():
    from sthlm.dedupe import Merged
    now = datetime(2026, 11, 2, 7, 0, tzinfo=TZ)            # a Monday
    assert render.next_week_start(now.date()) == datetime(2026, 11, 9).date()
    assert render.next_week_start(datetime(2026, 11, 8).date()) == datetime(2026, 11, 9).date()   # Sunday
    ms = []
    for day in (2, 8, 9, 15, 16):                           # only 9 and 15 fall in Mon 9 - Sun 15
        e = ev(f"E{day}", day=datetime(2026, 11, day, 18, 0, tzinfo=TZ), venue="V", category="music")
        e.extra["score"] = 5
        ms.append(Merged(e, [("a", "u")]))
    msgs = render.weekly(ms, now)
    text = "\n".join(msgs)
    assert msgs[0].startswith("🗓") and "9–15 NOVEMBER" in msgs[0]
    assert "E9" in text and "E15" in text and "E8" not in text and "E16" not in text and "E2<" not in text
    assert "MONDAY, 9 NOVEMBER" in text and "SUNDAY, 15 NOVEMBER" in text


def test_discovery_accepts_only_urls_returned_by_the_search():
    from types import SimpleNamespace as NS
    from sthlm.collectors.discovery import Discovery, norm_url, parse_json_array
    assert norm_url("https://www.Example.com/a/b/?x=1") == "example.com/a/b"
    arr = parse_json_array('Here you go:\n```json\n[{"title": "A"}, {"title": "B"}]\n```')
    assert [a["title"] for a in arr] == ["A", "B"]
    good = {"title": "Cloud Day", "start": "2026-11-05T09:00", "url": "https://cloud.example.com/day/", "price": "Free"}
    fake = {"title": "Invented", "start": "2026-11-05", "url": "https://nowhere.example.org/x"}
    reply = json.dumps([good, fake])
    result = NS(type="web_search_tool_result", content=[NS(url="https://cloud.example.com/day")])
    msg = NS(content=[result, NS(type="text", text=reply)], stop_reason="end_turn")
    client = NS(messages=NS(create=lambda **kw: msg))
    win = (datetime(2026, 10, 27, tzinfo=TZ), datetime(2026, 11, 26, tzinfo=TZ))
    d = Discovery({}, None, win, set(), None, client=client)
    evs = d._run("q")
    assert [e.title for e in evs] == ["Cloud Day"] and evs[0].is_free and evs[0].time_known


def test_held_in_stockholm_rejects_other_cities_and_unknown_on_strict_pages():
    from sthlm.geo import held_in_stockholm
    bangkok = ev("Expo"); bangkok.area = "Bangkok"
    sthlm = ev("Expo"); sthlm.area = "Solna"
    nowhere = ev("Expo")
    coords = ev("Expo", lat=59.33, lon=18.07)
    far = ev("Expo", lat=51.5, lon=-0.12)
    assert not held_in_stockholm(bangkok) and held_in_stockholm(sthlm)
    assert held_in_stockholm(nowhere) and not held_in_stockholm(nowhere, strict=True)
    assert held_in_stockholm(coords, strict=True) and not held_in_stockholm(far)


def test_fun_weekly_lists_only_free_events_and_professional_lists_all():
    from sthlm.dedupe import Merged
    now = datetime(2026, 11, 2, 7, 0, tzinfo=TZ)
    day = datetime(2026, 11, 10, 18, 0, tzinfo=TZ)
    free = ev("Free concert", day=day, venue="V", category="music", is_free=True)
    paid = ev("Paid concert", day=day, venue="V", category="music", price_text="from 300 kr")
    unknown = ev("Mystery", day=day, venue="V", category="music", source="meetup")
    ms = [Merged(e, [(e.source, "u")]) for e in (free, paid, unknown)]
    for m in ms:
        m.event.extra["score"] = 5
    fun = " ".join(render.weekly(ms, now, audience="fun"))
    pro = " ".join(render.weekly(ms, now, audience="professional"))
    assert "Free concert" in fun and "Paid concert" not in fun and "Mystery" not in fun and "FREE EVENTS" in fun
    assert "Free concert" in pro and "Paid concert" in pro and "Mystery" in pro and "WEEK AHEAD" in pro


def test_ics_parsing_folding_timezones_and_cancelled():
    from sthlm.collectors.ics_feeds import IcsFeeds, parse_ics
    text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:1\r\nSUMMARY:AI Meetup\, Stockholm\r\nDTSTART;TZID=Europe/Stockholm:20261105T180000\r\n"
            "DTEND;TZID=Europe/Stockholm:20261105T200000\r\nLOCATION:Epicenter\, Regeringsgatan 65\, Stockholm\r\n"
            "DESCRIPTION:Line one\r\n  continued\r\nURL:https://x.se/e1\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:2\r\nSUMMARY:Day event\r\nDTSTART;VALUE=DATE:20261106\r\nSTATUS:CANCELLED\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:3\r\nSUMMARY:UTC event\r\nDTSTART:20261107T170000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = [IcsFeeds._to_event(r, {"name": "t", "url": "https://x.se"}) for r in parse_ics(text)]
    a, cancelled, c = evs
    assert a.title == "AI Meetup, Stockholm" and a.time_known and a.start.hour == 18 and a.url == "https://x.se/e1"
    assert "continued" in a.description and a.venue == "Epicenter"
    assert cancelled is None
    assert c.start.hour == 18 and c.start.day == 7          # 17:00 UTC is 18:00 in Stockholm in November


def test_render_pages_are_skipped_cleanly_when_no_browser(monkeypatch):
    from sthlm import browser
    from sthlm.collectors.llm_pages import LlmPages

    def no_browser(url, wait_ms=0):
        raise browser.BrowserUnavailable("no playwright")
    monkeypatch.setattr(browser, "render_html", no_browser)
    win = (datetime(2026, 10, 27, tzinfo=TZ), datetime(2026, 11, 26, tzinfo=TZ))
    c = LlmPages({"pages": [{"name": "js", "url": "https://js.example/events", "render": True}]}, None, win, set(), None, client=object())
    assert list(c.fetch()) == []                       # logged and skipped, no crash
