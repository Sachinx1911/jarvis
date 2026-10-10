"""Offline fake browser for tests. Pages are plain data; no network, no Chromium."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.browser.driver import PASSWORD_MASK, DownloadResult, ElementInfo, FormField, FormSnapshot
from jarvis.browser.policy import BrowserError


@dataclass
class FakeElement:
    tag: str = "input"          # input | button | a
    type: str = "text"
    name: str = ""
    text: str = ""
    value: str = ""
    autocomplete: str = ""
    submits: bool = False
    href: str | None = None     # link target, or where a download comes from
    download: tuple[str, bytes] | None = None  # (suggested filename, content)


@dataclass
class FakePage:
    text: str = ""
    redirect: str | None = None      # server-side redirect target
    elements: dict[str, FakeElement] = field(default_factory=dict)
    form_action: str = ""
    after_submit: str | None = None  # page the form leads to


class FakeDriver:
    """enforce_routes=True mimics the Playwright driver's network-level block (navigations to
    disallowed domains fail). False lets a redirect through so the session's own post-check
    can be tested as a second layer."""

    instances: list["FakeDriver"] = []

    def __init__(self, pages: dict[str, FakePage], enforce_routes: bool = True):
        self.pages = pages
        self.enforce_routes = enforce_routes
        self.current = "about:blank"
        self.profile_dir: Path | None = None
        self.started = False
        self.closed = False
        self.cookies: dict[str, str] = {}
        self.actions: list[tuple] = []
        self.last_filled: str | None = None
        self.allow: Callable[[str], bool] = lambda u: True
        FakeDriver.instances.append(self)

    def start(self, profile_dir: Path | None, allow_navigation: Callable[[str], bool]) -> None:
        self.profile_dir, self.allow, self.started = profile_dir, allow_navigation, True

    def _navigate(self, url: str) -> None:
        for _ in range(5):
            if self.enforce_routes and not self.allow(url):
                raise BrowserError(f"net::ERR_BLOCKED_BY_CLIENT at {url}")
            page = self.pages.get(url) or self.pages.get(url.split("?")[0])
            if page and page.redirect:
                url = page.redirect
                continue
            self.current = url
            return
        raise BrowserError("too many redirects")

    def _page(self) -> FakePage:
        page = self.pages.get(self.current) or self.pages.get(self.current.split("?")[0])
        if page is None:
            raise BrowserError("no page is open")
        return page

    def _el(self, target: str) -> FakeElement:
        page = self._page()
        if target in page.elements:
            return page.elements[target]
        for el in page.elements.values():
            if target and (target == el.name or target.lower() == el.text.lower()):
                return el
        raise BrowserError(f"nothing matching {target!r} on the page")

    def goto(self, url: str) -> None:
        self.actions.append(("goto", url))
        self._navigate(url)

    def url(self) -> str:
        return self.current

    def text(self) -> str:
        return self._page().text

    def describe(self, target: str) -> ElementInfo:
        el = self._el(target)
        return ElementInfo(el.tag, el.type, el.name, el.text, el.autocomplete, el.submits)

    def click(self, target: str) -> None:
        el = self._el(target)
        self.actions.append(("click", target))
        if el.href:
            self._navigate(el.href)

    def fill(self, target: str, value: str) -> None:
        el = self._el(target)
        if el.tag not in ("input", "textarea"):
            raise BrowserError(f"{target!r} is not a text field")
        el.value = value
        self.last_filled = target
        self.actions.append(("fill", target, value))

    def form(self) -> FormSnapshot | None:
        page = self._page()
        fields = tuple(FormField(el.name or key, el.type, PASSWORD_MASK if el.type == "password" else el.value)
                       for key, el in page.elements.items() if el.tag in ("input", "textarea") and el.type != "submit")
        if not fields and not page.form_action:
            return None
        return FormSnapshot(page.form_action, "post", fields)

    def submit(self, button: str | None) -> None:
        page = self._page()
        self.actions.append(("submit", button))
        if page.form_action and self.enforce_routes and not self.allow(page.form_action):
            raise BrowserError(f"net::ERR_BLOCKED_BY_CLIENT at {page.form_action}")
        if page.after_submit:
            self._navigate(page.after_submit)

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def download(self, target: str, folder: Path) -> DownloadResult:
        el = self._el(target)
        if not el.download:
            raise BrowserError(f"{target!r} does not start a download")
        url = el.href or self.current
        if self.enforce_routes and not self.allow(url):
            raise BrowserError(f"net::ERR_BLOCKED_BY_CLIENT at {url}")
        name, content = el.download
        folder.mkdir(parents=True, exist_ok=True)
        raw = folder / f"raw-{len(self.actions)}"
        raw.write_bytes(content)
        self.actions.append(("download", target))
        return DownloadResult(raw, url, name)

    def close(self) -> None:
        self.closed = True
        if self.profile_dir is None:
            self.cookies.clear()  # a fresh context keeps nothing
