"use client";

import { useEffect, useState } from "react";
import { api, post, put, upload } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

type ProjectRow = { name: string; goal: string; documents: number };
type Doc = {
  file: string;
  indexed: boolean;
  privacy: string;
  chunks: number;
  status: string;
  error: string | null;
  doc_date: string | null;
  on_disk: boolean;
};
type Project = { name: string; project_md: string; documents: Doc[]; max_upload_mb: number };
type Hit = { citation: string; project: string; file: string; privacy: string; text: string; doc_date: string };

const ACCEPT = ".md,.txt,.pdf,.docx";

export default function ProjectsTab({ onUseInChat }: { onUseInChat: (name: string) => void }) {
  const list = usePoll(() => api<{ items: ProjectRow[] }>("/api/projects"), 0);
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const items = list.data?.items ?? [];

  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].name);
  }, [items, selected]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await post<{ name: string; created: boolean }>("/api/projects", { name, goal });
      setName("");
      setGoal("");
      await list.reload();
      setSelected(r.name);
      if (!r.created) setError(`Project ${r.name} already exists; opened it.`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <>
      <div className="split">
        <section className="panel">
          <h2>Projects</h2>
          {list.error && <div className="error">{list.error}</div>}
          {items.length === 0 && <p className="muted">No projects yet. Create one below.</p>}
          <table>
            <tbody>
              {items.map((p) => (
                <tr
                  key={p.name}
                  className={`clickable ${selected === p.name ? "selected" : ""}`}
                  onClick={() => setSelected(p.name)}
                >
                  <td>
                    <strong>{p.name}</strong>
                    <div className="small muted">{p.goal}</div>
                  </td>
                  <td className="num small">{p.documents} docs</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>New project</h3>
          <form onSubmit={create}>
            <label className="field">
              Name (letters, digits, dashes)
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} />
            </label>
            <label className="field">
              Goal
              <input value={goal} onChange={(e) => setGoal(e.target.value)} maxLength={2000} />
            </label>
            <button className="primary" disabled={!name.trim()}>
              Create project
            </button>
          </form>
          {error && <div className="error">{error}</div>}
        </section>
        <Search projects={items.map((p) => p.name)} />
      </div>
      {selected && (
        <ProjectDetail key={selected} name={selected} onChanged={list.reload} onUseInChat={onUseInChat} />
      )}
    </>
  );
}

function ProjectDetail({
  name,
  onChanged,
  onUseInChat,
}: {
  name: string;
  onChanged: () => void;
  onUseInChat: (name: string) => void;
}) {
  const p = usePoll(() => api<Project>(`/api/projects/${encodeURIComponent(name)}`), 0, [name]);
  const [md, setMd] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (p.data && md === null) setMd(p.data.project_md);
  }, [p.data, md]);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      setMsg(await action());
      await p.reload();
      onChanged();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const saveMd = () =>
    run(async () => {
      await put(`/api/projects/${encodeURIComponent(name)}/md`, { text: md ?? "" });
      return "PROJECT.md saved.";
    });

  async function onFiles(files: FileList | null) {
    if (!files || !files.length) return;
    const max = (p.data?.max_upload_mb ?? 20) * 1024 * 1024;
    await run(async () => {
      const out: string[] = [];
      for (const f of Array.from(files)) {
        if (f.size > max) {
          out.push(`${f.name}: larger than ${p.data?.max_upload_mb ?? 20} MB, not added`);
          continue;
        }
        const q = new URLSearchParams({ filename: f.name, replace: replace ? "true" : "false" });
        const r = await upload<{ file: string; index: string; failed: { file: string; why: string }[] }>(
          `/api/projects/${encodeURIComponent(name)}/docs?${q}`,
          f,
        );
        out.push(`${r.file} added (${r.index})` + r.failed.map((x) => `; ${x.file}: ${x.why}`).join(""));
      }
      return out.join("\n");
    });
  }

  const index = (force: boolean) =>
    run(async () => {
      const r = await post<{ summary: string; failed: { file: string; why: string }[] }>(
        `/api/projects/${encodeURIComponent(name)}/index`,
        { force },
      );
      return `Indexed: ${r.summary}` + r.failed.map((x) => `\n${x.file}: ${x.why}`).join("");
    });

  function mark(d: Doc, privacy: string) {
    if (privacy === d.privacy) return;
    const q =
      privacy === "P1"
        ? `Mark ${d.file} as P1? Its text may then be sent to the cloud model when relevant.`
        : `Mark ${d.file} as P2 (private, never sent to the cloud model)?`;
    if (!confirm(q)) return;
    run(async () => {
      await post(`/api/projects/${encodeURIComponent(name)}/privacy`, { file: d.file, privacy });
      return `${d.file} is now ${privacy}.`;
    });
  }

  const docs = p.data?.documents ?? [];
  return (
    <div className="split">
      <section className="panel">
        <div className="row">
          <h2 className="grow">{name}: PROJECT.md</h2>
          <button onClick={() => onUseInChat(name)} title="Its memories and documents come first in Chat">
            Use in chat
          </button>
        </div>
        <textarea rows={16} value={md ?? ""} onChange={(e) => setMd(e.target.value)} aria-label="PROJECT.md" lang="mr" />
        <div className="row">
          <button className="primary" onClick={saveMd} disabled={busy || md === null || md === p.data?.project_md}>
            Save PROJECT.md
          </button>
          <button onClick={() => setMd(p.data?.project_md ?? "")} disabled={busy}>
            Undo changes
          </button>
        </div>
      </section>
      <section className="panel">
        <h2>Documents</h2>
        <p className="small muted">
          Only files you add here are read by Jarvis: .md, .txt, .pdf, .docx, up to {p.data?.max_upload_mb ?? 20} MB.
          New documents are P2 (private: never sent to the cloud model). Mark one P1 to allow that.
        </p>
        <div className="row">
          <input type="file" accept={ACCEPT} multiple disabled={busy} onChange={(e) => onFiles(e.target.files)} />
          <label className="small row">
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            replace files with the same name
          </label>
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <button onClick={() => index(false)} disabled={busy}>
            Index new and changed
          </button>
          <button onClick={() => index(true)} disabled={busy}>
            Re-read all
          </button>
        </div>
        {busy && <p className="small muted">Working…</p>}
        {msg && <pre>{msg}</pre>}
        {(error || p.error) && <div className="error">{error || p.error}</div>}
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Privacy</th>
              <th className="num">Chunks</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.file}>
                <td>{d.file}</td>
                <td>
                  <select
                    value={d.privacy}
                    disabled={!d.indexed || busy}
                    onChange={(e) => mark(d, e.target.value)}
                    aria-label={`Privacy of ${d.file}`}
                  >
                    <option value="P2">P2 private</option>
                    <option value="P1">P1 may go to cloud</option>
                    {d.privacy === "P0" && <option value="P0">P0 public</option>}
                  </select>
                </td>
                <td className="num">{d.chunks}</td>
                <td className="small">
                  {d.status}
                  {d.error ? `: ${d.error}` : ""}
                  {!d.on_disk ? " (file removed; re-index)" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {docs.length === 0 && <p className="muted">No documents yet.</p>}
      </section>
    </div>
  );
}

function Search({ projects }: { projects: string[] }) {
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [error, setError] = useState("");

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const params = new URLSearchParams({ q, ...(project ? { project } : {}) });
      setHits((await api<{ items: Hit[] }>(`/api/docs/search?${params}`)).items);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <section className="panel">
      <h2>Search documents</h2>
      <form className="row" onSubmit={search}>
        <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="words (English or मराठी)" />
        <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
          <option value="">all projects</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button className="primary" disabled={!q.trim()}>
          Search
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {hits && hits.length === 0 && <p className="muted">No matches.</p>}
      {hits?.map((h, i) => (
        <div key={i} style={{ marginTop: 10 }}>
          <div className="small">
            <strong>[{h.citation}]</strong> {h.project} · <span className="tier">{h.privacy}</span>{" "}
            <span className="muted">{h.doc_date}</span>
          </div>
          <pre>{h.text}</pre>
        </div>
      ))}
    </section>
  );
}
