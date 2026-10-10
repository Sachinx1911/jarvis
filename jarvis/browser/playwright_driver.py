"""BrowserDriver on Playwright's own Chromium (sync API). Never the user's Chrome: no `channel`,
no `executable_path`, no user-data folder except Jarvis's own per-site profiles.

Network rule: a context-level route checks every navigation request (first load, redirects,
links, form posts, downloads, frames) against the task's allowlist and aborts the rest. Other
requests to local or private literal addresses are aborted too. Service workers are blocked,
because routing does not see their requests. Popups are closed; Jarvis works in one tab.

The sync API is bound to the thread that started it: use one session per thread.
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable

from jarvis.browser.driver import DownloadResult, ElementInfo, FormField, FormSnapshot
from jarvis.browser.policy import BrowserError

NOT_INSTALLED = ("Chromium for Playwright is not installed. Run: jarvis browser setup "
                 "(one-time download of about 150-200 MB).")
_CSS_LIKE = re.compile(r"^([#.\[]|//|xpath=|css=|text=|[a-z][a-z0-9-]*([#.\[:]|$))", re.IGNORECASE)

_DESCRIBE_JS = """el => {
  const tag = el.tagName.toLowerCase();
  let type = (el.getAttribute('type') || '').toLowerCase();
  if (tag === 'button' && !type) type = 'submit';
  if (tag === 'input' && !type) type = 'text';
  const form = el.form || el.closest('form');
  const submits = !!form && ((tag === 'button' && type === 'submit') ||
                             (tag === 'input' && (type === 'submit' || type === 'image')));
  const isButton = ['submit', 'button', 'reset', 'image'].includes(type);
  const text = (el.innerText || (isButton ? el.value : '') || el.getAttribute('aria-label') ||
                el.getAttribute('placeholder') || '').trim().slice(0, 100);
  return {tag, type, name: el.getAttribute('name') || el.id || el.getAttribute('aria-label') || '',
          text, autocomplete: el.getAttribute('autocomplete') || '', submits};
}"""

_FORM_JS = """el => {
  const f = (el && (el.form || el.closest('form'))) || document.querySelector('form');
  if (!f) return null;
  const fields = [];
  for (const e of f.elements) {
    const tag = e.tagName.toLowerCase();
    if (['button', 'fieldset', 'object', 'output'].includes(tag)) continue;
    const type = (e.type || tag).toLowerCase();
    if (['submit', 'button', 'reset', 'image'].includes(type)) continue;
    let value;
    if (type === 'password') value = '******';
    else if (type === 'checkbox' || type === 'radio') { if (!e.checked) continue; value = e.value; }
    else if (type === 'file') value = Array.from(e.files || []).map(x => x.name).join(', ');
    else if (tag === 'select') value = Array.from(e.selectedOptions).map(o => o.value).join(', ');
    else value = e.value || '';
    fields.push({name: e.name || e.id || '', type, value});
  }
  return {action: f.action || location.href, method: (f.method || 'get').toLowerCase(), fields};
}"""

_SUBMIT_JS = """el => {
  const f = (el && (el.form || el.closest('form'))) || document.querySelector('form');
  if (!f) throw new Error('no form on the page');
  f.requestSubmit();
}"""


def _local_literal(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("localhost",) or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


class PlaywrightDriver:
    def __init__(self, headless: bool = True, timeout_s: float = 30, single_tab: bool = True):
        self.headless = headless
        self.single_tab = single_tab
        self.timeout_ms = timeout_s * 1000
        self._pw: Any = None
        self._browser: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._last: Any = None  # locator of the last filled field (its form is the one submitted)
        self._allow: Callable[[str], bool] = lambda u: False

    # ---- lifecycle ----

    def start(self, profile_dir: Path | None, allow_navigation: Callable[[str], bool]) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError as e:
            raise BrowserError("Playwright is not installed (pip install playwright)") from e
        self._allow = allow_navigation
        self._pw = sync_playwright().start()
        opts = {"accept_downloads": True, "service_workers": "block"}
        try:
            if profile_dir is None:  # fresh, empty, in-memory context
                self._browser = self._pw.chromium.launch(headless=self.headless)
                self._ctx = self._browser.new_context(**opts)
            else:  # Jarvis's own per-site profile; never the user's Chrome profile
                self._ctx = self._pw.chromium.launch_persistent_context(str(profile_dir), headless=self.headless, **opts)
        except Error as e:
            self.close()
            raise BrowserError(NOT_INSTALLED if "Executable doesn't exist" in str(e) else f"browser start failed: {e}") from e
        self._ctx.set_default_timeout(self.timeout_ms)
        self._ctx.route("**/*", self._route)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._ctx.on("page", self._popup)

    def _route(self, route: Any, request: Any) -> None:
        url = request.url
        if request.is_navigation_request() and not self._allow(url):
            route.abort("blockedbyclient")
        elif not request.is_navigation_request() and _local_literal(url):
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _popup(self, page: Any) -> None:
        if self.single_tab and page is not self._page:
            page.close()

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._ctx = self._page = self._last = None

    # ---- helpers ----

    def _call(self, fn: Callable[[], Any]) -> Any:
        from playwright.sync_api import Error

        try:
            return fn()
        except Error as e:
            raise BrowserError(str(e).splitlines()[0]) from e

    def _locate(self, target: str) -> Any:
        p = self._page
        if p is None:
            raise BrowserError("the browser is not started")
        cands = []
        if _CSS_LIKE.match(target):
            cands.append(p.locator(target))
        cands += [p.get_by_role("link", name=target), p.get_by_role("button", name=target), p.get_by_label(target),
                  p.get_by_placeholder(target), p.locator(f"[name={target!r}]") if "'" not in target else None,
                  p.get_by_text(target)]
        for loc in cands:
            if loc is None:
                continue
            try:
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        raise BrowserError(f"nothing matching {target!r} on the page")

    # ---- actions ----

    def goto(self, url: str) -> None:
        self._call(lambda: self._page.goto(url, wait_until="load"))

    def url(self) -> str:
        return self._page.url if self._page is not None else ""

    def text(self) -> str:
        return self._call(lambda: self._page.inner_text("body"))

    def describe(self, target: str) -> ElementInfo:
        d = self._call(lambda: self._locate(target).evaluate(_DESCRIBE_JS))
        return ElementInfo(d["tag"], d["type"], d["name"], d["text"], d["autocomplete"], bool(d["submits"]))

    def click(self, target: str) -> None:
        loc = self._locate(target)
        self._call(loc.click)
        self._call(lambda: self._page.wait_for_load_state("load"))

    def fill(self, target: str, value: str) -> None:
        loc = self._locate(target)
        self._call(lambda: loc.fill(value))
        self._last = loc

    def form(self) -> FormSnapshot | None:
        d = self._call(lambda: self._last.evaluate(_FORM_JS) if self._last is not None
                       else self._page.evaluate(_FORM_JS, None))
        if not d:
            return None
        return FormSnapshot(d["action"], d["method"], tuple(FormField(f["name"], f["type"], f["value"]) for f in d["fields"]))

    def submit(self, button: str | None) -> None:
        if button:
            self._call(self._locate(button).click)
        elif self._last is not None:
            self._call(lambda: self._last.evaluate(_SUBMIT_JS))
        else:
            self._call(lambda: self._page.evaluate(_SUBMIT_JS, None))
        self._call(lambda: self._page.wait_for_load_state("load"))
        self._last = None

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._call(lambda: self._page.screenshot(path=str(path)))

    def download(self, target: str, folder: Path) -> DownloadResult:
        loc = self._locate(target)

        def run() -> DownloadResult:
            with self._page.expect_download() as info:
                loc.click()
            d = info.value
            if not self._allow(d.url):
                d.cancel()
                raise BrowserError(f"download from {d.url.split('?')[0]} is not allowed")
            if d.failure():
                raise BrowserError(f"download failed: {d.failure()}")
            folder.mkdir(parents=True, exist_ok=True)
            raw = folder / f"raw-{uuid.uuid4().hex[:8]}"
            d.save_as(raw)
            return DownloadResult(raw, d.url, d.suggested_filename)
        return self._call(run)


def login_interactive(profile_dir: Path, url: str, allow_navigation: Callable[[str], bool]) -> None:
    """Open the site's profile in a visible window so the user logs in himself. Jarvis types
    nothing. Returns when the user closes the window."""
    drv = PlaywrightDriver(headless=False, timeout_s=30, single_tab=False)  # login popups (SSO) allowed
    drv.start(profile_dir, allow_navigation)
    try:
        drv.goto(url)
        drv._page.wait_for_event("close", timeout=0)
    finally:
        drv.close()
