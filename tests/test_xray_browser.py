"""Phase 9 part F: the clean Chrome wrapper with fake popen/http/CDP, and the tiny WebSocket
client against a loopback test server. No real Chrome."""

import base64
import hashlib
import json
import socket
import struct
import threading
from pathlib import Path

import pytest

from jarvis.xray import XrayError
from jarvis.xray.browser import CDPClient, CleanBrowser, free_port


class FakePopen:
    def __init__(self, argv):
        self.argv = argv
        self.terminated = False
        self.killed = False
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


class FakeCDP:
    """Answers Runtime.evaluate from a dict; counts wheel events."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.wheels: list[float] = []
        self.evaluated: list[str] = []
        self.closed = False

    def evaluate(self, expression):
        self.evaluated.append(expression)
        value = self.answers.get(expression)
        if isinstance(value, Exception):
            raise value
        return value

    def wheel(self, delta_y, x=0, y=0):
        self.wheels.append(delta_y)

    def close(self):
        self.closed = True


class Harness:
    def __init__(self, tmp_path, answers=None, version_ok=True, **kw):
        self.popens: list[FakePopen] = []
        self.requests: list[tuple[str, str]] = []
        self.cdp = FakeCDP(answers if answers is not None else {"document.readyState": "complete"})
        self.stragglers_called: list[Path] = []
        self.now = 0.0
        self.version_ok = version_ok

        def popen(argv):
            p = FakePopen(argv)
            self.popens.append(p)
            return p

        def http(method, url, timeout):
            self.requests.append((method, url))
            assert url.startswith("http://127.0.0.1:"), url
            if url.endswith("/json/version"):
                if not self.version_ok:
                    raise XrayError("connection refused")
                return 200, json.dumps({"Browser": "Chrome/140", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/x"}).encode()
            if "/json/new?" in url:
                assert method == "PUT"
                return 200, json.dumps({"id": "T1", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/T1"}).encode()
            return 404, b""

        def sleep(s):
            self.now += s

        self.browser = CleanBrowser("C:/fake/chrome.exe", popen=popen, http=http, cdp_factory=lambda ws: self.cdp,
                                    stragglers=lambda p: self.stragglers_called.append(p) or 0, sleep=sleep,
                                    clock=lambda: self.now, temp_root=tmp_path, **kw)


def test_fresh_profile_loopback_port_and_flags(tmp_path):
    h = Harness(tmp_path, headless=True, port=9333)
    with h.browser as b:
        assert b.profile is not None and b.profile.is_dir() and b.profile.parent == tmp_path
        assert b.profile.name.startswith("jarvis-xray-")
        argv = h.popens[0].argv
        assert argv[0] == "C:/fake/chrome.exe"
        assert f"--user-data-dir={b.profile}" in argv and "--remote-debugging-port=9333" in argv
        for flag in ("--disable-extensions", "--no-first-run", "--no-default-browser-check", "--window-size=1280,820",
                     "--headless=new"):
            assert flag in argv
        assert not any("Default" in a or "User Data" in a for a in argv)  # never the everyday profile
        assert h.requests[0] == ("GET", "http://127.0.0.1:9333/json/version")
        assert b.version["Browser"] == "Chrome/140"
        profile = b.profile
    assert not profile.exists()
    assert h.popens[0].terminated and h.stragglers_called == [profile]
    assert b.profile is None and b.proc is None


def test_headed_by_default_and_free_port(tmp_path):
    h = Harness(tmp_path)
    with h.browser as b:
        assert "--headless=new" not in h.popens[0].argv
        assert 1024 <= b.port <= 65535
    assert 1024 <= free_port() <= 65535


def test_open_waits_for_complete_and_settles(tmp_path):
    h = Harness(tmp_path, answers={"document.readyState": "complete", "1+1": 2})
    with h.browser as b:
        state = b.open("https://demo.test/page?x=1")
        assert state == "complete"
        assert h.requests[-1] == ("PUT", f"http://127.0.0.1:{b.port}/json/new?https://demo.test/page?x=1")
        assert b.target["id"] == "T1"
        assert h.now >= 2.5  # the settle
        assert b.evaluate("1+1") == 2
        assert b.scroll(16) == 16
        assert h.cdp.wheels == [600] * 16 and b.scrolled == 16
        b.scroll_to_top()
        assert h.cdp.wheels[-1] < 0
    assert h.cdp.closed


def test_open_gives_up_on_a_page_that_never_completes(tmp_path):
    h = Harness(tmp_path, answers={"document.readyState": "loading"})
    with h.browser as b:
        assert b.open("https://slow.test/", settle_s=0) == "loading"
        assert h.now >= 30


def test_profile_removed_even_when_the_job_fails(tmp_path):
    h = Harness(tmp_path)
    with pytest.raises(RuntimeError):
        with h.browser as b:
            profile = b.profile
            (profile / "Default").mkdir()
            (profile / "Default" / "Cookies").write_bytes(b"x")
            raise RuntimeError("job blew up")
    assert not profile.exists()
    assert h.popens[0].terminated and h.stragglers_called == [profile]


def test_start_timeout_cleans_up(tmp_path):
    h = Harness(tmp_path, version_ok=False)
    with pytest.raises(XrayError, match="did not answer within 25 s"):
        with h.browser:
            pass
    assert h.now >= 25
    assert h.popens[0].terminated and not any(p.is_dir() for p in tmp_path.glob("jarvis-xray-*"))


def test_chrome_that_exits_at_once_is_reported(tmp_path):
    h = Harness(tmp_path, version_ok=False)
    real_popen = h.browser.popen

    def popen(argv):
        p = real_popen(argv)
        p.exit_code = 21
        return p

    h.browser.popen = popen
    with pytest.raises(XrayError, match="exited at once"):
        with h.browser:
            pass


def test_evaluate_and_scroll_need_an_open_page(tmp_path):
    h = Harness(tmp_path)
    with h.browser as b:
        with pytest.raises(XrayError, match="no page open"):
            b.evaluate("1")
        with pytest.raises(XrayError, match="no page open"):
            b.scroll()
    with pytest.raises(XrayError, match="no Chrome path"):
        CleanBrowser("")


# ---- the WebSocket client against a loopback server ----

def _ws_server(received: list, replies: dict):
    """Accepts one client: handshake, then answers each masked text frame by id. Returns (port, thread)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def recv_exact(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    def run():
        conn, _ = srv.accept()
        conn.settimeout(5)
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        key = [l.split(b":", 1)[1].strip() for l in head.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
        accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        # a ping first: the client must answer with a pong and keep waiting for its reply
        conn.sendall(bytes([0x89, 0x02]) + b"hi")
        try:
            while True:
                b0, b1 = recv_exact(conn, 2)
                opcode, n = b0 & 0x0F, b1 & 0x7F
                assert b1 & 0x80, "client frames must be masked"
                if n == 126:
                    n = struct.unpack(">H", recv_exact(conn, 2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", recv_exact(conn, 8))[0]
                mask = recv_exact(conn, 4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(recv_exact(conn, n)))
                if opcode == 0xA:
                    received.append(("pong", payload))
                    continue
                if opcode == 0x8:
                    break
                msg = json.loads(payload)
                received.append(msg)
                # an event the client must skip, then the reply split into two fragments
                event = b'{"method":"Page.frameNavigated","params":{}}'
                conn.sendall(bytes([0x81, len(event)]) + event)
                reply = json.dumps({"id": msg["id"], "result": replies.get(msg["method"], {})}).encode()
                half = len(reply) // 2
                conn.sendall(bytes([0x01, half]) + reply[:half])          # text, FIN=0
                conn.sendall(bytes([0x80, len(reply) - half]) + reply[half:])  # continuation, FIN=1
        except (ConnectionError, OSError, json.JSONDecodeError):
            pass
        finally:
            conn.close()
            srv.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return port, t


def test_cdp_client_handshake_masking_ping_and_replies():
    received: list = []
    replies = {"Runtime.evaluate": {"result": {"type": "string", "value": "complete"}},
               "Input.dispatchMouseEvent": {}}
    port, thread = _ws_server(received, replies)
    client = CDPClient(f"ws://127.0.0.1:{port}/devtools/page/T1", timeout=5)
    assert client.evaluate("document.readyState") == "complete"
    client.wheel(600)
    client.close()
    thread.join(timeout=5)
    # the client only reads (and answers) the ping while waiting for its first reply
    assert received[0]["method"] == "Runtime.evaluate" and received[0]["params"]["returnByValue"] is True
    assert received[1] == ("pong", b"hi")
    assert received[2]["method"] == "Input.dispatchMouseEvent" and received[2]["params"]["type"] == "mouseWheel"
    assert received[2]["params"]["deltaY"] == 600


def test_cdp_client_surfaces_page_exceptions_and_errors():
    received: list = []
    replies = {"Runtime.evaluate": {"result": {"type": "object"}, "exceptionDetails": {"text": "Uncaught ReferenceError"}}}
    port, thread = _ws_server(received, replies)
    client = CDPClient(f"ws://127.0.0.1:{port}/x", timeout=5)
    with pytest.raises(XrayError, match="ReferenceError"):
        client.evaluate("nope()")
    client.close()
    thread.join(timeout=5)
    with pytest.raises(XrayError, match="loopback"):
        CDPClient("ws://example.test:9222/devtools/page/1")
