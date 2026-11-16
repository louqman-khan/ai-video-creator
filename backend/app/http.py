"""Shared HTTP helpers: one client config, retries, and errors that never leak API keys
(several providers put the key in the query string, so URLs are logged without it)."""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import logging

# httpx logs every request URL at INFO, and several providers put the API key in the query
# string. Silence it here so no caller (CLI, tests, scripts) can leak a key into logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

USER_AGENT = "AIVideoCreator/0.1 (open-source video tool)"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    pass


class RetryableHttpError(HttpError):
    pass


def safe_url(url: str) -> str:
    return str(httpx.URL(url).copy_with(query=None))


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((RetryableHttpError, httpx.TransportError)),
)
def _request(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    resp = client.request(method, url, **kw)
    if resp.status_code in _RETRY_STATUS:
        raise RetryableHttpError(f"HTTP {resp.status_code} from {safe_url(url)}")
    if resp.is_error:
        raise HttpError(f"HTTP {resp.status_code} from {safe_url(url)}")
    return resp


def get_json(client: httpx.Client, url: str, **kw):
    return _request(client, "GET", url, **kw).json()


def post_json(client: httpx.Client, url: str, **kw):
    return _request(client, "POST", url, **kw).json()
