"use client";

import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

type Job = { status: string; result: any; error: string } | null;
type Setup = {
  secrets: Record<string, boolean>;
  config: { telegram_allowed_user_id: number | null; weather_place: string | null };
  config_error: string;
  google: {
    installed: boolean;
    install_hint: string;
    client_file_set: boolean;
    client_file_found: boolean;
    token_ok: boolean;
    token_detail: string;
    job: Job;
  };
  voice: {
    stt_package: boolean;
    stt_package_hint: string;
    stt_model: string;
    stt_model_present: boolean;
    stt_model_mb: number;
    stt_setup: string;
    recorder_package: boolean;
    install_hint: string;
    models: { name: string; mb: number }[];
  };
  browser: { installed: boolean; install_hint: string; setup: string; size: string };
  scheduler_running: boolean;
  telegram_running: boolean;
  can_quit: boolean;
};
type Check = { name: string; ok: boolean; detail: string };

const SECRETS: [string, string, string][] = [
  ["tavily_api_key", "Tavily API key", "Web search and news. From tavily.com (free plan)."],
  ["telegram_bot_token", "Telegram bot token", "From @BotFather in Telegram. Needed for the phone bot."],
];

export default function SetupTab() {
  const s = usePoll(() => api<Setup>("/api/setup"), 0);
  const d = s.data;
  return (
    <>
      {s.error && <div className="error">{s.error}</div>}
      <div className="split">
        <section className="panel">
          <h2>Keys</h2>
          <p className="small muted">
            Saved in this computer&apos;s secret store (Credential Manager / Keychain). Jarvis never shows them again.
          </p>
          {SECRETS.map(([name, label, help]) => (
            <SecretField key={name} name={name} label={label} help={help} isSet={!!d?.secrets[name]} onSaved={s.reload} />
          ))}
        </section>
        {d && <LocalSettings d={d} onSaved={s.reload} />}
      </div>
      {d && (
        <div className="split">
          <Google d={d} reload={s.reload} />
          <Downloads d={d} />
        </div>
      )}
      <div className="split">
        <Health />
        <Interview />
      </div>
      <Evaluation />
      {d?.can_quit && <Quit />}
    </>
  );
}

function SecretField({
  name,
  label,
  help,
  isSet,
  onSaved,
}: {
  name: string;
  label: string;
  help: string;
  isSet: boolean;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    const v = value;
    setValue(""); // never keep the secret on screen
    try {
      await post("/api/setup/secret", { name, value: v });
      setMsg("Saved.");
      onSaved();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <form onSubmit={save} style={{ marginBottom: 12 }}>
      <div className="row">
        <strong className="grow">{label}</strong>
        <span className="badge">{isSet ? "set" : "not set"}</span>
      </div>
      <div className="small muted">{help}</div>
      <div className="row">
        <input
          className="grow"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={isSet ? "paste a new value to replace it" : "paste the value"}
          aria-label={label}
        />
        <button className="primary" disabled={!value.trim()}>
          Save
        </button>
      </div>
      {msg && <div className="okbox small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </form>
  );
}

function LocalSettings({ d, onSaved }: { d: Setup; onSaved: () => void }) {
  const [uid, setUid] = useState(d.config.telegram_allowed_user_id?.toString() ?? "");
  const [place, setPlace] = useState(d.config.weather_place ?? "");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    const body: Record<string, unknown> = {};
    if (place.trim() !== (d.config.weather_place ?? "")) body.weather_place = place.trim();
    const oldUid = d.config.telegram_allowed_user_id?.toString() ?? "";
    if (uid.trim() !== oldUid) {
      if (uid.trim()) body.telegram_allowed_user_id = Number(uid.trim());
      else body.clear_telegram_user = true;
    }
    if (!Object.keys(body).length) {
      setMsg("Nothing changed.");
      return;
    }
    if (!confirm("Save these settings to config/local.yaml on this computer?")) return;
    try {
      const r = await post<{ changed: string[]; note: string }>("/api/setup/config", body);
      setMsg(r.changed.length ? `Saved. ${r.note}` : "Nothing changed.");
      onSaved();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <section className="panel">
      <h2>Settings</h2>
      {d.config_error && <div className="error">{d.config_error}</div>}
      <form onSubmit={save}>
        <label className="field">
          Your Telegram user id (the only account the bot answers; ask @userinfobot in Telegram)
          <input inputMode="numeric" value={uid} onChange={(e) => setUid(e.target.value.replace(/[^0-9]/g, ""))} />
        </label>
        <label className="field">
          Default weather place (chat weather and the morning brief)
          <input value={place} onChange={(e) => setPlace(e.target.value)} maxLength={80} placeholder="e.g. Pune" />
        </label>
        <button className="primary">Save settings</button>
      </form>
      <dl className="kv small">
        <dt>Scheduler</dt>
        <dd>{d.scheduler_running ? "running" : "not running (start Jarvis with the shortcut or jarvis app)"}</dd>
        <dt>Telegram bot</dt>
        <dd>{d.telegram_running ? "running" : "off"}</dd>
      </dl>
      {msg && <div className="okbox small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function Google({ d, reload }: { d: Setup; reload: () => void }) {
  const g = d.google;
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const running = g.job?.status === "running";

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(reload, 2000);
    return () => window.clearInterval(id);
  }, [running, reload]);

  async function signIn() {
    if (!confirm("Open Google sign-in in your browser to connect Calendar and Gmail?")) return;
    setError("");
    try {
      const r = await post<{ started: boolean; detail: string }>("/api/setup/google-auth");
      setMsg(r.detail);
      reload();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section className="panel">
      <h2>Google Calendar and Gmail</h2>
      <dl className="kv small">
        <dt>Libraries</dt>
        <dd>{g.installed ? "installed" : <>not installed: <code>{g.install_hint}</code></>}</dd>
        <dt>OAuth client file</dt>
        <dd>
          {g.client_file_found
            ? "found"
            : g.client_file_set
              ? "set but missing"
              : "not set (connectors_file.google.client_secret_file in config/local.yaml)"}
        </dd>
        <dt>Login</dt>
        <dd>{g.token_detail}</dd>
      </dl>
      <button className="primary" onClick={signIn} disabled={!g.installed || running}>
        {running ? "Waiting for Google…" : "Sign in with Google"}
      </button>
      {g.job && g.job.status !== "running" && (
        <div className={g.job.result?.ok ? "okbox small" : "error"}>{g.job.result?.detail || g.job.error}</div>
      )}
      {msg && <div className="notice small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function Downloads({ d }: { d: Setup }) {
  const v = d.voice;
  return (
    <section className="panel">
      <h2>Optional downloads</h2>
      <p className="small muted">Jarvis never downloads these by itself. Run the commands in the repo folder when you want them.</p>
      <h3>Speech-to-text (microphone in Chat)</h3>
      <dl className="kv small">
        <dt>Package</dt>
        <dd>{v.stt_package ? "installed" : <>not installed: <code>{v.install_hint}</code> ({v.stt_package_hint})</>}</dd>
        <dt>Whisper model</dt>
        <dd>
          {v.stt_model} ({v.stt_model_mb} MB):{" "}
          {v.stt_model_present ? "downloaded" : <>not downloaded: <code>{v.stt_setup}</code></>}
        </dd>
        <dt>Other sizes</dt>
        <dd>{v.models.map((m) => `${m.name} ${m.mb} MB`).join(" · ")}</dd>
      </dl>
      <h3>Isolated browser</h3>
      <dl className="kv small">
        <dt>Package</dt>
        <dd>{d.browser.installed ? "installed" : <code>{d.browser.install_hint}</code>}</dd>
        <dt>Chromium</dt>
        <dd>
          <code>{d.browser.setup}</code> — {d.browser.size}
        </dd>
      </dl>
    </section>
  );
}

function Health() {
  const [data, setData] = useState<{ providers: Check[]; connectors: Check[]; stop_engaged: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    try {
      setData(await api("/api/setup/health"));
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const rows = (checks: Check[]) =>
    checks.map((c) => (
      <tr key={c.name}>
        <td>{c.name}</td>
        <td>
          <span className={`badge ${c.ok ? "" : "alert"}`}>{c.ok ? "OK" : "NOT OK"}</span>
        </td>
        <td className="small">{c.detail}</td>
      </tr>
    ));

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Health checks</h2>
        <button className="primary" onClick={run} disabled={busy}>
          {busy ? "Checking…" : "Run checks"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data && (
        <>
          {data.stop_engaged && <div className="error">Emergency stop is ON.</div>}
          <h3>Model providers</h3>
          <table>
            <tbody>{rows(data.providers)}</tbody>
          </table>
          <h3>Connectors</h3>
          <table>
            <tbody>{rows(data.connectors)}</tbody>
          </table>
        </>
      )}
    </section>
  );
}

function Interview() {
  const q = usePoll(() => api<{ questions: string[] }>("/api/interview"), 0);
  const [i, setI] = useState(0);
  const [answer, setAnswer] = useState("");
  const [priv, setPriv] = useState(false);
  const [saved, setSaved] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const questions = q.data?.questions ?? [];
  const done = questions.length > 0 && i >= questions.length;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await post<{ id: string; summary: string }>("/api/interview/answer", {
        question: questions[i],
        answer,
        private: priv,
      });
      setSaved((s) => [...s, `${r.id}: ${r.summary}`]);
      setAnswer("");
      setPriv(false);
      setI(i + 1);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Profile interview</h2>
      <p className="small muted">
        Answer in English or Marathi; each answer is saved as a memory in your words (one model call to tidy it, unless
        marked private). Skip anything you like.
      </p>
      {q.error && <div className="error">{q.error}</div>}
      {!done && questions.length > 0 && (
        <form onSubmit={save}>
          <div className="small muted">
            Question {i + 1} of {questions.length}
          </div>
          <p>
            <strong>{questions[i]}</strong>
          </p>
          <textarea rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} lang="mr" />
          <label className="small row">
            <input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} />
            private (kept local, never sent to the cloud)
          </label>
          <div className="row">
            <button className="primary" disabled={busy || !answer.trim()}>
              Save and next
            </button>
            <button type="button" onClick={() => setI(i + 1)} disabled={busy}>
              Skip
            </button>
          </div>
        </form>
      )}
      {done && (
        <div className="okbox small">
          Interview finished.{" "}
          <button className="link" onClick={() => setI(0)}>
            Start again
          </button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {saved.length > 0 && (
        <ul className="small">
          {saved.map((x, k) => (
            <li key={k}>{x}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Evaluation() {
  const e = usePoll(() => api<{ job: Job }>("/api/eval"), 3000);
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const job = e.data?.job;

  async function run() {
    if (
      !confirm(
        "Run the evaluation suite? It calls the model for every task (about a dozen calls on your Claude plan) and takes a few minutes.",
      )
    )
      return;
    setError("");
    try {
      await post("/api/eval", { category: category.trim() || null });
      e.reload();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Evaluation</h2>
        <input
          value={category}
          onChange={(ev) => setCategory(ev.target.value)}
          placeholder="category (optional)"
          maxLength={40}
        />
        <button className="primary" onClick={run} disabled={job?.status === "running"}>
          {job?.status === "running" ? "Running…" : "Run evaluation"}
        </button>
      </div>
      <p className="small muted">Checks Marathi/English replies, memory, structured output and tool calling. Calls the model.</p>
      {error && <div className="error">{error}</div>}
      {job?.status === "error" && <div className="error">{job.error}</div>}
      {job?.result && (
        <>
          <p>
            <strong>
              {job.result.passed}/{job.result.total} passed
            </strong>{" "}
            <span className="small muted">
              {job.result.provider}/{job.result.model} · {job.result.path}
            </span>
          </p>
          <table>
            <tbody>
              {job.result.results.map((r: any) => (
                <tr key={r.task_id}>
                  <td>
                    <span className={`badge ${r.passed ? "" : "alert"}`}>{r.passed ? "PASS" : "FAIL"}</span>
                  </td>
                  <td>{r.task_id}</td>
                  <td className="small">
                    {r.category}/{r.language}
                  </td>
                  <td className="small">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function Quit() {
  const [msg, setMsg] = useState("");
  async function quit() {
    if (!confirm("Quit Jarvis? The dashboard, schedules, reminders and the Telegram bot stop until you start it again."))
      return;
    try {
      await post("/api/app/quit");
      setMsg("Jarvis is stopping. You can close this tab.");
    } catch (e) {
      setMsg(errText(e));
    }
  }
  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Jarvis app</h2>
        <button className="danger" onClick={quit}>
          Quit Jarvis
        </button>
      </div>
      {msg && <div className="notice small">{msg}</div>}
    </section>
  );
}
