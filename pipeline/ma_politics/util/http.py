"""Shared HTTP session for pipeline fetchers: identifies the project, retries
transient failures, and rate-limits so we're a polite, well-behaved client
against public government/nonprofit data sources with no bulk API."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter, Retry

USER_AGENT = (
    "ma-political-analytics-pipeline/0.1 "
    "(+https://github.com/nesanders/ma-political-analytics; contact via GitHub issues)"
)


def make_session(min_interval_s: float = 0.5) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session._min_interval_s = min_interval_s  # type: ignore[attr-defined]
    session._last_request_ts = 0.0  # type: ignore[attr-defined]
    return session


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with a minimum spacing between requests on this session."""
    min_interval = getattr(session, "_min_interval_s", 0.0)
    last_ts = getattr(session, "_last_request_ts", 0.0)
    wait = min_interval - (time.monotonic() - last_ts)
    if wait > 0:
        time.sleep(wait)
    resp = session.get(url, timeout=kwargs.pop("timeout", 30), **kwargs)
    session._last_request_ts = time.monotonic()  # type: ignore[attr-defined]
    resp.raise_for_status()
    return resp
