"""Audit a spreadsheet of candidate event sources against what we already read.

Usage: python tools/audit_sources.py path/to/sources.xlsx
For every URL: fetch it (plain HTTP, free), classify how it can be read, and say whether our config already covers it.
Writes docs/source-audit.md and prints a summary.
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import openpyxl
import requests
import yaml

sys.path.insert(0, ".")
from sthlm.collectors.llm_pages import page_text
from sthlm.parse import is_event_type, jsonld_objects

UA = {"User-Agent": "Mozilla/5.0 (compatible; StockholmEventsBot/1.0)"}
DATE = re.compile(r"\b(?:\d{1,2}\s*(?:jan|feb|mar|apr|may|maj|jun|jul|aug|sep|oct|okt|nov|dec)\w*|"
                  r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s*\d{1,2}|20\d\d-\d\d-\d\d)\b", re.I)


def norm(u: str) -> str:
    p = urlparse(u.strip())
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def existing_urls() -> set[str]:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    out = set()
    src = cfg["sources"]
    for key in ("jsonld_pages", "llm_pages"):
        for p in src.get(key, {}).get("pages", []):
            out.add(norm(p["url"]))
    return out


def classify(row):
    n, group, name, url, prio, typ, access, notes = row
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if "linkedin.com" in host:
        return {"how": "SKIP", "why": "LinkedIn (excluded by decision)"}
    if "eventbrite" in host:
        return {"how": "LOCAL", "why": "Eventbrite blocks GitHub; local-only source"}
    if host.endswith("meetup.com") and "/find/" not in url:
        return {"how": "MEETUP-GROUP", "why": "follow the group via Meetup GraphQL (free)"}
    if host.endswith("meetup.com"):
        return {"how": "COVERED", "why": "Meetup keyword search"}
    if host in ("luma.com", "lu.ma"):
        return {"how": "LUMA", "why": "Luma calendar/discover (free API)"}
    try:
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
    except Exception as exc:
        return {"how": "ERROR", "why": str(exc)[:70]}
    if r.status_code >= 400:
        return {"how": "ERROR", "why": f"HTTP {r.status_code}"}
    ld = sum(1 for o in jsonld_objects(r.text) if is_event_type(o))
    ics = bool(re.search(r"\.ics|webcal:", r.text))
    text = page_text(r.text, r.url)
    dates = len(DATE.findall(text))
    js = len(text) < 500 and bool(re.search(r"__NEXT_DATA__|id=\"root\"|id=\"__nuxt\"|ng-app|<noscript", r.text))
    if ld:
        how, why = "JSON-LD", f"{ld} schema.org events (free)"
    elif len(text) < 300:
        how, why = ("JS-ONLY", "renders with JavaScript") if js or len(r.text) > 5000 else ("THIN", f"only {len(text)} chars")
    elif dates < 2:
        how, why = "NO-DATES", f"{len(text)} chars, {dates} dates (landing page?)"
    else:
        how, why = "LLM", f"{len(text)} chars, {dates} dates"
    if ics:
        why += " + iCal link"
    return {"how": how, "why": why, "final": r.url}


def main(path):
    wb = openpyxl.load_workbook(path)
    ws = wb["100 SOURCES"]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[3]]
    rows = [(r[1], r[0], r[1], r[3], r[4], r[5], r[6], r[8]) for r in rows]
    have = existing_urls()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(classify, rows))
    lines = ["# Source audit", "", "| # | Pri | Source | Group | Result | Already covered | Note |", "|---|---|---|---|---|---|---|"]
    counts = {}
    for i, (row, res) in enumerate(zip(rows, results), 1):
        n, group, name, url, prio, typ, access, notes = row
        covered = norm(url) in have
        res["covered"] = covered
        counts[res["how"]] = counts.get(res["how"], 0) + 1
        lines.append(f"| {i} | {prio} | [{name}]({url}) | {group[3:]} | {res['how']} | {'yes' if covered else 'no'} | {res['why']} |")
        print(f"{i:>3} {prio} {res['how']:<13} cov={'Y' if covered else 'n'} {name[:38]:<38} {res['why'][:60]}")
    Path("docs").mkdir(exist_ok=True)
    Path("docs/source-audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nSUMMARY:", counts)
    import json
    Path("data").mkdir(exist_ok=True)
    json.dump([{"row": list(r), "res": s} for r, s in zip(rows, results)], open("data/audit.json", "w", encoding="utf-8"), default=str, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1])
