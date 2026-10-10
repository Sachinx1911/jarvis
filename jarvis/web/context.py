"""Shared state for the dashboard routers (jarvis/web/routes_*.py)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import Runtime, open_runtime
from jarvis.web.jobs import Jobs
from jarvis.web.settings import WebSettings


@dataclass
class WebContext:
    settings: WebSettings
    audit: AuditLog
    stop: StopSwitch
    chats: Any                      # jarvis.web.workers.ChatManager
    jobs: Jobs
    config_dir: Path
    proactive_factory: Callable[[], Any] | None = None   # -> jarvis.proactive.service.Proactive
    speech_factory: Callable[[], Any] | None = None      # -> jarvis.voice.tts.SpeechOutput
    stt_factory: Callable[[], Any] | None = None         # -> speech-to-text engine
    oauth_flow_factory: Callable | None = None           # tests: fake Google sign-in
    on_quit: Callable[[], None] | None = None            # set by `jarvis app`
    extra: dict[str, Any] = field(default_factory=dict)

    @contextmanager
    def runtime(self) -> Iterator[Runtime]:
        rt = open_runtime()
        try:
            yield rt
        finally:
            rt.close()

    def proactive(self):
        if self.proactive_factory is not None:
            return self.proactive_factory()
        from jarvis.proactive.notify import make_notifier
        from jarvis.proactive.service import Proactive
        from jarvis.proactive.settings import load_settings

        settings = load_settings(self.config_dir)
        return Proactive(settings, notifier=make_notifier(settings, self.audit),
                         provider_override=self.settings.provider)
