"""A clean Chrome for one x-ray job (PLAN.md 18.1 item 2, PLAN 11.4). Standard library only.

- The user's installed Chrome binary, but a brand-new temp profile folder per job: never his
  everyday profile, cookies or logins. Since Chrome 136 the debugging port is ignored for the
  default profile anyway.
- A free loopback debugging port; `--disable-extensions --no-first-run --no-default-browser-check
  --window-size=1280,820`; `--headless=new` for tests and unattended drills.
- Start: poll http://127.0.0.1:<port>/json/version for up to 25 s. Open: PUT /json/new?<url>,
  then wait for document.readyState === "complete" plus a 2.5 s settle.
- A minimal CDP WebSocket client (handshake, masked text frames) used for two things only:
  read-only `Runtime.evaluate` and `Input.dispatchMouseEvent` wheel scrolls. Nothing here
  clicks, types, logs in or submits.
- Exit: terminate, kill stragglers that still hold the profile folder, delete the folder
  (retrying on Windows file locks).

`popen`, `http`, `cdp_factory` and `stragglers` are injectable so tests use fakes.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from jarvis.xray import XrayError

START_TIMEOUT = 25.0
LOAD_TIMEOUT = 30.0
SETTLE_S = 2.5
WINDOW = (1280, 820)
CHROME_FLAGS = ["--disable-extensions", "--no-first-run", "--no-default-browser-check",
                f"--window-size={WINDOW[0]},{WINDOW[1]}", "--disable-background-networking",
                "--disable-component-update", "--disable-sync", "--no-service-autorun", "--password-store=basic"]

# (method, url, timeout) -> (status, body bytes). Loopback only.
Http = Callable[[str, str, float], tuple[int, bytes]]


def default_http(method: str, url: str, timeout: float) -> tuple[int, bytes]:
    if urllib.parse.urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise XrayError("the browser client only talks to loopback")
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback only, checked above)
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        raise XrayError(f"browser not reachable: {e}") from e


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def default_popen(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            shell=False)


def default_stragglers(profile: Path) -> int:
    """Kill any Chrome process still holding this job's profile folder. Returns how many were targeted."""
    marker = str(profile)
    try:
        if sys.platform == "win32":
            script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*' + $env:JARVIS_XRAY_PROFILE "
                      "+ '*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }")
            env = {**os.environ, "JARVIS_XRAY_PROFILE": marker}
            res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                                 text=True, timeout=20, check=False, shell=False, env=env)
            return len([l for l in (res.stdout or "").splitlines() if l.strip()])
        res = subprocess.run(["pkill", "-f", marker], capture_output=True, text=True, timeout=10, check=False,
                             shell=False)
        return 1 if res.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError):
        return 0


class CDPClient:
    """The smallest WebSocket client that can talk to Chrome DevTools: one connection, text frames,
    masked client frames, pings answered. Events are ignored; replies are matched by id."""

    def __init__(self, ws_url: str, timeout: float = 20.0):
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise XrayError("CDP only over ws:// to loopback")
        self.timeout = timeout
        self._id = 0
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        request = (f"GET {path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise XrayError("CDP handshake: connection closed")
            head += chunk
            if len(head) > 65536:
                raise XrayError("CDP handshake: bad response")
        status_line, _, rest = head.partition(b"\r\n")
        if b" 101 " not in status_line:
            raise XrayError(f"CDP handshake failed: {status_line.decode(errors='replace')[:80]}")
        self._buf = rest.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in rest else b""

    # ---- frames ----

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise XrayError("CDP connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        b0, b1 = self._read_exact(2)
        fin, opcode, masked, n = bool(b0 & 0x80), b0 & 0x0F, b1 & 0x80, b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(n)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def _recv_message(self) -> str:
        """One complete text message; fragments are joined, pings answered, other frames ignored."""
        parts: list[bytes] = []
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise XrayError("CDP connection closed by Chrome")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x1 or (opcode == 0x0 and parts):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", errors="replace")
            # binary / pong / stray continuation frames are ignored

    # ---- commands ----

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        self._send_frame(0x1, json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode())
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = json.loads(self._recv_message())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise XrayError(f"CDP {method}: {msg['error'].get('message', 'error')}")
                return msg.get("result") or {}
        raise XrayError(f"CDP {method}: no reply within {self.timeout:.0f} s")

    def evaluate(self, expression: str) -> Any:
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if res.get("exceptionDetails"):
            raise XrayError(f"page script failed: {res['exceptionDetails'].get('text', 'exception')}")
        return (res.get("result") or {}).get("value")

    def wheel(self, delta_y: float, x: int = WINDOW[0] // 2, y: int = WINDOW[1] // 2) -> None:
        self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y})

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class CleanBrowser:
    def __init__(self, chrome_path: str, headless: bool = False, port: int | None = None,
                 popen: Callable[[list[str]], Any] = default_popen, http: Http = default_http,
                 cdp_factory: Callable[[str], Any] | None = None, stragglers: Callable[[Path], int] = default_stragglers,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 temp_root: Path | None = None):
        if not chrome_path:
            raise XrayError("no Chrome path")
        self.chrome_path = chrome_path
        self.headless = headless
        self.port = port
        self.popen = popen
        self.http = http
        self.cdp_factory = cdp_factory or (lambda ws: CDPClient(ws))
        self.stragglers = stragglers
        self.sleep = sleep
        self.clock = clock
        self.temp_root = temp_root
        self.profile: Path | None = None
        self.proc: Any = None
        self.cdp: Any = None
        self.version: dict = {}
        self.target: dict = {}
        self.url: str | None = None
        self.scrolled = 0

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def argv(self) -> list[str]:
        args = [self.chrome_path, f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
                *CHROME_FLAGS]
        if self.headless:
            args.append("--headless=new")
        args.append("about:blank")
        return args

    # ---- lifecycle ----

    def __enter__(self) -> "CleanBrowser":
        self.profile = Path(tempfile.mkdtemp(prefix="jarvis-xray-", dir=str(self.temp_root) if self.temp_root else None))
        if self.port is None:
            self.port = free_port()
        try:
            self.proc = self.popen(self.argv())
            self.version = self._wait_for_version()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _wait_for_version(self) -> dict:
        deadline = self.clock() + START_TIMEOUT
        last = "not started"
        while self.clock() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise XrayError(f"Chrome exited at once (code {self.proc.poll()}); is another Chrome using this profile?")
            try:
                status, body = self.http("GET", f"{self.base}/json/version", 2.0)
                if status == 200:
                    return json.loads(body.decode("utf-8", errors="replace"))
                last = f"HTTP {status}"
            except (XrayError, ValueError) as e:
                last = str(e)
            self.sleep(0.25)
        raise XrayError(f"Chrome's debugging port did not answer within {START_TIMEOUT:.0f} s ({last})")

    def __exit__(self, *exc) -> None:
        if self.cdp is not None:
            try:
                self.cdp.close()
            except Exception:
                pass
            self.cdp = None
        if self.proc is not None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except Exception:
                        pass
            except Exception:
                pass
            self.proc = None
        if self.profile is not None:
            try:
                self.stragglers(self.profile)
            except Exception:
                pass
            self._remove_profile()

    def _remove_profile(self) -> None:
        profile, self.profile = self.profile, None
        for attempt in range(6):
            shutil.rmtree(profile, ignore_errors=True)
            if not profile.exists():
                return
            self.sleep(0.5 * (attempt + 1))  # Windows keeps file locks for a moment after the process dies
        shutil.rmtree(profile, ignore_errors=True)

    # ---- the page ----

    def open(self, url: str, settle_s: float = SETTLE_S) -> str:
        """Open `url` in a new tab and wait until the document is complete, then settle. Returns readyState."""
        if self.proc is None:
            raise XrayError("browser not started")
        status, body = self.http("PUT", f"{self.base}/json/new?{url}", 10.0)
        if status != 200:
            raise XrayError(f"Chrome refused to open a tab (HTTP {status})")
        self.target = json.loads(body.decode("utf-8", errors="replace"))
        ws = self.target.get("webSocketDebuggerUrl")
        if not ws:
            raise XrayError("Chrome gave no debugger address for the new tab")
        self.cdp = self.cdp_factory(ws)
        self.url = url
        state = "unknown"
        deadline = self.clock() + LOAD_TIMEOUT
        while self.clock() < deadline:
            try:
                state = str(self.cdp.evaluate("document.readyState"))
            except XrayError:
                state = "unknown"
            if state == "complete":
                break
            self.sleep(0.25)
        if settle_s:
            self.sleep(settle_s)
        return state

    def evaluate(self, expression: str) -> Any:
        """Read-only page inspection through Runtime.evaluate."""
        if self.cdp is None:
            raise XrayError("no page open")
        return self.cdp.evaluate(expression)

    def scroll(self, steps: int = 16, delta: int = 600, pause: float = 0.3) -> int:
        """Wheel-scroll down the page in `steps` steps so lazy content and animations load."""
        if self.cdp is None:
            raise XrayError("no page open")
        for _ in range(steps):
            self.cdp.wheel(delta)
            self.scrolled += 1
            self.sleep(pause)
        return steps

    def scroll_to_top(self, pause: float = 0.5) -> None:
        if self.cdp is None:
            raise XrayError("no page open")
        self.cdp.wheel(-1_000_000)
        self.sleep(pause)
