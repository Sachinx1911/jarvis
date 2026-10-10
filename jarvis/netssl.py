"""One TLS context for every HTTPS call Jarvis makes with urllib.

python.org builds of Python on macOS come without CA certificates unless "Install
Certificates.command" was run, so the default context trusts nothing and every HTTPS call
fails with "unable to get local issuer certificate" (seen on Sachin's Mac, 2026-10-10).
Windows and most Linux Pythons use the system store. This module keeps the system
certificates when Python has them and otherwise loads certifi's bundle. Certificate checks
are never turned off.
"""

from __future__ import annotations

import ssl
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi
        except ImportError:  # pragma: no cover - certifi is a declared dependency
            return ctx
        ctx.load_verify_locations(cafile=certifi.where())
    return ctx


def https_handler() -> urllib.request.HTTPSHandler:
    return urllib.request.HTTPSHandler(context=tls_context())
