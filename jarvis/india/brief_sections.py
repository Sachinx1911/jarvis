"""Morning-brief sections for India data (BriefSection protocol in jarvis/proactive/brief.py).

The lead wires them with one call at import time of the proactive integration:

    from jarvis.india.brief_sections import register_india_sections; register_india_sections()

Sections fetch only fixed official URLs from config/india.yaml, use no model, and return None
(left out of the brief) when they have nothing to say or are switched off. Tests pass a
fetcher through ctx.extras["india_fetcher"] (or to register_india_sections).

The brief is sent over Telegram. It shows NAVs, public alerts, headlines, and for bills only
biller, amount and due date; wallet lines show type, holder and expiry, never numbers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from jarvis.india import feeds
from jarvis.india.config import load_india_config, section, tz
from jarvis.india.net import Fetcher, FetchError, UrlFetcher
from jarvis.india.text import format_inr


class _Base:
    key = title = ""
    order = 0

    def __init__(self, fetcher: Fetcher | None = None, cfg: dict[str, Any] | None = None,
                 secret: Callable[[str], str | None] | None = None):
        self._fetcher, self._cfg, self._secret = fetcher, cfg, secret

    def cfg(self) -> dict[str, Any]:
        return self._cfg if self._cfg is not None else load_india_config()

    def fetcher(self, ctx) -> Fetcher:
        return ctx.extras.get("india_fetcher") or self._fetcher or UrlFetcher()

    def secret(self, name: str) -> str | None:
        if self._secret is not None:
            return self._secret(name)
        from jarvis.secrets import get_secret
        return get_secret(name)

    def now(self, ctx) -> datetime:
        cfg = self.cfg()
        return ctx.now if ctx.now.tzinfo else ctx.now.replace(tzinfo=tz(cfg))


class AlertsSection(_Base):
    key, title, order = "india_alerts", "Weather and disaster alerts", 12

    def render(self, ctx) -> str | None:
        cfg = self.cfg()
        lines: list[str] = []
        alerts_cfg = section(cfg, "alerts")
        if alerts_cfg.get("enabled", True):
            try:
                shown, others = feeds.sachet_alerts(self.fetcher(ctx), alerts_cfg, self.now(ctx))
                limit = int(alerts_cfg.get("max_items") or 5)
                for item in shown[:limit]:
                    when = f"{item.published.astimezone(tz(cfg)):%d %b %H:%M} " if item.published else ""
                    lines.append(f"- {when}{item.title}" + (f" ({item.author})" if item.author else ""))
                if len(shown) > limit:
                    lines.append(f"- ... and {len(shown) - limit} more (sachet.ndma.gov.in)")
                if others:
                    lines.append(f"- {others} other alert(s) elsewhere in the state.")
            except (FetchError, ValueError) as e:
                lines.append(f"- Sachet alerts unavailable: {e}")
        imd_cfg = section(cfg, "imd")
        if imd_cfg.get("enabled"):
            key, jwt = self.secret("imd_api_key"), self.secret("imd_jwt")
            if not key or not jwt:
                lines.append("- IMD warnings skipped: IMD key not set up (jarvis imd set-key / set-token).")
            else:
                try:
                    for w in feeds.imd_warnings(self.fetcher(ctx), imd_cfg, key, jwt):
                        day = "today" if w.day == 1 else "tomorrow"
                        lines.append(f"- IMD {w.color} {day}, {w.district}: {', '.join(w.warnings)}")
                except (FetchError, ValueError) as e:
                    lines.append(f"- IMD warnings unavailable: {e}")
        if not lines and alerts_cfg.get("enabled", True):
            return "No alerts for your area."
        return "\n".join(lines) or None


class NavSection(_Base):
    key, title, order = "india_nav", "Mutual fund NAVs", 45

    def render(self, ctx) -> str | None:
        from jarvis.india.nav import NavService, format_quotes

        cfg = self.cfg()
        if not section(cfg, "nav").get("enabled", True):
            return None
        svc = NavService(ctx.conn, cfg, self.fetcher(ctx), lambda: self.now(ctx))
        if not svc.schemes():
            return None
        error = svc.refresh()
        text = format_quotes(svc.quotes())
        return text + (f"\n({error}; showing the last saved NAVs)" if error else "")


class DueSoonSection(_Base):
    key, title, order = "india_due", "Bills and documents due", 35

    def render(self, ctx) -> str | None:
        from jarvis.india.bills import BillStore
        from jarvis.india.wallet import WalletStore

        cfg = self.cfg()
        zone, today = tz(cfg), self.now(ctx).date()
        lines = []
        for b in BillStore(ctx.conn, zone, cfg=section(cfg, "bills")).due_within(today, 7):
            late = " (OVERDUE)" if b.due_date and b.due_date < today else ""
            lines.append(f"- {b.biller} {format_inr(b.amount_paise)} due {b.due_date:%d %b}{late}"
                         + (" [AutoPay]" if b.autopay else ""))
        wallet = WalletStore(ctx.conn, ctx.home, zone, cfg=section(cfg, "wallet"))
        for r in wallet.list():
            if r.expiry and (r.expiry - today).days <= r.lead_days:
                what = "EXPIRED" if r.expiry < today else "expires"
                lines.append(f"- {(r.label or r.doc_type).replace('_', ' ')} of {r.holder} {what} {r.expiry:%d %b %Y}")
        return "\n".join(lines) or None


class NewsSection(_Base):
    key, order = "india_news", 80

    @property
    def title(self) -> str:  # type: ignore[override]
        return f"Marathi headlines ({section(self.cfg(), 'news').get('source') or 'news'})"

    def render(self, ctx) -> str | None:
        news_cfg = section(self.cfg(), "news")
        if not news_cfg.get("enabled"):
            return None
        try:
            items = feeds.news_headlines(self.fetcher(ctx), news_cfg)
        except (FetchError, ValueError) as e:
            return f"Headlines unavailable: {e}"
        return "\n".join(f"- {i.title}" for i in items) or None


def india_sections(fetcher: Fetcher | None = None, cfg: dict[str, Any] | None = None,
                   secret: Callable[[str], str | None] | None = None) -> list[_Base]:
    return [AlertsSection(fetcher, cfg, secret), DueSoonSection(fetcher, cfg, secret),
            NavSection(fetcher, cfg, secret), NewsSection(fetcher, cfg, secret)]


def register_india_sections(fetcher: Fetcher | None = None, cfg: dict[str, Any] | None = None,
                            secret: Callable[[str], str | None] | None = None) -> None:
    from jarvis.proactive.brief import register_section

    for s in india_sections(fetcher, cfg, secret):
        register_section(s)
