"""Setup, health, profile interview and evaluation in the dashboard.

Secrets: only `tavily_api_key` and `telegram_bot_token` can be entered here. They go
straight into the OS secret store (jarvis.secrets.set_secret); the response says only
"set"/"not set", the audit log records only the name, and request validation errors never
echo the submitted value (see the handler in jarvis/web/app.py).

Downloads (Whisper model, Playwright Chromium) are shown as instructions with sizes; the
dashboard never downloads them.
"""

from __future__ import annotations

import importlib.util
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.paths import PROMPTS_DIR
from jarvis.web.context import WebContext
from jarvis.web.jobs import JobBusy
from jarvis.web.localconfig import LocalConfigError, current_values, update_local

SETTABLE_SECRETS = ("tavily_api_key", "telegram_bot_token")
HEALTH_PROVIDERS = ("claude_code", "anthropic", "fake")


class SecretBody(BaseModel):
    name: Literal["tavily_api_key", "telegram_bot_token"]
    value: str = Field(min_length=1, max_length=500)


class ConfigBody(BaseModel):
    telegram_allowed_user_id: int | None = Field(default=None, ge=1, le=10**13)
    weather_place: str | None = Field(default=None, max_length=80)
    clear_telegram_user: bool = False


class InterviewAnswer(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=4000)
    private: bool = False


class EvalBody(BaseModel):
    category: str | None = Field(default=None, max_length=40)


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def interview_questions() -> list[str]:
    path = PROMPTS_DIR / "interview.md"
    return [line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def connectors_cfg() -> dict:
        from jarvis.connectors.config import load_connectors_config

        return load_connectors_config()

    # ---- status ----

    @r.get("/setup")
    def setup_status() -> dict[str, Any]:
        from jarvis.secrets import get_secret
        from jarvis.voice.config import load_voice_config
        from jarvis.voice.stt import PACKAGE_HINT, WHISPER_MODELS, faster_whisper_installed, model_present

        with ctx.runtime() as rt:
            home = rt.paths.home
        try:
            values = current_values(ctx.config_dir)
            config_error = ""
        except LocalConfigError as e:
            values, config_error = {}, str(e)
        voice_cfg = load_voice_config(ctx.config_dir)
        model = str(voice_cfg["stt"].get("model", "small"))
        cfg = connectors_cfg()
        from jarvis.connectors.google import auth as google_auth

        client = google_auth.client_secret_path(cfg)
        token_ok, token_detail = google_auth.token_status(cfg)
        return {
            "secrets": {name: bool(get_secret(name)) for name in SETTABLE_SECRETS},
            "config": values,
            "config_error": config_error,
            "google": {
                "installed": _installed("google_auth_oauthlib") and _installed("googleapiclient"),
                "install_hint": 'pip install -e ".[google]"',
                "client_file_set": bool(client),
                "client_file_found": bool(client and client.is_file()),
                "token_ok": token_ok, "token_detail": token_detail,
                "job": ctx.jobs.get("google-auth"),
            },
            "voice": {
                "stt_package": faster_whisper_installed(),
                "stt_package_hint": PACKAGE_HINT,
                "stt_model": model,
                "stt_model_present": model_present(home, model),
                "stt_model_mb": WHISPER_MODELS.get(model, ("", 0))[1],
                "stt_setup": f"jarvis voice setup --model {model}",
                "recorder_package": _installed("sounddevice"),
                "install_hint": 'pip install -e ".[voice]"',
                "models": [{"name": n, "mb": mb} for n, (_, mb) in WHISPER_MODELS.items()],
            },
            "browser": {
                "installed": _installed("playwright"),
                "install_hint": 'pip install -e ".[browser]"',
                "setup": "jarvis browser setup",
                "size": "about 150-200 MB (Playwright's own Chromium)",
            },
            "scheduler_running": bool(ctx.extra.get("scheduler_running")),
            "telegram_running": bool(ctx.extra.get("telegram_running")),
            "can_quit": ctx.on_quit is not None,
        }

    # ---- secrets (never echoed) ----

    @r.post("/setup/secret")
    def set_secret_value(body: SecretBody) -> dict[str, Any]:
        from jarvis.secrets import set_secret

        value = body.value.strip()
        if not value:
            raise HTTPException(400, "nothing entered; unchanged")
        try:
            set_secret(body.name, value)
        except Exception as e:  # keyring backend problems; the message never contains the value
            ctx.audit.write("secret_set_failed", name=body.name, source="dashboard", error=type(e).__name__)
            raise HTTPException(500, f"could not save in the OS secret store ({type(e).__name__})")
        ctx.audit.write("secret_set", name=body.name, source="dashboard")
        return {"name": body.name, "set": True}

    # ---- config/local.yaml ----

    @r.post("/setup/config")
    def set_config(body: ConfigBody) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if body.clear_telegram_user:
            values["telegram_allowed_user_id"] = None
        elif body.telegram_allowed_user_id is not None:
            values["telegram_allowed_user_id"] = int(body.telegram_allowed_user_id)
        if body.weather_place is not None:
            if any(c in body.weather_place for c in "\n\r\t{}[]<>`\"\\:#"):
                raise HTTPException(400, "use a plain place name, e.g. Pune")
            place = " ".join(body.weather_place.split())
            values["weather_place"] = place
        if not values:
            raise HTTPException(400, "nothing to change")
        try:
            changed = update_local(ctx.config_dir, values)
        except LocalConfigError as e:
            raise HTTPException(409, str(e))
        ctx.audit.write("local_config_changed", source="dashboard", keys=changed)
        return {"changed": changed, "config": current_values(ctx.config_dir),
                "note": "Restart Jarvis (or the daemon) for Telegram changes to take effect." if changed else ""}

    # ---- Google sign-in (opens the browser on this machine) ----

    @r.post("/setup/google-auth")
    def google_auth_start() -> dict[str, Any]:
        from jarvis.connectors.google import auth as google_auth

        if ctx.oauth_flow_factory is None and not _installed("google_auth_oauthlib"):
            return {"started": False, "detail": 'Google libraries are not installed. Run: pip install -e ".[google]"'}
        cfg = connectors_cfg()
        path = google_auth.client_secret_path(cfg)
        if not path or not path.is_file():
            return {"started": False, "detail": "Set google.client_secret_file in config/local.yaml "
                                                "(connectors_file) to the downloaded OAuth Desktop client JSON."}

        def run() -> dict[str, Any]:
            try:
                scopes = google_auth.run_oauth_flow(cfg, ctx.oauth_flow_factory)
            except google_auth.GoogleAuthError as e:
                ctx.audit.write("google_auth", ok=False, source="dashboard", detail=str(e))
                return {"ok": False, "detail": str(e)}
            ctx.audit.write("google_auth", ok=True, source="dashboard", scopes=[s.rsplit("/", 1)[-1] for s in scopes])
            return {"ok": True, "detail": google_auth.token_status(cfg)[1]}

        try:
            ctx.jobs.start("google-auth", run)
        except JobBusy as e:
            raise HTTPException(409, str(e))
        return {"started": True, "detail": "A Google sign-in page opens in your browser. Finish it there."}

    # ---- health ----

    @r.get("/setup/health")
    def health_checks() -> dict[str, Any]:
        from jarvis.config import load_config
        from jarvis.connectors.registry import ConnectorDeps, connector_health
        from jarvis.providers import make_provider
        from jarvis.secrets import get_secret

        config = load_config(ctx.config_dir)
        providers = []
        for name in HEALTH_PROVIDERS:
            try:
                h = make_provider(name, config).health()
                providers.append({"name": name, "ok": h.ok, "detail": h.detail})
            except Exception as e:
                providers.append({"name": name, "ok": False, "detail": f"{type(e).__name__}"})
        with ctx.runtime() as rt:
            connectors = [{"name": n, "ok": ok, "detail": d}
                          for n, ok, d in connector_health(ConnectorDeps(rt.paths.home, rt.store, rt.audit))]
        connectors.insert(0, {"name": "tavily key", "ok": bool(get_secret("tavily_api_key")),
                              "detail": "set" if get_secret("tavily_api_key") else "not set (Setup tab)"})
        return {"providers": providers, "connectors": connectors, "stop_engaged": ctx.stop.engaged()}

    # ---- profile interview (answers saved with the existing extractor) ----

    @r.get("/interview")
    def interview() -> dict[str, Any]:
        return {"questions": interview_questions()}

    @r.post("/interview/answer")
    def interview_answer(body: InterviewAnswer) -> dict[str, Any]:
        from jarvis.core.runtime import make_extractor
        from jarvis.memory.store import MemoryRejected
        from jarvis.providers.base import ProviderError

        if body.question not in interview_questions():
            raise HTTPException(400, "unknown question")
        if ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on")
        answer = body.answer.strip()
        text = f"{body.question} {answer}" if len(answer) < 40 else answer
        with ctx.runtime() as rt:
            try:
                mem = make_extractor(rt, ctx.settings.provider).remember(text, private=body.private)
            except (MemoryRejected, ValueError) as e:
                raise HTTPException(400, f"not saved: {e}")
            except ProviderError as e:
                raise HTTPException(502, f"model error ({e.kind}): {e}")
            rt.audit.write("interview_answer", source="dashboard", memory_id=mem.id)
            return {"id": mem.id, "summary": mem.summary_en or mem.name}

    # ---- evaluation (calls the model for every task) ----

    @r.get("/eval")
    def eval_status() -> dict[str, Any]:
        return {"job": ctx.jobs.get("eval")}

    @r.post("/eval")
    def eval_run(body: EvalBody) -> dict[str, Any]:
        if ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on")

        def run() -> dict[str, Any]:
            from jarvis.core.runtime import open_runtime
            from jarvis.evals.runner import run_suite

            rt = open_runtime()
            try:
                report = run_suite(rt, ctx.settings.provider, body.category or None)
            finally:
                rt.close()
            ctx.audit.write("eval_run", source="dashboard", provider=report.provider, model=report.model,
                            passed=report.passed, total=len(report.results))
            return {"provider": report.provider, "model": report.model, "passed": report.passed,
                    "total": len(report.results), "path": str(report.path) if report.path else None,
                    "results": [{"task_id": x.task_id, "category": x.category, "language": x.language,
                                 "passed": x.passed, "detail": x.detail[:300]} for x in report.results]}

        try:
            ctx.jobs.start("eval", run)
        except JobBusy as e:
            raise HTTPException(409, str(e))
        ctx.audit.write("eval_started", source="dashboard", category=body.category)
        return {"started": True}

    # ---- quit (only under `jarvis app`) ----

    @r.post("/app/quit")
    def quit_app() -> dict[str, Any]:
        if ctx.on_quit is None:
            raise HTTPException(409, "this server was not started by `jarvis app`; stop it in its terminal")
        ctx.audit.write("app_quit", source="dashboard")
        ctx.on_quit()
        return {"quitting": True}

    return r
