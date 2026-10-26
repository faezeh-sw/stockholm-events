"""Shared parsing helpers for dates, JSON-LD and text cleanup."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime

from dateutil import parser as dtparser

from .models import TZ

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(s: str | None, limit: int = 0) -> str:
    if not s:
        return ""
    s = html.unescape(_TAG.sub(" ", s))
    s = _WS.sub(" ", s).strip()
    return s[:limit].rstrip() if limit else s


def parse_dt(value: str | None) -> tuple[datetime | None, bool]:
    """Return (aware datetime in Stockholm, time_known)."""
    if not value:
        return None, False
    value = value.strip()
    time_known = bool(re.search(r"\d{1,2}:\d{2}", value))
    try:
        dt = dtparser.isoparse(value) if "T" in value or len(value) == 10 else dtparser.parse(value)
    except (ValueError, OverflowError):
        return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ), time_known


_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def jsonld_objects(html_text: str):
    """Yield every dict found in the page's JSON-LD blocks (flattening lists and @graph)."""
    for block in _LD.findall(html_text):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                yield o
                for k in ("@graph", "itemListElement", "item", "subEvent", "event"):
                    if k in o:
                        stack.append(o[k])


def is_event_type(o: dict) -> bool:
    t = o.get("@type")
    ts = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.endswith("Event") for x in ts)


def next_data(html_text: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    return json.loads(m.group(1)) if m else None
