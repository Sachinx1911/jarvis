"""jarvis preflight [--offline]: the live chain checks with one summary line (PLAN.md 18.1, row 06).

Checks, each printed as `name: OK/NOT OK - detail`:
  providers   the approved providers answer (jarvis health); skipped with --offline
  stop        the emergency stop is released
  database    the database opens
  truth       the index matches the truth files (jarvis verify)
  memory      the memory index is readable (count)
  daemon      the app lock state (reported)
  xray        the x-ray kit diag (reported, not required)
Exit 1 when a required check fails. "Done" means preflight passed (PLAN.md 20).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, TextIO

REPORT_ONLY = {"daemon", "xray"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def line(self) -> str:
        state = "OK" if self.ok else ("INFO" if not self.required else "NOT OK")
        return f"{self.name}: {state} - {self.detail}"


def register(sub) -> dict[str, Callable]:
    p = sub.add_parser("preflight", help="live chain checks (providers, stop, database, truth, memory, daemon, xray) with one summary line")
    p.add_argument("--offline", action="store_true", help="skip the provider calls")
    return {"preflight": cmd_preflight}


def _providers(config, offline: bool) -> list[Check]:
    if offline:
        return [Check("providers", True, "skipped (--offline)")]
    from jarvis.providers import make_provider

    out = []
    for name in config.routing.get("approved_providers") or []:
        try:
            h = make_provider(name, config).health()
            out.append(Check(f"provider {name}", h.ok, h.detail))
        except Exception as e:  # noqa: BLE001 (a broken adapter is a failed check, not a crash)
            out.append(Check(f"provider {name}", False, f"{type(e).__name__}: {e}"))
    return out or [Check("providers", False, "no approved providers in config/routing.yaml")]


def run_checks(offline: bool = False, diag: Callable[[], dict] | None = None) -> list[Check]:
    from jarvis.control.stop import StopSwitch
    from jarvis.core.rebuild import verify
    from jarvis.core.runtime import open_runtime

    checks: list[Check] = []
    try:
        rt = open_runtime()
    except Exception as e:  # noqa: BLE001
        return [Check("database", False, f"could not open: {type(e).__name__}: {e}")]
    try:
        checks += _providers(rt.config, offline)
        engaged = StopSwitch(rt.paths.data).engaged()
        checks.append(Check("stop", not engaged, "emergency stop is ON (jarvis resume)" if engaged else "released"))
        checks.append(Check("database", True, str(rt.paths.db)))
        try:
            report = verify(rt.paths.home, rt.store)
            checks.append(Check("truth", report.ok, report.summary() + f" ({report.counts()['checked']} rows checked)"))
        except Exception as e:  # noqa: BLE001
            checks.append(Check("truth", False, f"verify failed: {type(e).__name__}: {e}"))
        try:
            n = rt.store.conn.execute("SELECT COUNT(*) FROM memory_index WHERE status='active'").fetchone()[0]
            checks.append(Check("memory", True, f"{n} active memories indexed"))
        except Exception as e:  # noqa: BLE001
            checks.append(Check("memory", False, f"index unreadable: {type(e).__name__}: {e}"))
        lock = rt.paths.data / "app.lock"
        checks.append(Check("daemon", True, "app lock present (jarvis app or daemon running)" if lock.exists()
                            else "no app lock (daemon not running)", required=False))
        if diag is None:
            from jarvis.xray.live import kit_diag

            diag = kit_diag
        d = diag()
        from jarvis.xray.live import problems_text

        checks.append(Check("xray", bool(d.get("ready")), "kit ready" if d.get("ready") else problems_text(d), required=False))
        failed = [c.name for c in checks if c.required and not c.ok]
        rt.audit.write("preflight", source="cli", offline=offline, ok=not failed, failed=failed,
                       checks=len(checks))
    finally:
        rt.close()
    return checks


def summary_line(checks: list[Check]) -> str:
    failed = [c.name for c in checks if c.required and not c.ok]
    if failed:
        return f"preflight: NOT OK - {len(failed)} of {len(checks)} checks failed: {', '.join(failed)}"
    info = [c.name for c in checks if not c.required and not c.ok]
    return f"preflight: OK - {len(checks)} checks passed" + (f" ({', '.join(info)} reported only)" if info else "")


def cmd_preflight(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory=None) -> int:
    checks = run_checks(offline=bool(getattr(args, "offline", False)))
    for c in checks:
        print(c.line(), file=out)
    print(summary_line(checks), file=out)
    return 0 if all(c.ok for c in checks if c.required) else 1
