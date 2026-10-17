"""CLI for Phase 4: schedule, trigger, heartbeat, brief, remind, telegram, daemon.

Integration (jarvis/cli.py):
    from jarvis import cli_proactive
    cli_proactive.register(sub)                       # in build_parser()
    if args.command in cli_proactive.COMMANDS:        # in main(), before the handlers dict
        return cli_proactive.handle(args, out, inp)
"""

from __future__ import annotations

import argparse
import getpass
import json
import threading
from typing import Callable, TextIO

from jarvis.control.audit import AuditLog
from jarvis.paths import default_paths
from jarvis.proactive.notify import make_notifier, telegram_sender
from jarvis.proactive.reminders import ReminderStore, parse_reminder
from jarvis.proactive.schedule_parse import KINDS, OUTPUTS, CronError, ScheduleDraft, ScheduleParseError, normalize_cron
from jarvis.proactive.scheduler import PendingApprovals, ScheduleStore
from jarvis.proactive.service import Proactive
from jarvis.proactive.settings import load_settings
from jarvis.secrets import get_secret, set_secret

PROVIDERS = ["claude_code", "anthropic", "fake"]
COMMANDS = ("schedule", "trigger", "heartbeat", "brief", "remind", "telegram", "daemon")


def register(sub: argparse._SubParsersAction) -> None:
    sch = sub.add_parser("schedule", help="skill, agent and prompt schedules")
    sch.add_argument("action", choices=["add", "list", "pause", "resume", "run-now", "delete", "archive", "unarchive", "runs", "approvals"])
    sch.add_argument("text", nargs="*", help="add: what and when, e.g. 'every Monday at 9 project summary'; "
                                             "approvals: 'approve <id>' or 'deny <id>'; others: schedule id")
    sch.add_argument("--kind", choices=KINDS, default="prompt")
    sch.add_argument("--target", default="", help="skill or agent name (for --kind skill/agent)")
    sch.add_argument("--output", choices=OUTPUTS, default=None)
    sch.add_argument("--cron", default=None, help="exact 5-field cron instead of reading the time from the text")
    sch.add_argument("--max-calls", type=int, default=None, help="budget: model calls per run")
    sch.add_argument("--yes", action="store_true", help="save without asking (scripts)")
    sch.add_argument("--forever", action="store_true",
                     help="delete: remove an archived schedule for good (asks; logged as your act)")
    sch.add_argument("--no-model", action="store_true", help="read the time with the rules only")
    sch.add_argument("--dismiss", type=int, default=None, help="approvals: dismiss this pending item")
    sch.add_argument("--provider", choices=PROVIDERS, default=None)

    tr = sub.add_parser("trigger", help="event triggers: do something when something happens")
    tr.add_argument("action", choices=["add", "list", "pause", "resume", "delete", "archive", "unarchive", "test", "runs"])
    tr.add_argument("text", nargs="*", help="add: what to watch and what to do, e.g. 'when a new file arrives in "
                                            "workspace/inbox summarize it'; others: trigger id")
    tr.add_argument("--kind", choices=["notify", "prompt", "skill", "agent"], default=None,
                    help="what runs when it fires (default: read from the text)")
    tr.add_argument("--target", default="", help="skill or agent name (for --kind skill/agent)")
    tr.add_argument("--input", default="", help="the prompt or task text (instead of the one in the sentence)")
    tr.add_argument("--output", choices=OUTPUTS, default=None)
    tr.add_argument("--every", type=float, default=None, help="minutes between checks (web sources have a minimum)")
    tr.add_argument("--cooldown", type=float, default=None, help="minutes between two runs")
    tr.add_argument("--product", default="", help="web_price: the exact product name on the store page")
    tr.add_argument("--yes", action="store_true", help="save without asking (scripts)")
    tr.add_argument("--forever", action="store_true",
                    help="delete: remove an archived trigger for good (asks; logged as your act)"),
    tr.add_argument("--fire", action="store_true", help="test: check now for real (new items fire)")
    tr.add_argument("--provider", choices=PROVIDERS, default=None)

    hb = sub.add_parser("heartbeat", help="run the heartbeat check")
    hb.add_argument("action", choices=["run-once"])
    hb.add_argument("--send", action="store_true", help="send the message (if any) through the notifier")
    hb.add_argument("--provider", choices=PROVIDERS, default=None)

    br = sub.add_parser("brief", help="build the daily brief now")
    br.add_argument("--send", action="store_true", help="send it through the notifier instead of printing")

    rem = sub.add_parser("remind", help="add, list or cancel reminders")
    rem.add_argument("text", nargs="*", help="e.g. 'in 10 minutes call back' or 'udya sakali 9 la bill bhar'")
    rem.add_argument("--list", action="store_true")
    rem.add_argument("--cancel", type=int, default=None)

    tg = sub.add_parser("telegram", help="Telegram bot")
    tg.add_argument("action", choices=["run", "set-token", "status", "test"])
    tg.add_argument("--provider", choices=PROVIDERS, default=None)

    d = sub.add_parser("daemon", help="run schedules, reminders, heartbeat and the Telegram bot together")
    d.add_argument("--no-telegram", action="store_true")
    d.add_argument("--provider", choices=PROVIDERS, default=None)


def _proactive(args: argparse.Namespace, out: TextIO, notify: bool = True) -> Proactive:
    settings = load_settings()
    notifier = make_notifier(settings, AuditLog(default_paths().audit_log), out) if notify else None
    return Proactive(settings, notifier=notifier, provider_override=getattr(args, "provider", None))


def _ask(out: TextIO, inp: TextIO, question: str) -> bool:
    out.write(question + " [y/N] ")
    out.flush()
    return inp.readline().strip().lower() in ("y", "yes", "ho", "हो")


def cmd_schedule(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    approving = args.action == "approvals" and args.text[:1] == ["approve"]
    p = _proactive(args, out, notify=args.action == "run-now" or approving)  # replay results go to the notifier
    text = " ".join(args.text).strip()
    rt = p.open_rt()
    try:
        store = ScheduleStore(rt.store.conn)
        if args.action == "list":
            items = store.list()
            for s in items:
                print(s.line(), file=out)
            if not items:
                print("No schedules. Add one: jarvis schedule add \"every Monday at 9 project summary\"", file=out)
            return 0
        if args.action == "approvals":
            pending = PendingApprovals(rt.store.conn)
            verb, _, rest = text.partition(" ")
            if verb in ("approve", "deny"):
                pid = rest.strip().lstrip("#")
                if not pid.isdigit():
                    print(f"Usage: jarvis schedule approvals {verb} <id>", file=out)
                    return 2
                item = pending.get(int(pid))
                if item is None or item["status"] != "pending":
                    print(f"No pending approval #{pid}." if item is None else f"#{pid} is already {item['status']}.",
                          file=out)
                    return 1
                if verb == "approve" and not args.yes:
                    print(f"#{pid} from {item['schedule_id']} ({item['created_at'][:16]}): {item['tool']} "
                          f"[{item['tier']}]\n{json.dumps(item['arguments'], ensure_ascii=False, indent=2)}", file=out)
                    if not _ask(out, inp, "Run this exact call once now?"):
                        print("Not run; still pending.", file=out)
                        return 0
                rt.close()
                rt = None
                r = p.deny_pending(int(pid), "cli") if verb == "deny" else p.approve_pending(int(pid), "cli")
                print(r.message, file=out)
                return 0 if r.status in ("executed", "denied") else 1
            if args.dismiss is not None:
                print("Dismissed." if pending.dismiss(args.dismiss) else "No such pending item.", file=out)
                return 0
            for a in pending.list():
                print(f"#{a['id']} {a['created_at'][:16]} {a['schedule_id']} {a['tool']} [{a['tier']}] "
                      f"{a['arguments']} ({a['reason']})", file=out)
            return 0
        if args.action in ("pause", "resume", "delete", "archive", "unarchive", "runs", "run-now"):
            if not text or not store.get(text):
                print(f"No schedule {text or '(give an id, see: jarvis schedule list)'}.", file=out)
                return 1
            if args.action == "runs":
                for r in store.runs(text):
                    print(f"{r['started_at'][:16]} {r['trigger']:<8} {r['status']:<15} calls={r['model_calls']} "
                          f"{(r['detail'] or '')[:80]}", file=out)
                return 0
            if args.action in ("delete", "archive"):
                # Law 2: "delete" archives. Only `delete --forever` on an archived schedule removes the row,
                # and only after Sachin says yes here; both are audited.
                if args.action == "delete" and args.forever:
                    if not store.get(text).archived:
                        print(f"{text} is still live; archive it first (jarvis schedule archive {text}).", file=out)
                        return 1
                    if not _ask(out, inp, f"Delete {text} for ever? Its runs stay in the log, the schedule itself is gone."):
                        print("Kept.", file=out)
                        return 0
                    store.delete_forever(text)
                    rt.audit.write("schedule_delete_forever", schedule_id=text, source="cli", by="sachin")
                    print(f"{text}: deleted for ever.", file=out)
                    return 0
                if not args.yes and not _ask(out, inp, f"Archive {text}? (it stops and leaves the list; nothing is deleted)"):
                    print("Kept.", file=out)
                    return 0
                store.archive(text, p.now())
                rt.audit.write("schedule_archive", schedule_id=text, source="cli")
                print(f"{text}: archived. Reopen with: jarvis schedule unarchive {text}", file=out)
                return 0
            elif args.action == "unarchive":
                store.unarchive(text, p.now())
                rt.audit.write("schedule_unarchive", schedule_id=text, source="cli")
                print(f"{text}: reopened (paused; resume it when ready).", file=out)
                return 0
            elif args.action == "run-now":
                rt.close()
                rt = None
                r = p.runner().run(text, "run-now")
                print(f"{text}: {r.status}", file=out)
                if r.text:
                    print(r.text, file=out)
                return 0 if r.status in ("ok", "quiet") else 1
            else:
                store.set_enabled(text, args.action == "resume", p.now())
            rt.audit.write(f"schedule_{args.action.replace('-', '_')}", schedule_id=text, source="cli")
            print(f"{text}: {args.action} done.", file=out)
            return 0
        # add
        if not text and args.kind not in ("brief", "heartbeat"):
            print("Say what and when, e.g. jarvis schedule add \"every Monday at 9 project summary\"", file=out)
            return 2
        defaults = {"kind": args.kind, "target": args.target, "output": args.output or p.default_output}
        if args.max_calls:
            defaults["budget"] = {"max_model_calls": args.max_calls}
        try:
            if args.cron:
                cron = normalize_cron(args.cron)
                draft = ScheduleDraft(name=(text or args.kind)[:40], kind=args.kind, input=text, cron=cron,
                                      timezone=p.settings.tz_name, description=f"cron {cron}", target=args.target,
                                      output=defaults["output"], budget=defaults.get("budget", {}), source="explicit")
            else:
                draft = p.parser(rt, use_model=not args.no_model).parse(text, defaults)
        except (ScheduleParseError, CronError) as e:
            print(str(e), file=out)
            return 1
        print(draft.show(p.now()), file=out)
        if not args.yes and not _ask(out, inp, "Save this schedule?"):
            print("Not saved.", file=out)
            return 0
        try:
            s = p.save(draft, "cli")
        except ValueError as e:
            print(f"Not saved: {e}", file=out)
            return 1
        print(f"Saved as {s.id}. It runs while `jarvis daemon` is running.", file=out)
        return 0
    finally:
        if rt is not None:
            rt.close()


def cmd_trigger(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    from jarvis.proactive.trigger_parse import TriggerInvalid, TriggerParseError
    from jarvis.proactive.triggers import TriggerStore

    p = _proactive(args, out, notify=args.action == "test" and args.fire)
    text = " ".join(args.text).strip()
    if args.action == "add":
        if not text:
            print("Say what to watch and what to do, e.g. jarvis trigger add \"when a new file arrives in "
                  "workspace/inbox summarize it\"", file=out)
            return 2
        defaults: dict = {"output": args.output or p.default_output, "target": args.target, "input": args.input,
                          "product": args.product}
        if args.kind:
            defaults["action"] = args.kind
        if args.every:
            defaults["every_s"] = int(args.every * 60)
        if args.cooldown is not None:
            defaults["cooldown_s"] = int(args.cooldown * 60)
        try:
            draft = p.draft_trigger(text, defaults)
        except (TriggerParseError, TriggerInvalid) as e:
            print(str(e), file=out)
            return 1
        print(draft.show(), file=out)
        if not args.yes and not _ask(out, inp, "Save this trigger?"):
            print("Not saved.", file=out)
            return 0
        try:
            t = p.save_trigger(draft, "cli")
        except TriggerInvalid as e:
            print(f"Not saved: {e}", file=out)
            return 1
        print(f"Saved as {t.id}. It is checked while `jarvis daemon` is running.", file=out)
        return 0
    rt = p.open_rt()
    try:
        store = TriggerStore(rt.store.conn)
        if args.action == "list":
            items = store.list()
            for t in items:
                print(t.line(), file=out)
                if t.last_status in ("error", "waiting") and t.last_detail:
                    print(f"    {t.last_status}: {t.last_detail}", file=out)
            if not items:
                print("No triggers. Add one: jarvis trigger add \"when a new file arrives in workspace/inbox "
                      "summarize it\"", file=out)
            return 0
        if not text or not store.get(text):
            print(f"No trigger {text or '(give an id, see: jarvis trigger list)'}.", file=out)
            return 1
        if args.action == "runs":
            for f in store.fires(text):
                print(f"{f['started_at'][:16]} {f['status']:<8} events={f['events']} calls={f['model_calls']} "
                      f"pending={f['pending_approvals']} {(f['detail'] or '').splitlines()[0][:80] if f['detail'] else ''}",
                      file=out)
            return 0
        if args.action == "test":
            rt.close()
            rt = None
            r = p.trigger_engine().poll(text, dry_run=not args.fire)
            print(f"{text}: {r.status}" + (f" - {r.detail}" if r.detail else ""), file=out)
            for e in r.events[:20]:
                print(f"  - {e.summary}", file=out)
            if r.fire_status:
                print(f"Action: {r.fire_status}", file=out)
                if r.text and p.notifier is None:
                    print(r.text, file=out)
            if not args.fire:
                print("(dry run: nothing was marked or run; add --fire to check for real)", file=out)
            return 0 if r.status not in ("error", "unknown") else 1
        if args.action in ("delete", "archive"):
            if args.action == "delete" and args.forever:
                if not store.get(text).archived:
                    print(f"{text} is still live; archive it first (jarvis trigger archive {text}).", file=out)
                    return 1
                if not _ask(out, inp, f"Delete {text} for ever?"):
                    print("Kept.", file=out)
                    return 0
                store.delete_forever(text)
                rt.audit.write("trigger_delete_forever", trigger_id=text, source="cli", by="sachin")
                print(f"{text}: deleted for ever.", file=out)
                return 0
            if not args.yes and not _ask(out, inp, f"Archive {text}? (it stops and leaves the list; nothing is deleted)"):
                print("Kept.", file=out)
                return 0
            store.archive(text, p.now())
            rt.audit.write("trigger_archive", trigger_id=text, source="cli")
            print(f"{text}: archived. Reopen with: jarvis trigger unarchive {text}", file=out)
            return 0
        elif args.action == "unarchive":
            store.unarchive(text, p.now())
        else:
            store.set_enabled(text, args.action == "resume", p.now())
        rt.audit.write(f"trigger_{args.action}", trigger_id=text, source="cli")
        print(f"{text}: {args.action} done.", file=out)
        return 0
    finally:
        if rt is not None:
            rt.close()


def cmd_heartbeat(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    p = _proactive(args, out, notify=args.send)
    result = p.heartbeat_once()
    if result.spoke:
        if args.send and p.notifier:
            p.notifier.send(result.message, "Jarvis")
        else:
            print(result.message, file=out)
    else:
        print(f"Nothing to say ({result.reason}).", file=out)
    return 0


def cmd_brief(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    p = _proactive(args, out, notify=args.send)
    text = p.brief_text()
    if args.send and p.notifier:
        print(f"Sent via {p.notifier.send(text, 'Daily brief')}.", file=out)
    else:
        print(text, file=out)
    return 0


def cmd_remind(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    p = _proactive(args, out, notify=False)
    rt = p.open_rt()
    try:
        store = ReminderStore(rt.store.conn, rt.audit)
        if args.cancel is not None:
            print("Cancelled." if store.cancel(args.cancel) else "No pending reminder with that number.", file=out)
            return 0
        if args.list or not args.text:
            for r in store.pending():
                print(f"#{r.id} {r.due_at:%a %d %b %H:%M} {r.text}", file=out)
            return 0
        parsed = parse_reminder(" ".join(args.text), p.now())
        if not parsed:
            print("I could not read when. Try: 'in 10 minutes call back', 'tomorrow at 9 pay rent', "
                  "'udya sakali 8 la doctor'.", file=out)
            return 1
        r = store.add(parsed.text, parsed.due, "cli", p.now())
        print(f"Reminder #{r.id} set for {r.due_at:%a %d %b %H:%M}: {r.text}", file=out)
        print("It is sent while `jarvis daemon` is running.", file=out)
        return 0
    finally:
        rt.close()


def _bot_parts(args: argparse.Namespace, out: TextIO):
    from jarvis.telegram.core import BotCore

    settings = load_settings()
    token = get_secret(settings.telegram_secret)
    uid = settings.telegram_user_id
    missing = []
    if not token:
        missing.append("bot token (jarvis telegram set-token)")
    if not uid:
        missing.append("allowed user id (config/local.yaml: proactive_file.telegram.allowed_user_id)")
    if missing:
        print("Telegram is not set up: " + "; ".join(missing), file=out)
        return None
    p = Proactive(settings, notifier=make_notifier(settings, AuditLog(default_paths().audit_log), out),
                  provider_override=getattr(args, "provider", None))
    timeout = float(settings.section("telegram").get("approval_timeout_seconds", 300))
    return p, BotCore(p, uid), token, timeout


def cmd_telegram(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    settings = load_settings()
    if args.action == "set-token":
        value = getpass.getpass("Paste the bot token from @BotFather (input hidden): ").strip()
        if not value:
            print("Nothing entered; unchanged.", file=out)
            return 1
        set_secret(settings.telegram_secret, value)
        AuditLog(default_paths().audit_log).write("secret_set", name=settings.telegram_secret)
        print("Bot token saved in the OS secret store.", file=out)
        return 0
    if args.action == "status":
        print(f"bot token: {'set' if get_secret(settings.telegram_secret) else 'NOT SET (jarvis telegram set-token)'}",
              file=out)
        print(f"allowed user id: {settings.telegram_user_id or 'NOT SET (config/local.yaml)'}", file=out)
        return 0
    if args.action == "test":
        sender = telegram_sender(settings)
        if sender is None:
            print("Telegram is not set up (jarvis telegram status).", file=out)
            return 1
        sender.send("Jarvis test message. Telegram works.")
        print("Sent.", file=out)
        return 0
    parts = _bot_parts(args, out)
    if parts is None:
        return 2
    from jarvis.telegram.bot import run_bot

    _, core, token, timeout = parts
    print("Telegram bot running (long polling). Ctrl+C to stop.", file=out)
    run_bot(core, token, timeout)
    return 0


def cmd_daemon(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    parts = None if args.no_telegram else _bot_parts(args, out)
    p = parts[0] if parts else _proactive(args, out)
    added = p.ensure_default_schedules()
    if added:
        print(f"Created default schedules: {', '.join(added)} (pause with: jarvis schedule pause <id>)", file=out)
    svc = p.service()
    for r in svc.catch_up():
        print(f"Catch-up run {r.schedule_id}: {r.status}", file=out)
    svc.start()
    p.fire_reminders()
    print("Scheduler running.", file=out)
    try:
        if parts:
            from jarvis.telegram.bot import run_bot

            _, core, token, timeout = parts
            print("Telegram bot running (long polling). Ctrl+C to stop.", file=out)
            run_bot(core, token, timeout)
        else:
            print("Telegram off. Ctrl+C to stop.", file=out)
            stop = threading.Event()
            try:
                while not stop.wait(1):
                    pass
            except KeyboardInterrupt:
                pass
    finally:
        svc.shutdown()
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace, TextIO, TextIO], int]] = {
    "schedule": cmd_schedule, "trigger": cmd_trigger, "heartbeat": cmd_heartbeat, "brief": cmd_brief, "remind": cmd_remind,
    "telegram": cmd_telegram, "daemon": cmd_daemon,
}


def handle(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    return HANDLERS[args.command](args, out, inp)
