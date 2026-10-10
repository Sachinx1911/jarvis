"use client";

import { useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

// India features (jarvis/india via jarvis/web/routes_india.py). Bill and wallet details are
// private (P2): they are shown here, on this computer only, and never sent to a model.

type Quote = {
  code: string;
  label: string;
  name: string;
  nav: number | null;
  nav_date: string | null;
  prev_nav: number | null;
  prev_date: string | null;
  change: number | null;
  change_pct: number | null;
};
type Scheme = { code: string; label: string };
type NavData = {
  enabled: boolean;
  schemes: Scheme[];
  query: string;
  items: Quote[];
  last_fetch: string | null;
  fresh: boolean;
  refresh_hours: number;
  error?: string | null;
};

type Bill = {
  id: number;
  biller: string;
  category: string;
  kind: string;
  source: string;
  amount: string;
  due_date: string | null;
  bill_date: string;
  status: string;
  autopay: boolean;
  period: string | null;
  days_left: number | null;
  overdue: boolean;
  reminders: number;
  payee: boolean;
};
type Payee = { name: string; vpa: string; biller_key: string; confirmed_at: string };
type Recurring = {
  biller: string;
  period: string;
  count: number;
  average: string;
  per_month: string;
  next_expected: string;
  autopay: boolean;
};
type BillsData = {
  items: Bill[];
  counts: { due: number; due_soon: number; overdue: number };
  summary: string;
  recurring: Recurring[];
  payees: Payee[];
};
type UpiPreview = {
  bill: Bill;
  ready: boolean;
  reason: string;
  payee: { name: string; vpa: string; confirmed_at: string } | null;
  args_sha256: string;
};
type UpiLink = { bill: Bill; payee: { name: string; vpa: string }; link: string; qr: string | null; note: string };

type WalletRecord = {
  id: number;
  doc_type: string;
  holder: string;
  label: string;
  number_masked: string;
  expiry: string | null;
  lead_days: number;
  file: string | null;
  notes: string;
  days_left: number | null;
  expired: boolean;
  expiring_soon: boolean;
  reminders: number;
};
type Deadline = { name: string; date: string; days_left: number | null; past: boolean; reminders_set: boolean; error?: string };
type Tax = { lead_days: number; deadlines: Deadline[] };
type WalletData = { items: WalletRecord[]; types: string[]; expiring_soon: number; default_lead_days: number; tax: Tax };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2026-10-15" -> "15 Oct 2026" without going through Date (no timezone shifts).
function day(iso: string | null): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
}

const words = (s: string) => s.replace(/_/g, " ");

type WalletPoll = { data: WalletData | null; error: string; reload: () => Promise<void> };

export default function IndiaTab() {
  const wallet = usePoll(() => api<WalletData>("/api/india/wallet"), 0);
  return (
    <>
      <div className="notice small">
        Bills and wallet records are private: they stay on this computer and are never sent to a model. Jarvis never
        pays anything; a UPI link only hands a bill over to your own UPI app.
      </div>
      <Bills />
      <div className="split">
        <Navs />
        <TaxDeadlines w={wallet} />
      </div>
      <Wallet w={wallet} />
    </>
  );
}

// ---- bills ----

function billStatus(b: Bill): [string, string] {
  if (b.status === "due" && b.overdue) return ["bad", "overdue"];
  if (b.status === "due") return ["warn", "due"];
  if (b.status === "paid") return ["ok", "paid"];
  return ["off", b.status];
}

function Bills() {
  const [status, setStatus] = useState("due");
  const [month, setMonth] = useState("");
  const bills = usePoll(
    () => api<BillsData>(`/api/india/bills?status=${status}${month ? `&month=${month}` : ""}`),
    0,
    [status, month],
  );
  const [error, setError] = useState("");
  const [upi, setUpi] = useState<UpiPreview | null>(null);
  const [link, setLink] = useState<UpiLink | null>(null);
  const d = bills.data;

  async function mark(b: Bill, action: "paid" | "ignore") {
    const q =
      action === "paid"
        ? `Mark bill #${b.id} (${b.biller}, ${b.amount}) as paid? Its reminders are cancelled.`
        : `Ignore bill #${b.id} (${b.biller}, ${b.amount})? It leaves the lists and its reminders are cancelled.`;
    if (!confirm(q)) return;
    setError("");
    try {
      await post(`/api/india/bills/${b.id}/${action}`);
      if (upi?.bill.id === b.id) setUpi(null);
      bills.reload();
    } catch (e) {
      setError(errText(e));
    }
  }

  async function preview(b: Bill) {
    setError("");
    setLink(null);
    try {
      setUpi(await api<UpiPreview>(`/api/india/bills/${b.id}/upi`));
    } catch (e) {
      setError(errText(e));
    }
  }

  async function makeLink() {
    if (!upi?.ready || !upi.payee) return;
    const b = upi.bill;
    const q =
      `Make a UPI link for bill #${b.id}?\n\nBiller: ${b.biller}\nAmount: ${b.amount}\n` +
      `Pay to: ${upi.payee.name} (${upi.payee.vpa})\n\n` +
      "Jarvis does not pay. You open the link in your own UPI app, check the payee and amount there, " +
      "and enter your PIN yourself.";
    if (!confirm(q)) return;
    setError("");
    try {
      setLink(await post<UpiLink>(`/api/india/bills/${b.id}/upi`, { confirm: true, args_sha256: upi.args_sha256 }));
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section className="panel" aria-label="Bills">
      <div className="row">
        <h2 className="grow">Bills, subscriptions and AutoPay</h2>
        <label className="small row">
          Show
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Bill status">
            <option value="due">due</option>
            <option value="paid">paid</option>
            <option value="ignored">ignored</option>
            <option value="all">all (not ignored)</option>
          </select>
        </label>
        <label className="small row">
          Month
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month" />
        </label>
        {month && <button onClick={() => setMonth("")}>All months</button>}
        <button onClick={bills.reload}>Refresh</button>
      </div>
      {d && (
        <div className="row small" style={{ margin: "4px 0 8px" }}>
          <span className="pill warn">{d.counts.due} due</span>
          <span className="pill warn">{d.counts.due_soon} due within 7 days</span>
          <span className={`pill ${d.counts.overdue ? "bad" : "ok"}`}>{d.counts.overdue} overdue</span>
        </div>
      )}
      {(error || bills.error) && <div className="error">{error || bills.error}</div>}
      {d && d.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Biller</th>
              <th className="num">Amount</th>
              <th>Due</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {d.items.map((b) => {
              const [tone, label] = billStatus(b);
              return (
                <tr key={b.id} className={upi?.bill.id === b.id ? "selected" : undefined}>
                  <td>{b.id}</td>
                  <td>
                    <strong>{b.biller}</strong>
                    <div className="small muted">
                      {words(b.category)}, {b.kind}
                      {b.autopay ? " · AutoPay" : ""}
                      {b.period ? ` · ${b.period}` : ""}
                    </div>
                  </td>
                  <td className="num">{b.amount}</td>
                  <td className="small">
                    {b.due_date ? day(b.due_date) : `bill of ${day(b.bill_date)}`}
                    {b.days_left !== null && (
                      <div className="muted">
                        {b.days_left < 0
                          ? `${-b.days_left} day(s) late`
                          : b.days_left === 0
                            ? "today"
                            : `in ${b.days_left} day(s)`}
                      </div>
                    )}
                  </td>
                  <td className="small">
                    <span className={`pill ${tone}`}>{label}</span>
                  </td>
                  <td>
                    <div className="row">
                      {b.status === "due" && <button onClick={() => preview(b)}>UPI link…</button>}
                      {b.status !== "paid" && <button onClick={() => mark(b, "paid")}>Paid</button>}
                      {b.status !== "ignored" && <button onClick={() => mark(b, "ignore")}>Ignore</button>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {d && d.items.length === 0 && (
        <p className="muted">
          No {status === "all" ? "" : status} bills{month ? " this month" : ""}.
        </p>
      )}

      {upi && (
        <div className="subpanel" aria-label="UPI hand-off">
          <div className="row">
            <h3 className="grow">
              UPI link for bill #{upi.bill.id}: {upi.bill.biller} {upi.bill.amount}
            </h3>
            <button
              onClick={() => {
                setUpi(null);
                setLink(null);
              }}
            >
              Close
            </button>
          </div>
          {!upi.ready && <div className="notice small">No link: {upi.reason}.</div>}
          {upi.ready && upi.payee && (
            <>
              <dl className="kv small">
                <dt>Pay to</dt>
                <dd>
                  {upi.payee.name} <code>{upi.payee.vpa}</code>
                </dd>
                <dt>Amount</dt>
                <dd>{upi.bill.amount}</dd>
                <dt>Payee confirmed</dt>
                <dd>by you on {day(upi.payee.confirmed_at)}</dd>
              </dl>
              {!link && (
                <button className="primary" onClick={makeLink}>
                  Make the link
                </button>
              )}
            </>
          )}
          {link && (
            <>
              <pre aria-label="UPI link">{link.link}</pre>
              {link.qr ? (
                <img src={link.qr} alt={`UPI QR code for bill #${link.bill.id}`} width={220} height={220} />
              ) : (
                <p className="small muted">No QR image (the optional qrcode package is not installed).</p>
              )}
              <div className="okbox small">{link.note}</div>
            </>
          )}
        </div>
      )}

      <div className="split" style={{ marginTop: 10 }}>
        <PasteBill onAdded={bills.reload} />
        <div>
          {d?.summary && (
            <>
              <h3>Month summary</h3>
              <pre>{d.summary}</pre>
            </>
          )}
          <h3>Confirmed UPI payees</h3>
          {d && d.payees.length === 0 && <p className="small muted">None yet.</p>}
          {d && d.payees.length > 0 && (
            <table>
              <tbody>
                {d.payees.map((p) => (
                  <tr key={p.biller_key}>
                    <td className="small">{p.name}</td>
                    <td className="small">
                      <code>{p.vpa}</code>
                    </td>
                    <td className="small muted">confirmed {day(p.confirmed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted">
            Payees are added only in a terminal, after you check the UPI ID on the biller&apos;s official app, website or
            bill: <code>jarvis bills payee-add &quot;&lt;name&gt;&quot; &lt;upi-id&gt;</code>. A UPI ID found in an email or SMS is
            never used.
          </p>
        </div>
      </div>
    </section>
  );
}

function PasteBill({ onAdded }: { onAdded: () => void }) {
  const [text, setText] = useState("");
  const [sender, setSender] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await post<{ bill: Bill }>("/api/india/bills", { text, sender });
      const b = r.bill;
      setMsg(
        `Tracked bill #${b.id}: ${b.biller} ${b.amount}` +
          (b.due_date ? `, due ${day(b.due_date)}` : "") +
          ` (${b.status})` +
          (b.reminders ? `; ${b.reminders} reminder(s) set` : ""),
      );
      setText("");
      setSender("");
      onAdded();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={add}>
      <h3>Add a bill from an SMS or email</h3>
      <label className="field">
        Paste the text (read on this computer by fixed rules; only biller, amount and dates are kept)
        <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} maxLength={20000} />
      </label>
      <label className="field">
        Sender (optional)
        <input
          value={sender}
          onChange={(e) => setSender(e.target.value)}
          maxLength={200}
          placeholder="e.g. VM-BILLER or billing@…"
        />
      </label>
      <button className="primary" disabled={busy || !text.trim()}>
        Track bill
      </button>
      {msg && <div className="okbox small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </form>
  );
}

// ---- NAVs ----

function changeText(q: Quote): [string, string] {
  if (q.change === null || q.change_pct === null) return ["off", "no earlier NAV yet"];
  const sign = q.change > 0 ? "+" : "";
  const word = q.change > 0 ? "up" : q.change < 0 ? "down" : "unchanged";
  const text = `${word} ${sign}${q.change.toFixed(4)} (${sign}${q.change_pct.toFixed(2)}%) since ${day(q.prev_date)}`;
  return [q.change > 0 ? "ok" : q.change < 0 ? "bad" : "off", text];
}

function Navs() {
  const nav = usePoll(() => api<NavData>("/api/india/nav"), 0);
  const [shown, setShown] = useState<NavData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const d = shown ?? nav.data;

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const r = await post<NavData>("/api/india/nav/refresh", { force: true });
      setShown(r);
      if (r.error) setError(`${r.error} (showing the saved NAVs)`);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-label="Mutual fund NAVs">
      <div className="row">
        <h2 className="grow">Mutual fund NAVs</h2>
        <button onClick={() => setEditing(!editing)}>{editing ? "Close" : "My schemes"}</button>
        <button className="primary" onClick={refresh} disabled={busy}>
          {busy ? "Fetching…" : "Refresh"}
        </button>
      </div>
      <p className="small muted">
        From AMFI&apos;s official daily NAV file (published by about 9 pm on business days).
        {d?.last_fetch ? ` Last fetched ${d.last_fetch.replace("T", " ").slice(0, 16)}.` : " Not fetched yet."}
      </p>
      {d && !d.fresh && d.schemes.length > 0 && (
        <div className="notice small">
          {d.last_fetch ? `Saved NAVs are older than ${d.refresh_hours} hours.` : "No NAVs saved yet."} Press Refresh to
          fetch AMFI&apos;s file.
        </div>
      )}
      {(error || nav.error) && <div className="error">{error || nav.error}</div>}
      {d && d.schemes.length === 0 && !editing && (
        <p className="muted">No schemes yet. Use “My schemes” to add the ones you hold.</p>
      )}
      {d && d.items.length > 0 && <QuoteTable items={d.items} />}
      {editing && d && (
        <SchemeEditor
          schemes={d.schemes}
          onSaved={(r) => {
            setShown(r);
            setEditing(false);
          }}
        />
      )}
    </section>
  );
}

function QuoteTable({ items, onAdd }: { items: Quote[]; onAdd?: (q: Quote) => void }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Scheme</th>
          <th className="num">NAV</th>
          <th>Change</th>
          {onAdd && <th />}
        </tr>
      </thead>
      <tbody>
        {items.map((q) => {
          const [tone, text] = changeText(q);
          return (
            <tr key={q.code}>
              <td>
                <strong>{q.label}</strong>
                <div className="small muted">
                  {q.code}
                  {q.name && q.name !== q.label ? ` · ${q.name}` : ""}
                </div>
              </td>
              <td className="num">
                {q.nav === null ? "-" : q.nav.toFixed(4)}
                <div className="small muted">{day(q.nav_date)}</div>
              </td>
              <td className="small">
                {q.nav === null ? <span className="muted">no NAV found</span> : <span className={`pill ${tone}`}>{text}</span>}
              </td>
              {onAdd && (
                <td>
                  <button onClick={() => onAdd(q)}>Add</button>
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SchemeEditor({ schemes, onSaved }: { schemes: Scheme[]; onSaved: (d: NavData) => void }) {
  const [rows, setRows] = useState<Scheme[]>(schemes);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Quote[] | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  function add(s: Scheme) {
    if (!/^\d{1,8}$/.test(s.code)) {
      setError("A scheme code is AMFI's number, e.g. 119551.");
      return;
    }
    setError("");
    if (!rows.some((r) => r.code === s.code)) setRows([...rows, { code: s.code, label: s.label.slice(0, 60) }]);
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      setFound((await api<NavData>(`/api/india/nav?q=${encodeURIComponent(q)}`)).items);
    } catch (err) {
      setError(errText(err));
    }
  }

  async function save() {
    if (!confirm("Save these schemes to config/local.yaml on this computer?")) return;
    setError("");
    try {
      onSaved(await post<NavData>("/api/india/nav/schemes", { schemes: rows }));
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <div className="subpanel">
      <h3>My schemes</h3>
      {rows.length === 0 && <p className="small muted">None.</p>}
      {rows.map((r, i) => (
        <div className="row" key={r.code} style={{ marginBottom: 4 }}>
          <code>{r.code}</code>
          <input
            className="grow"
            value={r.label}
            maxLength={60}
            aria-label={`Label for ${r.code}`}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
          />
          <button type="button" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <form className="row" onSubmit={search} style={{ marginTop: 8 }}>
        <input
          className="grow"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          maxLength={80}
          placeholder="find in the saved AMFI file: words of the name, or the code"
          aria-label="Find a scheme"
        />
        <button disabled={!q.trim()}>Find</button>
      </form>
      {found && found.length === 0 && (
        <p className="small muted">No match in the saved file (press Refresh first if it is empty).</p>
      )}
      {found && found.length > 0 && <QuoteTable items={found} onAdd={(x) => add({ code: x.code, label: x.name || x.code })} />}
      <div className="row" style={{ marginTop: 8 }}>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.trim())}
          placeholder="or type a scheme code"
          aria-label="Scheme code"
          style={{ width: 200 }}
        />
        <button
          type="button"
          disabled={!code}
          onClick={() => {
            add({ code, label: code });
            setCode("");
          }}
        >
          Add code
        </button>
        <span className="grow" />
        <button className="primary" type="button" onClick={save}>
          Save schemes
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

// ---- tax deadlines ----

function deadlineTone(x: Deadline, lead: number): [string, string] {
  if (x.error) return ["bad", "bad date"];
  if (x.past) return ["off", "passed"];
  if (x.days_left !== null && x.days_left <= lead) return ["warn", x.days_left === 0 ? "today" : `in ${x.days_left} day(s)`];
  return ["ok", `in ${x.days_left} day(s)`];
}

function TaxDeadlines({ w }: { w: WalletPoll }) {
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const t = w.data?.tax ?? null;

  async function remind() {
    setError("");
    setMsg("");
    try {
      const r = await post<{ scheduled: string[]; tax: Tax }>("/api/india/tax/reminders");
      w.reload();
      setMsg(r.scheduled.length ? `Reminders set for: ${r.scheduled.join("; ")}.` : "No new deadlines to remind.");
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section className="panel" aria-label="Tax deadlines">
      <div className="row">
        <h2 className="grow">Income-tax deadlines</h2>
        <button onClick={remind} title="Reminders before each future deadline (each one only once)">
          Set reminders
        </button>
      </div>
      <p className="small muted">
        Dates come from <code>config/india.yaml</code> (tax.deadlines); check them each year on incometaxindia.gov.in.
        {t ? ` Reminders ${t.lead_days} days before and on the day.` : ""}
      </p>
      {(error || w.error) && <div className="error">{error || w.error}</div>}
      {t && t.deadlines.length === 0 && <p className="muted">No deadlines in the config.</p>}
      {t && t.deadlines.length > 0 && (
        <table>
          <tbody>
            {t.deadlines.map((x) => {
              const [tone, label] = deadlineTone(x, t.lead_days);
              return (
                <tr key={`${x.name}|${x.date}`}>
                  <td className="small">{x.name}</td>
                  <td className="small" style={{ whiteSpace: "nowrap" }}>
                    {day(x.date)}
                  </td>
                  <td className="small">
                    <span className={`pill ${tone}`}>{label}</span>
                  </td>
                  <td className="small muted">{x.past ? "" : x.reminders_set ? "reminders set" : "no reminders yet"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {msg && <div className="okbox small">{msg}</div>}
    </section>
  );
}

// ---- document wallet ----

function expiryTone(r: WalletRecord): [string, string] {
  if (!r.expiry) return ["off", "no expiry"];
  if (r.expired) return ["bad", "expired"];
  if (r.expiring_soon) return ["warn", `expires in ${r.days_left} day(s)`];
  return ["ok", "valid"];
}

function Wallet({ w }: { w: WalletPoll }) {
  const [error, setError] = useState("");
  const d = w.data;

  async function remove(r: WalletRecord) {
    const what = `${r.label || words(r.doc_type)} of ${r.holder}`;
    if (!confirm(`Remove wallet record #${r.id} (${what})? Its reminders are cancelled; a linked file is kept.`)) return;
    setError("");
    try {
      await post(`/api/india/wallet/${r.id}/remove`, { confirm: true });
      w.reload();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section className="panel" aria-label="Document wallet">
      <div className="row">
        <h2 className="grow">Document wallet</h2>
        {d && <span className={`pill ${d.expiring_soon ? "warn" : "ok"}`}>{d.expiring_soon} expiring soon or expired</span>}
        <button onClick={w.reload}>Refresh</button>
      </div>
      <p className="small muted">
        Passport, PAN, licence, insurance, PUC, warranties. Numbers are kept masked (last 4 only); a full Aadhaar or PAN
        number typed in any field is masked before it is saved. Files stay where you put them in the workspace folder.
      </p>
      {(error || w.error) && <div className="error">{error || w.error}</div>}
      {d && d.items.length === 0 && <p className="muted">The wallet is empty.</p>}
      {d && d.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Document</th>
              <th>Holder</th>
              <th>Number</th>
              <th>Expiry</th>
              <th>File / notes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {d.items.map((r) => {
              const [tone, label] = expiryTone(r);
              return (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>
                    <strong>{r.label || words(r.doc_type)}</strong>
                    <div className="small muted">{words(r.doc_type)}</div>
                  </td>
                  <td>{r.holder}</td>
                  <td>
                    <code>{r.number_masked || "-"}</code>
                  </td>
                  <td className="small">
                    {day(r.expiry)}
                    <div>
                      <span className={`pill ${tone}`}>{label}</span>
                    </div>
                  </td>
                  <td className="small cell-wrap">
                    {r.file && <code>{r.file}</code>}
                    {r.notes && <div className="muted">{r.notes}</div>}
                  </td>
                  <td>
                    <button onClick={() => remove(r)}>Remove</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {d && <AddRecord types={d.types} lead={d.default_lead_days} onAdded={w.reload} />}
    </section>
  );
}

function AddRecord({ types, lead, onAdded }: { types: string[]; lead: number; onAdded: () => void }) {
  const empty = { doc_type: "", holder: "", expiry: "", number: "", label: "", lead_days: "", file: "", notes: "" };
  const [f, setF] = useState(empty);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const set = (k: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      const r = await post<{ record: WalletRecord; warnings: string[] }>("/api/india/wallet", {
        doc_type: f.doc_type,
        holder: f.holder,
        expiry: f.expiry || null,
        number: f.number,
        label: f.label,
        lead_days: f.lead_days === "" ? null : Number(f.lead_days),
        file: f.file || null,
        notes: f.notes,
      });
      setMsg(
        `Saved record #${r.record.id}` +
          (r.record.number_masked ? `, number ${r.record.number_masked}` : "") +
          (r.record.reminders ? `; ${r.record.reminders} expiry reminder(s) set` : "") +
          (r.warnings.length ? ` (${r.warnings.join("; ")})` : "") +
          ".",
      );
      setF(empty);
      onAdded();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <form onSubmit={add} className="subpanel">
      <h3>Add a document</h3>
      <div className="row">
        <label className="field">
          Type
          <select value={f.doc_type} onChange={set("doc_type")}>
            <option value="">choose…</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {words(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Holder
          <input value={f.holder} onChange={set("holder")} maxLength={80} placeholder="whose document" />
        </label>
        <label className="field">
          Expiry
          <input type="date" value={f.expiry} onChange={set("expiry")} />
        </label>
        <label className="field">
          Remind days before
          <input
            type="number"
            min={0}
            max={365}
            value={f.lead_days}
            onChange={set("lead_days")}
            placeholder={String(lead)}
            style={{ width: 120 }}
          />
        </label>
      </div>
      <div className="row">
        <label className="field">
          Number (only the last 4 are kept)
          <input
            value={f.number}
            onChange={set("number")}
            maxLength={40}
            autoComplete="off"
            spellCheck={false}
            placeholder="last 4 is enough"
          />
        </label>
        <label className="field grow">
          Label (optional)
          <input value={f.label} onChange={set("label")} maxLength={80} placeholder="e.g. car insurance" />
        </label>
        <label className="field grow">
          File in the workspace (optional)
          <input value={f.file} onChange={set("file")} maxLength={300} placeholder="documents/passport.pdf" />
        </label>
      </div>
      <label className="field">
        Notes (optional)
        <input value={f.notes} onChange={set("notes")} maxLength={500} />
      </label>
      <button className="primary" disabled={!f.doc_type || !f.holder.trim()}>
        Add document
      </button>
      {msg && <div className="okbox small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </form>
  );
}
