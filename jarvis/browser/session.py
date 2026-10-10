"""One isolated browser per task (PLAN.md 11.4).

- Playwright's own Chromium; never the user's Chrome profile, cookies or passwords.
- Default: a fresh, empty context, started on first use and wiped by close().
- A site that needs a login uses its own persistent profile in <home>/data/browser/<site>/,
  where the user logged in himself (jarvis browser login). That site must be on the allowlist.
- The allowlist is fixed when the session is created; every navigation is checked.
- Screenshots, downloads and the step log go into the task folder.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from jarvis.browser.driver import BrowserDriver
from jarvis.browser.policy import (
    BrowserError,
    DomainAllowlist,
    DownloadRejected,
    check_download,
    load_browser_config,
    normalize_domain,
    profile_dir,
    safe_filename,
)
from jarvis.browser.recording import STEPS_FILE, RecordingDriver
from jarvis.control.audit import AuditLog
from jarvis.tools.web import WebError, _check_public_url


def _playwright_factory(config: dict) -> Callable[[], BrowserDriver]:
    def make() -> BrowserDriver:
        from jarvis.browser.playwright_driver import PlaywrightDriver

        return PlaywrightDriver(headless=bool(config.get("headless", True)),
                                timeout_s=float(config.get("navigation_timeout_seconds", 30)))
    return make


class BrowserSession:
    def __init__(self, home: Path, task_dir: Path, allowed_domains: list[str], audit: AuditLog | None = None,
                 driver_factory: Callable[[], BrowserDriver] | None = None, config: dict | None = None,
                 site: str | None = None, step_sinks: list[Path] | None = None,
                 check_url: Callable[[str], None] = _check_public_url):
        self.config = config if config is not None else load_browser_config()
        self.home = home
        self.task_dir = task_dir
        self.allow = DomainAllowlist(list(allowed_domains) + list(self.config.get("default_allowed_domains") or []))
        self.audit = audit
        self.site = normalize_domain(site) if site else None
        if self.site and not self.allow.allows(f"https://{self.site}/"):
            raise BrowserError(f"the profile site {self.site} is not on this task's allowlist")
        self.driver_factory = driver_factory or _playwright_factory(self.config)
        self.check_url = check_url
        self.dir = task_dir / "browser"
        self.downloads = task_dir / "downloads"
        self.step_sinks = [self.dir / STEPS_FILE] + list(step_sinks or [])
        self._driver: RecordingDriver | None = None
        self._shots = 0
        dl = self.config.get("downloads") or {}
        self.allowed_types = list(dl.get("allowed_types") or ["pdf", "csv", "txt"])
        self.max_bytes = int(float(dl.get("max_mb", 25)) * 1024 * 1024)
        self.max_page_chars = int(self.config.get("max_page_chars", 20000))

    # ---- lifecycle ----

    @property
    def started(self) -> bool:
        return self._driver is not None

    @property
    def driver(self) -> RecordingDriver:
        if self._driver is None:
            profile = profile_dir(self.home, self.site) if self.site else None
            raw = self.driver_factory()
            raw.start(profile, self.navigation_allowed)
            self._driver = RecordingDriver(raw, self.step_sinks)
            self._log("browser_started", profile=self.site or "fresh", allowlist=str(self.allow))
        return self._driver

    def close(self) -> None:
        """End of task: close the browser. A fresh context is gone with it (Playwright keeps
        nothing on disk for it); the partial-download folder is removed. Site profiles persist."""
        if self._driver is not None:
            try:
                self._driver.close()
            finally:
                self._driver = None
                self._log("browser_closed", profile=self.site or "fresh (wiped)")
        shutil.rmtree(self.dir / ".partial", ignore_errors=True)

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _log(self, event: str, **fields) -> None:
        if self.audit:
            self.audit.write(event, task_dir=self.task_dir.name, **fields)

    # ---- rules ----

    def navigation_allowed(self, url: str) -> bool:
        if url == "about:blank":
            return True
        if not self.allow.allows(url):
            self._log("browser_blocked", url=url.split("?")[0], reason="not on the allowlist")
            return False
        try:
            self.check_url(url)
        except WebError as e:
            self._log("browser_blocked", url=url.split("?")[0], reason=str(e))
            return False
        return True

    def require_allowed(self, url: str) -> None:
        if not self.allow.allows(url):
            raise BrowserError(f"{url.split('?')[0]} is not on this task's allowed sites ({self.allow})")
        try:
            self.check_url(url)
        except WebError as e:
            raise BrowserError(str(e)) from e

    def after_navigation(self) -> str:
        """Second layer behind the driver's network block: if the page ended up off the
        allowlist (e.g. a redirect), leave it at once."""
        url = self.driver.url()
        if not self.allow.allows(url):
            self._driver.inner.goto("about:blank")  # type: ignore[union-attr]
            self._log("browser_blocked", url=url.split("?")[0], reason="redirected off the allowlist")
            raise BrowserError(f"the page went to {url.split('?')[0]}, which is not on this task's allowed "
                               f"sites ({self.allow}); it was closed")
        return url

    # ---- evidence and downloads ----

    def screenshot(self, label: str = "page") -> Path:
        self._shots += 1
        path = self.dir / "screenshots" / f"{self._shots:03d}-{safe_filename(label)}.png"
        self.driver.screenshot(path)
        return path

    def download(self, target: str) -> tuple[Path, str]:
        partial = self.dir / ".partial"
        res = self.driver.download(target, partial)
        try:
            if not self.allow.allows(res.url):
                raise DownloadRejected(f"the file comes from {res.url.split('?')[0]}, which is not allowed")
            name = safe_filename(res.filename)
            final = self.downloads / name
            staged = res.path.with_name(name)  # check under the real extension, still in .partial
            if staged != res.path:
                if staged.exists():
                    staged.unlink()
                res.path.rename(staged)
            kind = check_download(staged, self.allowed_types, self.max_bytes)
            self.downloads.mkdir(parents=True, exist_ok=True)
            stem, n = final.stem, 1
            while final.exists():
                n += 1
                final = self.downloads / f"{stem}-{n}{final.suffix}"
            shutil.move(str(staged), str(final))
            self._log("browser_download", file=final.name, type=kind, bytes=final.stat().st_size)
            return final, kind
        except BrowserError:
            shutil.rmtree(partial, ignore_errors=True)
            raise

    def show(self, path: Path) -> str:
        return path.relative_to(self.task_dir).as_posix()
