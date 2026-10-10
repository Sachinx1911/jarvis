"""The BrowserDriver interface. The Playwright driver and the offline fake both implement it,
so every safety rule in BrowserSession is tested without a real browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

# Never return or record the value of these fields, whatever the page calls them.
PASSWORD_MASK = "******"


@dataclass(frozen=True)
class ElementInfo:
    tag: str            # input, button, a, select, textarea, ...
    type: str = ""      # input type: text, password, submit, ...
    name: str = ""      # name / id / aria-label
    text: str = ""      # visible label or button text (untrusted)
    autocomplete: str = ""
    submits: bool = False  # clicking it submits a form


@dataclass(frozen=True)
class FormField:
    name: str
    type: str
    value: str          # PASSWORD_MASK for password fields


@dataclass(frozen=True)
class FormSnapshot:
    action: str         # where the form sends its data
    method: str
    fields: tuple[FormField, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DownloadResult:
    path: Path          # where the driver saved the raw file
    url: str            # where it came from
    filename: str       # name suggested by the site (untrusted)


class BrowserDriver(Protocol):
    def start(self, profile_dir: Path | None, allow_navigation: Callable[[str], bool]) -> None:
        """profile_dir None = a fresh, empty context. allow_navigation is checked for every
        navigation the page makes (redirects, links, form posts), not just the first one."""

    def goto(self, url: str) -> None: ...
    def url(self) -> str: ...
    def text(self) -> str: ...
    def describe(self, target: str) -> ElementInfo: ...
    def click(self, target: str) -> None: ...
    def fill(self, target: str, value: str) -> None: ...
    def form(self) -> FormSnapshot | None:
        """The form last filled, else the first form on the page."""

    def submit(self, button: str | None) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def download(self, target: str, folder: Path) -> DownloadResult: ...
    def close(self) -> None: ...
