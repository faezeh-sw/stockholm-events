from __future__ import annotations

import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; StockholmEventsBot/1.0; event aggregator)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en,sv;q=0.8"})
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "POST"))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


class Http:
    """Polite HTTP client: shared session, timeout and a minimum delay between calls."""

    def __init__(self, delay: float = 0.4, timeout: int = 25):
        self.s = make_session()
        self.delay = delay
        self.timeout = timeout
        self._next = 0.0
        self._lock = threading.Lock()

    def get(self, url: str, delay: float | None = None, **kw) -> requests.Response:
        """GET with a global rate limit (one request slot every `delay` seconds, across threads)."""
        return self._request("get", url, delay, **kw)

    def post(self, url: str, delay: float | None = None, **kw) -> requests.Response:
        return self._request("post", url, delay, **kw)

    def _request(self, method: str, url: str, delay: float | None, **kw) -> requests.Response:
        d = self.delay if delay is None else delay
        with self._lock:
            slot = max(time.monotonic(), self._next)
            self._next = slot + d
        wait = slot - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        kw.setdefault("timeout", self.timeout)
        r = getattr(self.s, method)(url, **kw)
        r.raise_for_status()
        return r
