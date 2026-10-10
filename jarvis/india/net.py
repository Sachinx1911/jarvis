"""Fetch interface for the India feeds. Tests pass a FakeFetcher; nothing else touches the network.

Only fixed URLs from config/india.yaml are fetched (never a link a model or a message gave),
over https, with a size cap.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from jarvis.netssl import tls_context

TIMEOUT = 25
MAX_BYTES = 8_000_000  # NAVAll.txt was about 1.5 MB on 2026-10-10
USER_AGENT = "Jarvis/0.1 (personal assistant)"


class FetchError(RuntimeError):
    pass


class Fetcher(Protocol):
    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes: ...


class UrlFetcher:
    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        if urllib.parse.urlparse(url).scheme != "https":
            raise FetchError("only https sources are fetched")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=tls_context()) as resp:  # noqa: S310 - https only, fixed URLs
                data = resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            raise FetchError(f"HTTP {e.code} from {urllib.parse.urlparse(url).hostname}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FetchError(f"network error: {e}") from e
        if len(data) > MAX_BYTES:
            raise FetchError("response too large")
        return data


class FakeFetcher:
    """url -> bytes (or an Exception to raise). Records every call."""

    def __init__(self, responses: dict[str, bytes | Exception] | None = None):
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        self.calls.append((url, dict(headers or {})))
        value = self.responses.get(url)
        if value is None:
            raise FetchError(f"no fake response for {url}")
        if isinstance(value, Exception):
            raise value
        return value
