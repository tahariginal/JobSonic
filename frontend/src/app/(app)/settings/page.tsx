"use client";
import { Mail, Plus, Search, Send, Trash2 } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { useShell } from "@/components/Shell";
import { Badge, Button, Callout, Card, cx, Empty, ErrorNote, Input, Label, PageHeader, Select, Skeleton, Tabs, Toggle, useToast } from "@/components/ui";
import { api, fmtDate, timeAgo, titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const TABS = [{ id: "account", label: "Account" }, { id: "schedule", label: "Search & schedule" }, { id: "sources", label: "Job sources" }, { id: "ai", label: "AI" }, { id: "email", label: "Email" }, { id: "alerts", label: "Notifications" }, { id: "system", label: "System" }] as const;

export default function SettingsPage() {
  const { data: s, error, reload, setData } = useApi<any>("/settings");
  const toast = useToast();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("schedule");
  const [gmail, setGmail] = useState("");
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("gmail")) { setGmail(sp.get("gmail")!); setTab("email"); window.history.replaceState(null, "", window.location.pathname); }
    if (sp.get("tab")) setTab(sp.get("tab") as any);
  }, []);
  async function patch(section: string, values: any, msg = "Saved.") {
    try { const r = await api("/settings", { method: "PUT", body: { [section]: values } }); setData(r); toast(msg); }
    catch (e: any) { toast(e.message, "error"); reload(); }
  }
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!s) return <div className="space-y-3"><Skeleton className="h-9 w-40" /><Skeleton className="h-80" /></div>;
  return (
    <div className="animate-in mx-auto max-w-4xl">
      <PageHeader title="Settings" />
      <Tabs value={tab} onChange={setTab} items={TABS as any} />
      <div className="mt-5 space-y-4">
        {tab === "account" && <Account />}
        {tab === "schedule" && <Schedule s={s} patch={patch} />}
        {tab === "sources" && <Sources />}
        {tab === "ai" && <AI s={s} patch={patch} />}
        {tab === "email" && <Email s={s} gmail={gmail} reload={reload} />}
        {tab === "alerts" && <Alerts s={s} patch={patch} reload={reload} />}
        {tab === "system" && <System s={s} />}
      </div>
    </div>
  );
}

function Account() {
  const { username, setUsername } = useShell();
  const toast = useToast();
  const [name, setName] = useState(username);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault(); setError("");
    if (password !== confirmation) { setError("New passwords do not match."); return; }
    setBusy(true);
    try {
      const result = await api<{ username: string }>("/auth/account", { method: "PUT", body: {
        username: name.trim(), current_password: current, ...(password ? { new_password: password } : {}),
      } });
      setUsername(result.username); setName(result.username);
      setCurrent(""); setPassword(""); setConfirmation("");
      toast("Account updated. Other sessions have been signed out.");
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  return <Card className="p-5">
    <h2 className="text-[13px] font-semibold">Sign-in details</h2>
    <p className="mt-0.5 text-xs leading-relaxed text-ink-3">Change your username or password. Enter your current password to save. Other sessions will be signed out.</p>
    <form onSubmit={save} className="mt-4 max-w-md space-y-4">
      <div><Label htmlFor="account-username">Username</Label><Input id="account-username" required maxLength={64} autoComplete="username" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div><Label htmlFor="account-current-password">Current password</Label><Input id="account-current-password" required type="password" maxLength={256} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></div>
      <div><Label htmlFor="account-new-password">New password</Label><Input id="account-new-password" type="password" minLength={12} maxLength={256} autoComplete="new-password" aria-describedby="account-password-help" value={password} onChange={(e) => setPassword(e.target.value)} /><p id="account-password-help" className="mt-1 text-xs text-ink-3">At least 12 characters. Leave blank to keep your current password.</p></div>
      <div><Label htmlFor="account-confirm-password">Confirm new password</Label><Input id="account-confirm-password" type="password" required={!!password} maxLength={256} autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || (name.trim() === username && !password)}>Save account</Button>
    </form>
  </Card>;
}

function Row({ title, desc, children }: { title: string; desc?: React.ReactNode; children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-line/70 py-4 first:pt-0 last:border-0 last:pb-0"><div className="min-w-0 max-w-xl"><p className="text-[13.5px] font-medium">{title}</p>{desc && <p className="mt-0.5 text-xs leading-relaxed text-ink-3">{desc}</p>}</div><div className="flex shrink-0 items-center gap-2">{children}</div></div>;
}
function Num({ value, onCommit, min = 0, max = 100000, step = 1, suffix, label }: { value: number; onCommit: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string; label: string }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  return <span className="flex items-center gap-2"><Input aria-label={label} type="number" min={min} max={max} step={step} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => { const n = Number(v); if (!Number.isNaN(n) && n !== value) onCommit(Math.min(max, Math.max(min, n))); else setV(String(value)); }} className="w-24 text-right tabular" />{suffix && <span className="text-xs text-ink-3">{suffix}</span>}</span>;
}

function Schedule({ s, patch }: any) {
  const { runSearch, searching } = useShell();
  const sc = s.schedule, se = s.search, lr = s.last_runs ?? {};
  const [kw, setKw] = useState(""); const [ex, setEx] = useState("");
  return (<>
    <Card className="p-5">
      <Row title="Automatic job search" desc={lr.discovery ? `Last run ${timeAgo(lr.discovery.at)}: ${lr.discovery.new} new, ${lr.discovery.updated} updated, ${lr.discovery.closed} closed across ${lr.discovery.companies} sources.` : "Has not run yet."}><Toggle label="Automatic job search" checked={sc.discovery_enabled} onChange={(v) => patch("schedule", { discovery_enabled: v })} /></Row>
      <Row title="Search every" desc="All sources are re-read from their official job boards. Scripts only; no AI is involved."><Num label="Search interval in hours" value={sc.discovery_interval_hours} min={1} max={168} suffix="hours" onCommit={(v) => patch("schedule", { discovery_interval_hours: v })} /></Row>
      <Row title="Re-verify jobs you are working on" desc="Shortlisted, preparing and awaiting-approval jobs are checked against the official source so you never apply to a closed vacancy."><Toggle label="Re-verify active jobs" checked={sc.verify_enabled} onChange={(v) => patch("schedule", { verify_enabled: v })} /><Num label="Verify interval in hours" value={sc.verify_interval_hours} min={1} max={168} suffix="hours" onCommit={(v) => patch("schedule", { verify_interval_hours: v })} /></Row>
      <Row title="Run a search now" desc="Queues one full search immediately."><Button variant="primary" loading={searching} icon={<Search className="size-4" />} onClick={runSearch}>Run job search</Button></Row>
    </Card>
    <Card className="p-5">
      <h2 className="mb-4 text-[13px] font-semibold">Search → prepare → fill → track</h2>
      <Row title="Automatically fill applications after each full search" desc="Confirmed visa sponsorship first, then remote roles, ranked by fit. Only active jobs marked eligible are selected. Each job is attempted once; forms wait for your approval before submission."><Toggle label="Automatically fill applications" checked={s.automation.auto_fill_enabled} onChange={(v) => patch("automation", { auto_fill_enabled: v })} /></Row>
      <Row title="Include other suitable jobs after priority matches" desc="Other eligible roles can fill the remaining places in each cycle."><Toggle label="Include other suitable jobs" checked={s.automation.include_other_matches} onChange={(v) => patch("automation", { include_other_matches: v })} /></Row>
      <Row title="Applications per cycle" desc="Maximum new applications prepared and filled after each search. Existing, previously attempted, and archived applications are skipped."><Num label="Applications per cycle" value={s.automation.max_applications_per_cycle} min={1} max={100} onCommit={(v) => patch("automation", { max_applications_per_cycle: v })} /></Row>
      <p className="mt-4 text-xs text-ink-3">Follow queued work, filled forms, and questions that need your input in Application tracker. Pausing automatic filling also stops queued automatic applications from opening forms.</p>
    </Card>
    <Card className="p-5">
      <h2 className="text-[13px] font-semibold">Title matching</h2>
      <p className="mt-0.5 text-xs text-ink-3">Engineering titles matching your target roles are kept automatically. Add keywords to widen or narrow that.</p>
      <div className="mt-4 grid gap-5 sm:grid-cols-2">
        <KwList label="Also include titles containing" values={se.extra_title_keywords} draft={kw} setDraft={setKw} onChange={(v: string[]) => patch("search", { extra_title_keywords: v })} placeholder="e.g. forward deployed" />
        <KwList label="Always exclude titles containing" values={se.exclude_title_keywords} draft={ex} setDraft={setEx} onChange={(v: string[]) => patch("search", { exclude_title_keywords: v })} placeholder="e.g. embedded" />
      </div>
      <p className="mt-4 text-xs text-ink-3">Changes apply from the next search. The experience limit (max years) is in Profile → Work authorization &amp; preferences.</p>
    </Card>
  </>);
}
function KwList({ label, values, draft, setDraft, onChange, placeholder }: any) {
  const add = () => { const v = draft.trim().toLowerCase(); if (v && !values.includes(v)) onChange([...values, v]); setDraft(""); };
  return <div><Label>{label}</Label><div className="flex flex-wrap gap-1.5">{values.map((v: string) => <span key={v} className="inline-flex items-center gap-1 rounded-lg border border-line bg-raised py-1 pl-2.5 pr-1 text-[13px]">{v}<button aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x: string) => x !== v))} className="rounded p-0.5 text-ink-3 hover:text-bad"><Trash2 className="size-3" /></button></span>)}<span className="inline-flex gap-1.5"><Input aria-label={label} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder={placeholder} className="h-8 w-44 text-[13px]" /><Button size="sm" onClick={add} disabled={!draft.trim()}>Add</Button></span></div></div>;
}

function Sources() {
  const { data, error, reload } = useApi<any[]>("/companies", 20000);
  const toast = useToast();
  const [q, setQ] = useState(""); const [provider, setProvider] = useState("greenhouse"); const [token, setToken] = useState(""); const [busy, setBusy] = useState(false);
  const rows = useMemo(() => (data ?? []).filter((c) => !q || c.name.toLowerCase().includes(q.toLowerCase()) || c.board_token.includes(q.toLowerCase())), [data, q]);
  async function add(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try { const c = await api("/companies", { body: { provider, board_token: token.trim() } }); toast(`${c.name} added and verified. Searching it now.`); setToken(""); reload(); }
    catch (err: any) { toast(err.message, "error"); } finally { setBusy(false); }
  }
  if (error) return <ErrorNote>{error}</ErrorNote>;
  return (<>
    <Card className="p-5">
      <h2 className="text-[13px] font-semibold">Add an employer job board</h2>
      <p className="mt-0.5 text-xs leading-relaxed text-ink-3">The board ID is the last part of the company's careers URL, e.g. <span className="font-mono text-ink-2">job-boards.greenhouse.io/<b>stripe</b></span>, <span className="font-mono text-ink-2">jobs.lever.co/<b>spotify</b></span>, <span className="font-mono text-ink-2">jobs.ashbyhq.com/<b>notion</b></span>. It is checked against the official API before being saved.</p>
      <form onSubmit={add} className="mt-3 flex flex-wrap gap-2">
        <Select aria-label="Provider" value={provider} onChange={(e) => setProvider(e.target.value)} className="w-40"><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option></Select>
        <Input aria-label="Board ID" required value={token} onChange={(e) => setToken(e.target.value)} placeholder="board id" pattern="[A-Za-z0-9._\-]+" className="w-56" />
        <Button type="submit" variant="primary" loading={busy} icon={<Plus className="size-4" />}>Verify &amp; add</Button>
      </form>
    </Card>
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4"><h2 className="text-[13px] font-semibold">Sources <span className="ml-1 font-normal text-ink-3">{data ? `${data.filter((c) => c.enabled).length} active of ${data.length}` : ""}</span></h2><Input aria-label="Filter sources" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="h-8 w-48 text-[13px]" /></div>
      {!data ? <div className="p-5"><Skeleton className="h-40" /></div> : rows.length === 0 ? <Empty title="No sources match" /> : (
        <ul className="mt-3 max-h-[560px] divide-y divide-line/60 overflow-y-auto">
          {rows.map((c) => (
            <li key={c.id} className={cx("flex items-center gap-3 px-5 py-2.5", !c.enabled && "opacity-50")}>
              <div className="min-w-0 flex-1"><p className="truncate text-[13.5px] font-medium">{c.name} <span className="ml-1 text-xs font-normal text-ink-3">{titleCase(c.provider)} · {c.board_token}</span></p>
                <p className={cx("truncate text-xs", c.last_status.startsWith("error") ? "text-[#f19191]" : "text-ink-3")}>{c.last_fetch_at ? `${c.last_status} · ${timeAgo(c.last_fetch_at)}` : "Not fetched yet"}</p></div>
              <span className="hidden text-right text-xs text-ink-3 sm:block"><span className="tabular text-ink-2">{c.relevant_jobs}</span> match{c.relevant_jobs === 1 ? "" : "es"}</span>
              <Toggle label={`Enable ${c.name}`} checked={c.enabled} onChange={(v) => api(`/companies/${c.id}`, { method: "PATCH", body: { enabled: v } }).then(reload).catch((e) => toast(e.message, "error"))} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  </>);
}

function AI({ s, patch }: any) {
  const a = s.ai, st = s.ai_status;
  const serverOff = s.server.ai_mode === "off";
  return (<>
    <Callout tone={st.available ? "info" : "accent"} title={st.available ? `AI is on (${st.model} via the local Claude CLI)` : "AI is off — the system runs on rules only"}>
      {st.available ? "It is used only when you prepare an application or request an AI review, within the budgets below." : st.reason}
    </Callout>
    {serverOff && (
      <Card className="p-5 text-[13px] leading-relaxed text-ink-2">
        <h2 className="mb-1 text-[13px] font-semibold text-ink">How to enable it</h2>
        <p>AI execution has a server-side switch that is deliberately not changeable from the browser. This server's Claude Code is signed in with a personal <strong className="text-ink">subscription</strong> login; unattended use draws from that plan's limits. If you accept that, set <span className="font-mono text-ink">SONIC_AI_MODE=claude_cli</span> in <span className="font-mono text-ink">.env</span>, restart the services, then turn on the switch below. No API key is used and nothing is billed per call. See <span className="font-mono text-ink">docs/AI_COSTS.md</span>.</p>
      </Card>
    )}
    <Card className="p-5">
      <Row title="Use AI when preparing applications" desc="Writes the cover letter and free-text answers from your profile facts only. Without it, a plain factual template is used and unknown questions wait for you."><Toggle label="Enable AI" checked={a.enabled} onChange={(v) => patch("ai", { enabled: v })} /></Row>
      <Row title="Automatically AI-review strong new matches" desc="After each search, promising jobs get a deeper read. Off by default to keep usage low."><Toggle label="Auto evaluate" checked={a.auto_evaluate} disabled={!a.enabled} onChange={(v) => patch("ai", { auto_evaluate: v })} /><Select aria-label="Minimum stars for AI review" value={a.min_stars_for_ai} onChange={(e) => patch("ai", { min_stars_for_ai: Number(e.target.value) })} className="w-28">{[3, 4, 5].map((n) => <option key={n} value={n}>{n}★ and up</option>)}</Select></Row>
      <Row title="Daily budget" desc={`Used today: ${st.usage.today.calls} calls, est. $${st.usage.today.est_cost_usd.toFixed(3)}.`}><Num label="Daily call budget" value={a.daily_call_budget} max={1000} suffix="calls" onCommit={(v) => patch("ai", { daily_call_budget: v })} /><Num label="Daily cost budget" value={a.daily_usd_budget} max={1000} step={0.5} suffix="USD" onCommit={(v) => patch("ai", { daily_usd_budget: v })} /></Row>
      <Row title="Monthly budget" desc={`Used this month: ${st.usage.month.calls} calls, est. $${st.usage.month.est_cost_usd.toFixed(3)}. When a budget is reached AI stops; everything else keeps working.`}><Num label="Monthly call budget" value={a.monthly_call_budget} max={20000} suffix="calls" onCommit={(v) => patch("ai", { monthly_call_budget: v })} /><Num label="Monthly cost budget" value={a.monthly_usd_budget} max={10000} step={1} suffix="USD" onCommit={(v) => patch("ai", { monthly_usd_budget: v })} /></Row>
    </Card>
  </>);
}

function Email({ s, gmail, reload }: any) {
  const st = useApi<any>("/email/status");
  const mails = useApi<any[]>("/emails");
  const apps = useApi<any[]>("/applications?status=submitted|submit_uncertain");
  const toast = useToast();
  const [cid, setCid] = useState(""); const [sec, setSec] = useState(""); const [busy, setBusy] = useState("");
  const g = s.google_oauth;
  async function saveClient(e: React.FormEvent) { e.preventDefault(); setBusy("save"); try { await api("/settings/google-oauth", { method: "PUT", body: { client_id: cid, client_secret: sec } }); toast("Google OAuth client saved (encrypted)."); setSec(""); reload(); st.reload(); } catch (err: any) { toast(err.message, "error"); } finally { setBusy(""); } }
  async function connect() { setBusy("connect"); try { const r = await api("/email/oauth/start"); window.location.href = r.url; } catch (err: any) { toast(err.message, "error"); setBusy(""); } }
  return (<>
    {gmail === "connected" && <Callout tone="info" title="Gmail connected (read-only)." />}
    {gmail === "failed" && <Callout tone="bad" title="Gmail connection failed">Check that the redirect URL below is registered exactly in your Google Cloud OAuth client, then try again.</Callout>}
    {gmail === "denied" && <Callout tone="warn" title="Gmail access was not granted." />}
    <Card className="p-5">
      <div className="flex items-start gap-3"><span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line bg-raised text-ink-3"><Mail className="size-5" /></span>
        <div><h2 className="text-[13px] font-semibold">Gmail tracking</h2><p className="mt-0.5 text-xs leading-relaxed text-ink-3">Detects confirmations, interview invitations, replies, rejections and offers and links them to your applications. Access is <strong className="text-ink-2">read-only</strong> (scope <span className="font-mono">gmail.readonly</span>): this system cannot send, reply to, label or delete mail. Your Gmail password is never requested.</p></div></div>
      <div className="mt-4 border-t border-line/70 pt-4">
        {(st.data?.accounts ?? []).length > 0 ? (
          <ul className="space-y-2">{st.data.accounts.map((a: any) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-3.5">
              <div><p className="text-[13.5px] font-medium">{a.email} <Badge tone="good" className="ml-1">Connected</Badge></p><p className={cx("text-xs", a.last_error ? "text-[#f19191]" : "text-ink-3")}>{a.last_error || (a.last_sync_at ? `Last checked ${timeAgo(a.last_sync_at)}` : "Not checked yet")}</p></div>
              <div className="flex gap-2"><Button size="sm" loading={busy === "sync"} onClick={async () => { setBusy("sync"); try { await api("/email/sync", { method: "POST" }); toast("Checking mail…"); } catch (e: any) { toast(e.message, "error"); } finally { setBusy(""); } }}>Check now</Button>
                <Button size="sm" variant="danger" onClick={() => { if (confirm(`Disconnect ${a.email}?`)) api(`/email/accounts/${a.id}`, { method: "DELETE" }).then(() => { st.reload(); toast("Disconnected."); }); }}>Disconnect</Button></div>
            </li>))}</ul>
        ) : (
          <div className="space-y-4 text-[13px] leading-relaxed text-ink-2">
            <Badge tone="warn">Needs configuration</Badge>
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>In Google Cloud Console create an OAuth client of type “Web application” and enable the Gmail API for the project.</li>
              <li>Add this authorised redirect URI: {g.redirect_uri ? <span className="break-all font-mono text-ink">{g.redirect_uri}</span> : <span className="text-warn">not available — set SONIC_PUBLIC_BASE_URL in .env to the dashboard's HTTPS address first</span>}</li>
              <li>Paste the client ID and secret below, then connect.</li>
            </ol>
            <form onSubmit={saveClient} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <div><Label htmlFor="gcid">Client ID {g.configured && <span className="font-normal text-good">· saved</span>}</Label><Input id="gcid" required value={cid} onChange={(e) => setCid(e.target.value)} placeholder={g.client_id || "….apps.googleusercontent.com"} autoComplete="off" /></div>
              <div><Label htmlFor="gsec">Client secret</Label><Input id="gsec" required type="password" value={sec} onChange={(e) => setSec(e.target.value)} placeholder={g.configured ? "•••••••• (stored encrypted)" : ""} autoComplete="off" /></div>
              <Button type="submit" loading={busy === "save"}>Save</Button>
            </form>
            <Button variant="primary" disabled={!g.configured || !g.redirect_uri} loading={busy === "connect"} onClick={connect} icon={<Mail className="size-4" />}>Connect Gmail (read-only)</Button>
          </div>
        )}
      </div>
    </Card>
    <Card>
      <div className="px-5 pt-4"><h2 className="text-[13px] font-semibold">Detected emails</h2><p className="mt-0.5 text-xs text-ink-3">Correct the category or the linked application if the automatic match is wrong. Ambiguous emails never change your pipeline.</p></div>
      {(mails.data ?? []).length === 0 ? <Empty title="No application emails detected yet" /> : (
        <ul className="mt-3 divide-y divide-line/60">{mails.data!.map((m) => (
          <li key={m.id} className="px-5 py-3">
            <p className="truncate text-[13.5px] font-medium">{m.subject}</p><p className="truncate text-xs text-ink-3">{m.from} · {fmtDate(m.received_at)} · {Math.round(m.confidence * 100)}% sure{m.manually_corrected && " · corrected by you"}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Select aria-label="Category" value={m.category} className="h-8 w-44 text-[13px]" onChange={(e) => api(`/emails/${m.id}`, { method: "PATCH", body: { category: e.target.value } }).then(mails.reload)}>{["confirmation", "interview", "rejection", "offer", "documents", "recruiter_reply", "other"].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}</Select>
              <Select aria-label="Linked application" value={m.application_id ?? ""} className="h-8 w-64 text-[13px]" onChange={(e) => api(`/emails/${m.id}`, { method: "PATCH", body: e.target.value ? { application_id: Number(e.target.value) } : { unlink: true } }).then(mails.reload)}><option value="">Not linked</option>{(apps.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.company} — {a.title}</option>)}</Select>
            </div>
          </li>))}</ul>
      )}
    </Card>
  </>);
}

function Alerts({ s, patch, reload }: any) {
  const toast = useToast();
  const [tok, setTok] = useState(""); const [chat, setChat] = useState(""); const [busy, setBusy] = useState(false);
  const n = s.notifications, tg = s.telegram;
  async function save(e: React.FormEvent) { e.preventDefault(); setBusy(true); try { const r = await api("/settings/telegram", { method: "PUT", body: { bot_token: tok, chat_id: chat } }); toast(r.test_sent ? "Saved. A test message was sent to Telegram." : "Saved, but the test message could not be delivered. Check the token and chat ID.", r.test_sent ? "ok" : "error"); setTok(""); reload(); } catch (err: any) { toast(err.message, "error"); } finally { setBusy(false); } }
  return (<>
    <Card className="p-5">
      <Row title="Alert me about new jobs rated" desc="Jobs with explicitly mentioned sponsorship always alert. Each job alerts once; unchanged jobs never repeat."><Select aria-label="Minimum stars for alerts" value={n.min_stars} onChange={(e) => patch("notifications", { min_stars: Number(e.target.value) })} className="w-32">{[3, 4, 5].map((x) => <option key={x} value={x}>{x}★ and up</option>)}</Select></Row>
      <Row title="Dashboard notifications" desc="Approvals waiting, form errors, failed runs, interview invitations and recruiter replies always appear in the bell menu."><Badge tone="good">Always on</Badge></Row>
    </Card>
    <Card className="p-5">
      <div className="flex items-start gap-3"><span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line bg-raised text-ink-3"><Send className="size-5" /></span><div><h2 className="text-[13px] font-semibold">Telegram (optional)</h2><p className="mt-0.5 text-xs leading-relaxed text-ink-3">Get the same alerts on your phone. Create a bot with @BotFather, send it a message, and enter its token and your chat ID. The token is stored encrypted and never shown again.</p></div></div>
      <div className="mt-4 border-t border-line/70 pt-4">
        {tg.configured ? (
          <><Row title={`Connected to chat ${tg.chat_id}`} desc="Send dashboard notifications to Telegram as well."><Toggle label="Telegram alerts" checked={n.telegram_enabled} onChange={(v) => patch("notifications", { telegram_enabled: v })} /><Button size="sm" variant="danger" onClick={() => api("/settings/telegram", { method: "DELETE" }).then(() => { toast("Telegram removed."); reload(); })}>Remove</Button></Row></>
        ) : (
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-[1fr_180px_auto] sm:items-end">
            <div><Label htmlFor="tgt">Bot token</Label><Input id="tgt" required type="password" value={tok} onChange={(e) => setTok(e.target.value)} placeholder="123456:ABC…" autoComplete="off" /></div>
            <div><Label htmlFor="tgc">Chat ID</Label><Input id="tgc" required value={chat} onChange={(e) => setChat(e.target.value)} placeholder="123456789" /></div>
            <Button type="submit" variant="primary" loading={busy}>Save &amp; test</Button>
          </form>
        )}
      </div>
    </Card>
  </>);
}

function System({ s }: any) {
  const audit = useApi<any[]>("/audit");
  const Flag = ({ ok, children }: { ok: boolean; children: React.ReactNode }) => <li className="flex items-start gap-2.5 text-[13px]"><span className={cx("mt-1.5 size-2 shrink-0 rounded-full", ok ? "bg-good" : "bg-warn")} /><span className="text-ink-2">{children}</span></li>;
  return (<>
    <Card className="p-5">
      <h2 className="mb-3 text-[13px] font-semibold">Server status</h2>
      <ul className="space-y-2">
        <Flag ok={s.server.cookie_secure}>Session cookies are {s.server.cookie_secure ? "HTTPS-only" : "allowed over plain HTTP (tunnel mode)"}.</Flag>
        <Flag ok={s.server.allow_real_submit}>Real form submission is {s.server.allow_real_submit ? "enabled, and only ever after your approval of the exact version" : "disabled on the server (SONIC_ALLOW_REAL_SUBMIT=false): approved applications will stop before the submit button"}.</Flag>
        <Flag ok>AI execution mode: <span className="font-mono text-ink">{s.server.ai_mode}</span>.</Flag>
        <Flag ok={s.telegram.configured}>Telegram: {s.telegram.configured ? "configured" : "not configured (optional)"}.</Flag>
        <Flag ok={s.google_oauth.configured}>Gmail OAuth client: {s.google_oauth.configured ? "configured" : "not configured"}.</Flag>
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-ink-3">Server-side switches live in <span className="font-mono">.env</span> and need a service restart; they cannot be changed from the browser on purpose. See <span className="font-mono">docs/DEPLOYMENT.md</span>.</p>
    </Card>
    <Card>
      <div className="px-5 pt-4"><h2 className="text-[13px] font-semibold">Audit log</h2><p className="mt-0.5 text-xs text-ink-3">Sign-ins, approvals, edits and configuration changes.</p></div>
      <ul className="mt-3 max-h-[420px] divide-y divide-line/60 overflow-y-auto">{(audit.data ?? []).map((a) => <li key={a.id} className="flex flex-wrap items-center justify-between gap-x-4 px-5 py-2 text-[13px]"><span className="font-mono text-xs text-ink-2">{a.action}</span><span className="text-xs text-ink-3">{a.target}</span><span className="ml-auto text-xs text-ink-3">{a.ip && `${a.ip} · `}{fmtDate(a.created_at)}</span></li>)}</ul>
    </Card>
  </>);
}
