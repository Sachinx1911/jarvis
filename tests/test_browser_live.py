"""Opt-in smoke test of the real Playwright driver against a local test page (no internet).
Needs `jarvis browser setup` first. Run: JARVIS_BROWSER_LIVE=1 pytest tests/test_browser_live.py"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("JARVIS_BROWSER_LIVE") != "1",
                                reason="real browser test (set JARVIS_BROWSER_LIVE=1)")

FORM = b"""<html><body><h1>Demo shop</h1>
<a href="/off">Partner</a> <a href="/file.pdf" download="invoice.pdf">Invoice</a>
<form action="/sent" method="post"><label>Name <input name="name"></label>
<label>Password <input type="password" name="pw"></label><button type="submit">Send</button></form>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/off":
            self._send(302, b"", headers={"Location": "http://blocked.localhost:1/"})
        elif self.path == "/file.pdf":
            self._send(200, b"%PDF-1.7 synthetic", "application/pdf",
                       {"Content-Disposition": 'attachment; filename="invoice.pdf"'})
        else:
            self._send(200, FORM)

    def do_POST(self):
        self._send(200, b"<html><body>Thanks</body></html>")


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_real_browser_flow(server, tmp_path):
    from jarvis.browser.playwright_driver import PlaywrightDriver

    allowed = lambda u: u.startswith(server) or u == "about:blank"  # noqa: E731
    drv = PlaywrightDriver(headless=True, timeout_s=10)
    drv.start(None, allowed)
    try:
        drv.goto(server + "/")
        assert "Demo shop" in drv.text()
        assert drv.describe("Send").submits and drv.describe("pw").type == "password"
        drv.fill("name", "Asha Demo")
        drv.fill("pw", "synthetic-not-real")
        form = drv.form()
        values = {f.name: f.value for f in form.fields}
        assert values == {"name": "Asha Demo", "pw": "******"} and form.action.endswith("/sent")
        res = drv.download("Invoice", tmp_path / "partial")
        assert res.path.read_bytes().startswith(b"%PDF") and res.filename == "invoice.pdf"
        drv.screenshot(tmp_path / "shot.png")
        assert (tmp_path / "shot.png").stat().st_size > 0
        try:
            drv.click("Partner")  # the redirect to another host is aborted by the route
        except Exception:
            pass
        assert "blocked.localhost" not in drv.url()  # error page or unchanged; the session then leaves it
        drv.goto(server + "/")
        drv.fill("name", "Asha Demo")
        drv.submit(None)
        assert "Thanks" in drv.text()
    finally:
        drv.close()
