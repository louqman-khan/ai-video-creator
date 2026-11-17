"""Shared HTTP helpers: one client config, retries, and errors that never leak API keys
(several providers put the key in the query string, so URLs are logged without it)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

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


def assert_public_url(url: str) -> None:
    """Refuse addresses on the server's own network (localhost, 10.x, 192.168.x, the cloud metadata address 169.254.169.254, ...): a download address that
    came from an outside search result must never make the hosted server fetch something from inside its own network."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HttpError("blocked: not a web address")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HttpError("blocked: the address cannot be resolved") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HttpError("blocked: that address is on a private network")


def make_client(read_timeout: float = 30.0, public_only: bool = False) -> httpx.Client:
    """`public_only`: every request, including each redirect, must go to a public address (hosted mode)."""
    return httpx.Client(
        timeout=httpx.Timeout(read_timeout, connect=10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        event_hooks={"request": [lambda r: assert_public_url(str(r.url))]} if public_only else {},
    )


def _request_once(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    resp = client.request(method, url, **kw)
    if resp.status_code in _RETRY_STATUS:
        raise RetryableHttpError(f"HTTP {resp.status_code} from {safe_url(url)}")
    if resp.is_error:
        raise HttpError(f"HTTP {resp.status_code} from {safe_url(url)}")
    return resp


_request = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((RetryableHttpError, httpx.TransportError)),
)(_request_once)


def get_json(client: httpx.Client, url: str, **kw):
    return _request(client, "GET", url, **kw).json()


def post_json(client: httpx.Client, url: str, *, retries: bool = True, **kw):
    """retries=False: one attempt only (the caller has its own fail-over, e.g. other models)."""
    return (_request if retries else _request_once)(client, "POST", url, **kw).json()
