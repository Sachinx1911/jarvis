"use client";

import { useState } from "react";
import { api, post, put } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

type Rec = {
  id: string;
  name: string;
  status: string;
  started_at: string;
  notes: string[];
  has_evidence: boolean;
  has_draft: boolean;
};
type Skill = { name: string; description: string; version: number | null; source: string | null; old_versions: string[] };
type TeachData = {
  active: { id: string; name: string; started_at: string; notes: string[] } | null;
  recordings: Rec[];
  skills: Skill[];
};
type RecDetail = { id: string; meta: Record<string, unknown>; evidence: string | null; draft: string | null };

export default function TeachTab({
  onRunInChat,
  onGoToChat,
}: {
  onRunInChat: (text: string) => void;
  onGoToChat: () => void;
}) {
  const t = usePoll(() => api<TeachData>("/api/teach"), 5000);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function act(fn: () => Promise<string | void>) {
    setError("");
    setMsg("");
    try {
      const m = await fn();
      if (m) setMsg(m);
      await t.reload();
    } catch (e) {
      setError(errText(e));
    }
  }

  const active = t.data?.active;
  return (
    <>
      <section className="panel">
        <h2>Teach Jarvis a task</h2>
        <p className="small muted">
          Start a recording, do the task once in the Chat tab (Jarvis records the chat, the tools it ran and file
          changes in its folders; no mouse or keyboard capture), add notes on why, then stop. Jarvis drafts a skill;
          you check and approve it.
        </p>
        {active ? (
          <>
            <div className="okbox">
              Recording <strong>{active.name}</strong> ({active.id}) since {active.started_at}.{" "}
              <button className="link" onClick={onGoToChat}>
                Go to Chat
              </button>
            </div>
            {active.notes.length > 0 && (
              <ul className="small">
                {active.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                act(async () => {
                  await post("/api/teach/note", { text: note });
                  setNote("");
                  return "Noted.";
                });
              }}
            >
              <input
                className="grow"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why you do this step (note)"
                maxLength={2000}
              />
              <button disabled={!note.trim()}>Add note</button>
              <button
                type="button"
                className="primary"
                onClick={() =>
                  act(async () => {
                    const r = await post<{ id: string }>("/api/teach/stop");
                    setOpen(r.id);
                    return `Recording ${r.id} stopped. Check the evidence, then draft a skill.`;
                  })
                }
              >
                Stop recording
              </button>
            </form>
          </>
        ) : (
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                const r = await post<{ id: string; hint: string }>("/api/teach/start", { name: name || "demo" });
                setName("");
                return `Recording ${r.id} started. ${r.hint}`;
              });
            }}
          >
            <input
              className="grow"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name of the task, e.g. daily note"
              maxLength={80}
            />
            <button className="primary">Start recording</button>
          </form>
        )}
        {msg && <div className="okbox small">{msg}</div>}
        {(error || t.error) && <div className="error">{error || t.error}</div>}
      </section>

      <div className="split">
        <section className="panel">
          <h2>Recordings</h2>
          {(t.data?.recordings ?? []).length === 0 && <p className="muted">No recordings yet.</p>}
          <table>
            <tbody>
              {(t.data?.recordings ?? []).map((r) => (
                <tr
                  key={r.id}
                  className={`clickable ${open === r.id ? "selected" : ""}`}
                  onClick={() => setOpen(r.id)}
                >
                  <td>
                    <strong>{r.name}</strong> <span className="small muted">{r.id}</span>
                  </td>
                  <td className="small">{r.status}</td>
                  <td className="small">{r.has_draft ? "draft ready" : r.has_evidence ? "evidence" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <Skills skills={t.data?.skills ?? []} onRunInChat={onRunInChat} />
      </div>
      {open && <RecordingDetail key={open} id={open} onChanged={t.reload} />}
    </>
  );
}

function RecordingDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const d = usePoll(() => api<RecDetail>(`/api/teach/recordings/${id}`), 0, [id]);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const text = draft ?? d.data?.draft ?? "";

  async function act(fn: () => Promise<string>) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      setMsg(await fn());
      await d.reload();
      onChanged();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const makeDraft = () => {
    if (!confirm("Draft a skill from this recording? This makes one model call (skill_draft route).")) return;
    act(async () => {
      const r = await post<{ draft: string }>(`/api/teach/recordings/${id}/draft`);
      setDraft(r.draft);
      return "Draft ready. Read it, edit if needed, then approve.";
    });
  };
  const save = () =>
    act(async () => {
      await put(`/api/teach/recordings/${id}/draft`, { text });
      setDraft(null);
      return "Draft saved.";
    });
  const approve = () => {
    if (!confirm("Approve this draft as a skill? An older version with the same name is kept as SKILL.vN.md.")) return;
    act(async () => {
      if (draft !== null && draft !== d.data?.draft) await put(`/api/teach/recordings/${id}/draft`, { text });
      const r = await post<{ skill: string; version: number }>(`/api/teach/recordings/${id}/approve`);
      setDraft(null);
      return `Skill ${r.skill} saved (version ${r.version}).`;
    });
  };

  return (
    <div className="split">
      <section className="panel">
        <h2>Evidence: {id}</h2>
        {d.error && <div className="error">{d.error}</div>}
        {d.data?.evidence ? <pre lang="mr">{d.data.evidence}</pre> : <p className="muted">Stop the recording first.</p>}
      </section>
      <section className="panel">
        <div className="row">
          <h2 className="grow">Skill draft</h2>
          <button onClick={makeDraft} disabled={busy || !d.data?.evidence}>
            {d.data?.draft ? "Draft again" : "Draft a skill"}
          </button>
        </div>
        {d.data?.draft || draft !== null ? (
          <>
            <textarea rows={18} value={text} onChange={(e) => setDraft(e.target.value)} aria-label="Skill draft" />
            <div className="row">
              <button onClick={save} disabled={busy || draft === null || draft === d.data?.draft}>
                Save edits
              </button>
              <button className="primary" onClick={approve} disabled={busy}>
                Approve as skill
              </button>
            </div>
          </>
        ) : (
          <p className="muted">No draft yet.</p>
        )}
        {busy && <p className="small muted">Working…</p>}
        {msg && <div className="okbox small">{msg}</div>}
        {error && <div className="error">{error}</div>}
      </section>
    </div>
  );
}

function Skills({ skills, onRunInChat }: { skills: Skill[]; onRunInChat: (text: string) => void }) {
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [shown, setShown] = useState<{ name: string; text: string } | null>(null);
  const [error, setError] = useState("");

  async function show(name: string) {
    setError("");
    try {
      setShown(await api<{ name: string; text: string }>(`/api/skills/${encodeURIComponent(name)}`));
    } catch (e) {
      setError(errText(e));
    }
  }

  function run(s: Skill) {
    const extra = (inputs[s.name] ?? "").trim();
    if (!confirm(`Run the skill ${s.name} in Chat${extra ? ` with: ${extra}` : ""}? Actions that need approval still ask.`))
      return;
    onRunInChat(
      `Load the skill ${s.name} with load_skill and carry it out` + (extra ? ` with these inputs: ${extra}` : "") + ".",
    );
  }

  return (
    <section className="panel">
      <h2>Skills</h2>
      {skills.length === 0 && <p className="muted">No skills yet. Approve a draft to add one.</p>}
      {skills.map((s) => (
        <div key={s.name} style={{ marginBottom: 10 }}>
          <div className="row">
            <strong className="grow">
              {s.name} <span className="small muted">v{s.version ?? 1}</span>
            </strong>
            <button onClick={() => show(s.name)}>View</button>
          </div>
          <div className="small muted">
            {s.description}
            {s.old_versions.length > 0 && ` · older: ${s.old_versions.join(", ")}`}
          </div>
          <div className="row">
            <input
              className="grow"
              value={inputs[s.name] ?? ""}
              onChange={(e) => setInputs({ ...inputs, [s.name]: e.target.value })}
              placeholder="inputs, e.g. date=2026-10-12"
            />
            <button className="primary" onClick={() => run(s)}>
              Run in chat
            </button>
          </div>
        </div>
      ))}
      {error && <div className="error">{error}</div>}
      {shown && (
        <>
          <h3>{shown.name}</h3>
          <pre>{shown.text}</pre>
        </>
      )}
    </section>
  );
}
