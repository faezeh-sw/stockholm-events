"""Count what the LLM calls consume, so the weekly health report can show where the credit goes."""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0, "searches": 0, "calls": 0})


def record(kind: str, usage) -> None:
    """`usage` is the `usage` object of an Anthropic response (or None)."""
    if usage is None:
        return
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    with _lock:
        t = _totals[kind]
        t["in"] += (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        t["out"] += getattr(usage, "output_tokens", 0) or 0
        t["searches"] += searches
        t["calls"] += 1


def flush(store) -> None:
    """Persist this process's totals and reset them."""
    with _lock:
        items = {k: dict(v) for k, v in _totals.items() if v["calls"]}
        _totals.clear()
    for kind, t in items.items():
        store.log_usage(kind, t["in"], t["out"], t["searches"], t["calls"])
    if items:
        store.commit()
