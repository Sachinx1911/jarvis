"""`jarvis approvals`: standing approvals that Sachin creates, lists and revokes.

  jarvis approvals grant write_file --rule path=glob:notes/*.md --rule content=max_chars:5000 --days 30 --uses 50
  jarvis approvals list [--all]
  jarvis approvals revoke g-1a2b3c4d
  jarvis approvals uses g-1a2b3c4d

A rule is ARG=KIND:VALUE with KIND one of glob, domain, max_chars, equals, one_of (values
separated by |) or any (no value). Every argument the tool call uses needs a rule, or the
grant does not match. Only T1/T2 tools; never send, pay, delete (T3) or T4.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Callable, TextIO

from jarvis.control.grants import KINDS, GrantError, GrantStore


def register(sub) -> dict[str, Callable]:
    ap = sub.add_parser("approvals", help="standing approvals: grant, list, revoke, uses")
    ap.add_argument("action", choices=["grant", "list", "revoke", "uses"])
    ap.add_argument("target", nargs="?", default="", help="tool name (grant) or grant id (revoke, uses)")
    ap.add_argument("--rule", action="append", default=[], metavar="ARG=KIND:VALUE",
                    help=f"argument rule; KIND: {', '.join(KINDS)} (repeat for each argument)")
    ap.add_argument("--days", type=float, default=7.0, help="expiry in days (max 90)")
    ap.add_argument("--uses", type=int, default=10, help="maximum number of uses (max 1000)")
    ap.add_argument("--note", default="")
    ap.add_argument("--all", action="store_true", help="list also expired, used-up and revoked grants")
    return {"approvals": cmd_approvals}


def parse_rule(text: str) -> tuple[str, dict]:
    arg, sep, rest = text.partition("=")
    if not sep or not arg.strip():
        raise GrantError(f"rule {text!r} must look like ARG=KIND:VALUE")
    kind, _, value = rest.partition(":")
    kind = kind.strip()
    if kind == "any":
        return arg.strip(), {"any": True}
    if kind == "one_of":
        return arg.strip(), {"one_of": [v.strip() for v in value.split("|") if v.strip()]}
    if kind == "max_chars":
        try:
            return arg.strip(), {"max_chars": int(value)}
        except ValueError:
            raise GrantError("max_chars needs a number")
    return arg.strip(), {kind: value}


def _tiers(rt) -> dict[str, tuple[str, bool]]:
    from jarvis.web.data import tools_json

    return {t["name"]: (t["tier"], t["enabled"]) for t in tools_json(rt)["tools"]}


def _show(g, now: float) -> str:
    d = g.public(now)
    rules = ", ".join(f"{a} {k}={json.dumps(v, ensure_ascii=False)}" for a, r in g.constraints.items()
                      for k, v in r.items())
    return (f"{g.id}  {g.tool} ({g.tier})  [{d['status']}]  uses {g.uses}/{g.max_uses}  expires {d['expires']}\n"
            f"    rules: {rules}" + (f"\n    note: {g.note}" if g.note else ""))


def cmd_approvals(args: argparse.Namespace, out: TextIO, inp: TextIO, approver_factory) -> int:
    from jarvis.core.runtime import open_runtime
    from jarvis.tools.catalog import file_roots

    rt = open_runtime()
    try:
        store = GrantStore(rt.store.conn, file_roots(rt.paths.home, rt.config.tools))
        now = time.time()
        if args.action == "list":
            grants = store.list(active_only=not args.all)
            for g in grants:
                print(_show(g, now), file=out)
            if not grants:
                print("No standing approvals." if args.all else "No active standing approvals (--all shows old ones).",
                      file=out)
            return 0
        if not args.target:
            print("Give a tool name (grant) or a grant id (revoke, uses).", file=out)
            return 2
        if args.action == "revoke":
            try:
                store.revoke(args.target)
            except KeyError:
                print(f"No grant {args.target}.", file=out)
                return 1
            rt.audit.write("grant_revoked", source="cli", grant_id=args.target)
            print(f"Revoked {args.target}.", file=out)
            return 0
        if args.action == "uses":
            if not store.get(args.target):
                print(f"No grant {args.target}.", file=out)
                return 1
            uses = store.uses(args.target)
            for u in uses:
                print(f"  {u['ts']}  task={u['task_id'] or '-'}  {json.dumps(u['arguments'], ensure_ascii=False)[:200]}",
                      file=out)
            if not uses:
                print("  Not used yet.", file=out)
            return 0
        # grant
        tiers = _tiers(rt)
        if args.target not in tiers:
            print(f"Unknown tool {args.target}.", file=out)
            return 1
        tier, enabled = tiers[args.target]
        if not enabled:
            print(f"{args.target} is disabled.", file=out)
            return 1
        try:
            rules = dict(parse_rule(r) for r in args.rule)
            g = store.create(args.target, tier, rules, args.days, args.uses, args.note, created_by="cli")
        except GrantError as e:
            rt.audit.write("grant_refused", source="cli", tool=args.target, detail=str(e))
            print(f"Not granted: {e}", file=out)
            return 1
        rt.audit.write("grant_created", source="cli", grant_id=g.id, tool=g.tool, tier=g.tier,
                       constraints=g.constraints, expires=g.expires, max_uses=g.max_uses)
        print("Granted. Jarvis will run this without asking while every argument matches:", file=out)
        print(_show(g, now), file=out)
        return 0
    finally:
        rt.close()
