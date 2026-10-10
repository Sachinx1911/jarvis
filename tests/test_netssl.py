"""Every urllib HTTPS call uses one TLS context that has CA certificates, even on a python.org
Python on macOS (which ships with none). Offline: no connection is made."""

import ssl

from jarvis import netssl


def test_tls_context_trusts_some_certificate_authorities_and_still_verifies():
    ctx = netssl.tls_context()
    assert ctx.cert_store_stats()["x509_ca"] > 0
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_certifi_is_used_when_python_has_no_certificates(monkeypatch):
    loaded = []

    class Empty(ssl.SSLContext):
        def cert_store_stats(self):
            return {"x509_ca": 0}

        def load_verify_locations(self, cafile=None, capath=None, cadata=None):
            loaded.append(cafile)

    monkeypatch.setattr(netssl.ssl, "create_default_context", lambda: Empty(ssl.PROTOCOL_TLS_CLIENT))
    netssl.tls_context.cache_clear()
    try:
        netssl.tls_context()
        import certifi
        assert loaded == [certifi.where()]
    finally:
        netssl.tls_context.cache_clear()


def test_web_tool_opener_uses_the_shared_context():
    from jarvis.tools import web

    handlers = [h for h in web._OPENER.handlers if h.__class__.__name__ == "HTTPSHandler"]
    assert handlers and handlers[0]._context.cert_store_stats()["x509_ca"] > 0
