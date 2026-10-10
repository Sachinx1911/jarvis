"""Telegram bot: python-telegram-bot, long polling (no server, no open port).

- Only the configured user ID is served. A gate in handler group -1 drops every other
  update before any handler sees it, and logs the attempt.
- Chat messages run in one worker thread (ChatSession is blocking and SQLite is
  thread-bound); the event loop stays free for buttons and /stop.
- /stop is handled on the event loop directly: it writes the stop file and denies any
  waiting approval. No model call, no queue.
- Approvals arrive as a message with the exact arguments and Approve/Deny buttons;
  no answer within the timeout counts as Deny.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from jarvis.telegram.approvals import TelegramApprover
from jarvis.telegram.core import HELP, BotCore
from jarvis.telegram.sender import chunks

log = logging.getLogger(__name__)
SEND_TIMEOUT = 30


def quiet_http_logs() -> None:
    """httpx logs every request URL at INFO, and Telegram URLs contain the bot token."""
    for name in ("httpx", "httpcore", "telegram.request"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _buttons(prefix: str, token: str, yes: str, no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(yes, callback_data=f"{prefix}:{token}:y"),
                                  InlineKeyboardButton(no, callback_data=f"{prefix}:{token}:n")]])


class JarvisBot:
    def __init__(self, core: BotCore, approval_timeout: float = 300.0, bot: Any = None):
        self.core = core
        self.chat_id = core.allowed_user_id  # private chat id == user id
        self.approval_timeout = approval_timeout
        self.bot = bot                       # telegram.Bot (set in post_init) or a test double
        self.loop: asyncio.AbstractEventLoop | None = None
        self.chat_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-chat")
        self._approval_msgs: dict[str, Any] = {}
        self.approver = TelegramApprover(core.broker, self._send_approval, approval_timeout, core.audit,
                                         self._approval_closed)

    # ---- building the application ----

    def build(self, token: str) -> Application:
        quiet_http_logs()

        async def post_init(app: Application) -> None:
            self.bot = app.bot
            self.loop = asyncio.get_running_loop()

        app = (Application.builder().token(token).concurrent_updates(True).post_init(post_init).build())
        self.register(app)
        return app

    def register(self, app: Application) -> None:
        app.add_handler(TypeHandler(Update, self.gate), group=-1)
        for name in ("start", "help", "stop", "resume", "tasks", "task", "pause", "cancel", "schedules", "schedule",
                     "schedule_pause", "schedule_resume", "schedule_run", "schedule_delete", "triggers", "trigger",
                     "trigger_pause", "trigger_resume", "trigger_delete", "approvals", "approve",
                     "deny", "dismiss",
                     "remind", "reminders", "brief", "cloud", "new"):
            app.add_handler(CommandHandler(name, self.on_command))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

    # ---- handlers ----

    async def gate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or not self.core.is_allowed(user.id):
            self.core.rejected(user.id if user else None, user.username if user else None,
                               "callback" if update.callback_query else "message")
            raise ApplicationHandlerStop  # nobody else gets an answer, or even a "no"

    async def _reply(self, update: Update, text: str, markup: Any = None) -> None:
        parts = chunks(text)
        for i, part in enumerate(parts):
            await update.effective_message.reply_text(part, reply_markup=markup if i == len(parts) - 1 else None)

    async def _in_chat_thread(self, fn, *args):
        self.loop = asyncio.get_running_loop()  # the chat thread sends approval messages through this loop
        return await self.loop.run_in_executor(self.chat_pool, fn, *args)

    async def on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.core.is_allowed(update.effective_user.id if update.effective_user else None):
            return  # the gate already logged it; this is a second lock on the door
        text = update.effective_message.text or ""
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lstrip("/").split("@")[0].lower()
        arg = arg.strip()
        c = self.core
        if cmd == "stop":  # first, and without any thread hop or model call
            await self._reply(update, c.cmd_stop(arg))
            return
        if cmd == "resume":
            await self._reply(update, c.cmd_resume())
            return
        if cmd in ("start", "help"):
            await self._reply(update, HELP)
            return
        if cmd == "schedule":
            shown, token = await asyncio.to_thread(c.draft_schedule, arg)
            await self._reply(update, shown, _buttons("sc", token, "Save", "Cancel") if token else None)
            return
        if cmd == "trigger":
            shown, token = await asyncio.to_thread(c.draft_trigger, arg)
            await self._reply(update, shown, _buttons("tr", token, "Save", "Cancel") if token else None)
            return
        if cmd in ("cloud", "new"):  # these touch the chat session, which lives in the chat thread
            fn = (lambda: c.cmd_cloud(arg)) if cmd == "cloud" else c.new_session
            await self._reply(update, await self._in_chat_thread(fn))
            return
        handlers = {
            "tasks": lambda: c.cmd_tasks(),
            "task": lambda: c.cmd_task(arg) if arg else "Usage: /task <id>",
            "pause": lambda: c.cmd_task_state(arg, "PAUSED") if arg else "Usage: /pause <task id>",
            "cancel": lambda: c.cmd_task_state(arg, "CANCELLED") if arg else "Usage: /cancel <task id>",
            "schedules": lambda: c.cmd_schedules(),
            "schedule_pause": lambda: c.cmd_schedule_action("pause", arg),
            "schedule_resume": lambda: c.cmd_schedule_action("resume", arg),
            "schedule_run": lambda: c.cmd_schedule_action("run", arg),
            "schedule_delete": lambda: c.cmd_schedule_action("delete", arg),
            "triggers": lambda: c.cmd_triggers(),
            "trigger_pause": lambda: c.cmd_trigger_action("pause", arg),
            "trigger_resume": lambda: c.cmd_trigger_action("resume", arg),
            "trigger_delete": lambda: c.cmd_trigger_action("delete", arg),
            "approvals": lambda: c.cmd_approvals(),
            "approve": lambda: c.cmd_approve(arg),
            "deny": lambda: c.cmd_deny(arg),
            "dismiss": lambda: c.cmd_dismiss(arg),
            "remind": lambda: c.cmd_remind(arg),
            "reminders": lambda: c.cmd_reminders(),
            "brief": lambda: c.cmd_brief(),
        }
        fn = handlers.get(cmd)
        if fn is None:
            await self._reply(update, HELP)
            return
        try:
            reply = await asyncio.to_thread(fn)
        except Exception as e:  # noqa: BLE001 - report, keep the bot alive
            log.exception("command %s failed", cmd)
            reply = f"Failed: {type(e).__name__}: {e}"
        await self._reply(update, reply)
        if cmd == "approvals":
            # One message per waiting item with Approve/Deny buttons. The item id is in the button;
            # only Sachin's updates pass the gate, and approving re-checks status, age and tier.
            for pid in await asyncio.to_thread(c.pending_approval_ids):
                await update.effective_message.reply_text(
                    f"#{pid}", reply_markup=_buttons("pa", str(pid), "Approve", "Deny"))

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.core.is_allowed(update.effective_user.id if update.effective_user else None):
            return
        text = (update.effective_message.text or "").strip()
        if not text:
            return
        if self.bot is not None:
            try:
                await self.bot.send_chat_action(chat_id=self.chat_id, action="typing")
            except Exception:  # noqa: BLE001 - cosmetic
                pass
        reply = await self._in_chat_thread(self.core.chat, text, self.approver)
        await self._reply(update, reply or "(no answer)")

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.core.is_allowed(update.effective_user.id if update.effective_user else None):
            return
        prefix, _, rest = (query.data or "").partition(":")
        token, _, answer = rest.partition(":")
        yes = answer == "y"
        if prefix == "ap":
            req = self.core.broker.resolve(token, yes)
            await query.answer("Approved" if yes and req else "Denied" if req else "Expired")
            if req is not None:
                verdict = "APPROVED" if yes else "DENIED"
                await query.edit_message_text(f"{verdict}: {req.tool}\n\n{req.describe()}"[:4000])
            else:
                await query.edit_message_text("This approval is closed (answered, timed out, or stopped).")
        elif prefix == "pa":
            await query.answer("Running" if yes else "Denied")
            fn = self.core.cmd_approve if yes else self.core.cmd_deny
            try:
                reply = await asyncio.to_thread(fn, token)
            except Exception as e:  # noqa: BLE001 - report, keep the bot alive
                log.exception("approval replay failed")
                reply = f"Failed: {type(e).__name__}: {e}"
            await query.edit_message_text(reply[:4000])
        elif prefix == "sc":
            await query.answer()
            await query.edit_message_text(await asyncio.to_thread(self.core.confirm_schedule, token, yes))
        elif prefix == "tr":
            await query.answer()
            await query.edit_message_text(await asyncio.to_thread(self.core.confirm_trigger, token, yes))
        else:
            await query.answer()

    # ---- approval messages (called from the chat thread) ----

    def _run_coro(self, coro):
        if self.loop is None:
            raise RuntimeError("bot loop not running")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(SEND_TIMEOUT)

    def _send_approval(self, text: str, token: str) -> None:
        msg = self._run_coro(self.bot.send_message(chat_id=self.chat_id, text=text,
                                                   reply_markup=_buttons("ap", token, "Approve", "Deny")))
        self._approval_msgs[token] = msg

    def _approval_closed(self, token: str, outcome: str) -> None:
        msg = self._approval_msgs.pop(token, None)
        if msg is not None and outcome == "timeout":
            self._run_coro(self.bot.edit_message_text(
                chat_id=self.chat_id, message_id=msg.message_id,
                text=f"TIMED OUT (denied): no answer within {int(self.approval_timeout)} s."))

    def close(self) -> None:
        self.core.broker.deny_all()
        self.chat_pool.submit(self.core._drop_session, True).result(timeout=120)
        self.chat_pool.shutdown(wait=False)


def run_bot(core: BotCore, token: str, approval_timeout: float) -> None:
    """Blocks until Ctrl+C. Long polling: nothing listens on this machine."""
    bot = JarvisBot(core, approval_timeout)
    app = bot.build(token)
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        try:
            bot.close()
        except Exception:  # noqa: BLE001
            log.exception("closing the chat session failed")
