"""Render JavaScript-only pages with a headless browser (Playwright), for the few sources that need it.

Playwright is optional: if it (or its Chromium) is not installed, `render_html` raises BrowserUnavailable and the
page is skipped with a warning. It identifies itself honestly (headless Chromium); we never try to get around blocks.
"""
from __future__ import annotations

import atexit
import logging

log = logging.getLogger(__name__)


class BrowserUnavailable(RuntimeError):
    pass


_state: dict = {}


def _launch():
    if "page" in _state:
        return _state["page"]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailable("playwright is not installed (pip install playwright && playwright install chromium)") from exc
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:
        pw.stop()
        raise BrowserUnavailable(f"chromium could not start: {str(exc)[:100]}") from exc
    context = browser.new_context(locale="en-GB", timezone_id="Europe/Stockholm")
    _state.update(pw=pw, browser=browser, page=context.new_page())
    atexit.register(close)
    return _state["page"]


def render_html(url: str, wait_ms: int = 2500) -> str:
    page = _launch()
    page.goto(url, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(wait_ms)                 # let late client-side rendering finish
    return page.content()


def close() -> None:
    for key in ("browser", "pw"):
        obj = _state.pop(key, None)
        try:
            if obj is not None:
                (obj.close if key == "browser" else obj.stop)()
        except Exception:
            pass
    _state.pop("page", None)
