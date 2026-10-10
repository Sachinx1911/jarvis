"""Chat sessions and task runs started from the dashboard.

SQLite connections belong to the thread that opened them, so every chat session gets its
own single-thread executor that opens a Runtime and keeps it, and every task run gets its
own thread and Runtime. Request handlers never touch these connections directly.
"""

from __future__ import annotations

import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import Runtime, make_chat, make_task_runner, open_runtime
from jarvis.web.approvals import ApprovalBroker

ChatFactory = Callable[[Runtime, object], ChatSession]  # (runtime, approver) -> session


@dataclass
class _Chat:
    id: str
    executor: ThreadPoolExecutor
    rt: Runtime | None = None
    session: ChatSession | None = None
    last_used: float = field(default_factory=time.time)
    busy: bool = False


class ChatManager:
    def __init__(self, broker: ApprovalBroker, factory: ChatFactory, idle_minutes: float = 120.0):
        self.broker = broker
        self.factory = factory
        self.idle_s = idle_minutes * 60
        self._lock = threading.Lock()
        self._chats: dict[str, _Chat] = {}

    def create(self) -> dict:
        self.expire_idle()
        cid = secrets.token_hex(8)
        chat = _Chat(cid, ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"chat-{cid}"))

        def start() -> dict:
            chat.rt = open_runtime()
            try:
                chat.session = self.factory(chat.rt, self.broker.approver(f"chat:{cid}"))
            except Exception:
                chat.rt.close()
                raise
            d = chat.session.decision
            return {"id": cid, "provider": d.provider, "model": d.model}

        try:
            info = chat.executor.submit(start).result()
        except Exception:
            chat.executor.shutdown(wait=False)
            raise
        with self._lock:
            self._chats[cid] = chat
        return info

    def _get(self, cid: str) -> _Chat:
        with self._lock:
            chat = self._chats.get(cid)
        if chat is None:
            raise KeyError(cid)
        return chat

    def send(self, cid: str, text: str) -> dict:
        chat = self._get(cid)
        chat.last_used = time.time()

        def work() -> dict:
            assert chat.session and chat.rt
            if text.startswith("/remember"):
                cmd, _, rest = text.partition(" ")
                if chat.session.extractor is None:
                    return {"reply": "Memory is not available.", "kind": "command"}
                mem = chat.session.extractor.remember(rest.strip(), private=cmd == "/remember-private")
                return {"reply": f"Remembered as {mem.id}: {mem.summary_en or mem.name}", "kind": "command"}
            return {"reply": chat.session.send(text), "kind": "chat"}

        chat.busy = True
        try:
            return chat.executor.submit(work).result()
        finally:
            chat.busy = False
            chat.last_used = time.time()

    def end(self, cid: str) -> list:
        with self._lock:
            chat = self._chats.pop(cid, None)
        if chat is None:
            raise KeyError(cid)

        def work() -> list:
            try:
                return chat.session.end() if chat.session else []
            finally:
                if chat.rt:
                    chat.rt.close()

        try:
            return chat.executor.submit(work).result()
        finally:
            chat.executor.shutdown(wait=False)

    def expire_idle(self) -> None:
        now = time.time()
        with self._lock:
            old = [c.id for c in self._chats.values() if not c.busy and now - c.last_used > self.idle_s]
        for cid in old:
            try:
                self.end(cid)
            except Exception:  # an idle chat that fails to save must not break new chats
                pass

    def list(self) -> list[dict]:
        with self._lock:
            return [{"id": c.id, "busy": c.busy, "last_used": c.last_used} for c in self._chats.values()]

    def close_all(self) -> None:
        for c in list(self._chats):
            try:
                self.end(c)
            except Exception:
                pass


class TaskManager:
    """Runs tasks in background threads. The approver routes questions to the dashboard queue."""

    def __init__(self, broker: ApprovalBroker, audit: AuditLog, provider_override: str | None = None,
                 runner_factory: Callable | None = None):
        self.broker = broker
        self.audit = audit
        self.provider_override = provider_override
        self.runner_factory = runner_factory or (
            lambda rt, approver, progress: make_task_runner(rt, self.provider_override, approver, progress=progress))
        self._lock = threading.Lock()
        self._running: dict[str, threading.Thread] = {}
        self.progress: dict[str, list[str]] = {}

    def running(self) -> list[str]:
        with self._lock:
            return [k for k, t in self._running.items() if t.is_alive()]

    def is_running(self, task_id: str) -> bool:
        return task_id in self.running()

    def start(self, task_id: str) -> bool:
        with self._lock:
            t = self._running.get(task_id)
            if t and t.is_alive():
                return False
            log = self.progress.setdefault(task_id, [])
            thread = threading.Thread(target=self._run, args=(task_id, log), name=f"task-{task_id}", daemon=True)
            self._running[task_id] = thread
        thread.start()
        return True

    def _run(self, task_id: str, log: list[str]) -> None:
        rt = open_runtime()
        try:
            def progress(msg: str) -> None:
                log.append(msg)
                del log[:-50]

            runner = self.runner_factory(rt, self.broker.approver(f"task:{task_id}", task_id), progress)
            runner.run(task_id)
        except Exception as e:  # e.g. the task was cancelled from the board while it ran
            self.audit.write("dashboard_task_error", task_id=task_id, error=f"{type(e).__name__}: {e}")
            log.append(f"stopped: {e}")
        finally:
            rt.close()

    def join(self, task_id: str, timeout: float | None = None) -> None:
        with self._lock:
            t = self._running.get(task_id)
        if t:
            t.join(timeout)


def default_chat_factory(provider_override: str | None) -> ChatFactory:
    return lambda rt, approver: make_chat(rt, provider_override, approver)  # type: ignore[arg-type]
