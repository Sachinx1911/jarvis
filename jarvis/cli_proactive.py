"""CLI for Phase 4: schedule, heartbeat, brief, remind, telegram, daemon.

Integration (jarvis/cli.py):
    from jarvis import cli_proactive
    cli_proactive.register(sub)                       # in build_parser()
    if args.command in cli_proactive.COMMANDS:        # in main(), before the handlers dict
        return cli_proactive.handle(args, out, inp)
"""

from __future__ import annotations

import argparse
import getpass
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
COMMANDS = ("schedule", "heartbeat", "brief", "remind", "telegram", "daemon")


def register(sub: argparse._SubParsersAction) -> None:
    sch = sub.add_parser("schedule", help="skill, agent and prompt schedules")
    sch.add_argument("action", choices=["add", "list", "pause", "resume", "run-now", "delete", "runs", "approvals"])
    sch.add_argument("text", nargs="*", help="add: what and when, e.g. 'every Monday at 9 project summary'; "
                                             "others: schedule id")
    sch.add_argument("--kind", choices=KINDS, default="prompt")
    sch.add_argument("--target", default="", help="skill or agent name (for --kind skill/agent)")
    sch.add_argument("--output", choices=OUTPUTS, default=None)
    sch.add_argument("--cron", default=None, help="exact 5-field cron instead of reading the time from the text")
    sch.add_argument("--max-calls", type=int, default=None, help="budget: model calls per run")
    sch.add_argument("--yes", action="store_true", help="save without asking (scripts)")
    sch.add_argument("--no-model", action="store_true", help="read the time with the rules only")
    sch.add_argument("--dismiss", type=int, default=None, help="approvals: dismiss this pending item")
    sch.add_argument("--provider", choices=PROVIDERS, default=None)

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
    p = _proactive(args, out, notify=args.action == "run-now")
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
            if args.dismiss is not None:
                print("Dismissed." if pending.dismiss(args.dismiss) else "No such pending item.", file=out)
                return 0
            for a in pending.list():
                print(f"#{a['id']} {a['created_at'][:16]} {a['schedule_id']} {a['tool']} [{a['tier']}] "
                      f"{a['arguments']} ({a['reason']})", file=out)
            return 0
        if args.action in ("pause", "resume", "delete", "runs", "run-now"):
            if not text or not store.get(text):
                print(f"No schedule {text or '(give an id, see: jarvis schedule list)'}.", file=out)
                return 1
            if args.action == "runs":
                for r in store.runs(text):
                    print(f"{r['started_at'][:16]} {r['trigger']:<8} {r['status']:<15} calls={r['model_calls']} "
                          f"{(r['detail'] or '')[:80]}", file=out)
                return 0
            if args.action == "delete":
                if not args.yes and not _ask(out, inp, f"Delete {text}?"):
                    print("Kept.", file=out)
                    return 0
                store.delete(text)
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
    "schedule": cmd_schedule, "heartbeat": cmd_heartbeat, "brief": cmd_brief, "remind": cmd_remind,
    "telegram": cmd_telegram, "daemon": cmd_daemon,
}


def handle(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    return HANDLERS[args.command](args, out, inp)
