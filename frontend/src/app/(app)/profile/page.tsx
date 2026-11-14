"use client";
import { FileUp, Plus, Star, Trash2 } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { Badge, Button, Callout, Card, cx, Empty, ErrorNote, Input, Label, PageHeader, Skeleton, Tabs, Textarea, Toggle, useToast } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type P = any;
const TABS = [{ id: "personal", label: "Personal" }, { id: "background", label: "Education & experience" }, { id: "skills", label: "Skills & projects" }, { id: "auth", label: "Work authorization & preferences" }, { id: "answers", label: "Standard answers" }, { id: "documents", label: "CVs & documents" }] as const;

export default function ProfilePage() {
  const { data, error, reload } = useApi<any>("/profile");
  const docs = useApi<any[]>("/documents");
  const toast = useToast();
  const [p, setP] = useState<P | null>(null);
  const [saved, setSaved] = useState("");
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("personal");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data && !p) { setP(data.data); setSaved(JSON.stringify(data.data)); } }, [data, p]);
  const dirty = p !== null && JSON.stringify(p) !== saved;
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", h); return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!p) return <div className="space-y-3"><Skeleton className="h-9 w-48" /><Skeleton className="h-96" /></div>;

  const up = (path: string, value: any) => setP((prev: P) => { const n = structuredClone(prev); const keys = path.split("."); let o = n; for (const k of keys.slice(0, -1)) o = o[k]; o[keys[keys.length - 1]] = value; return n; });
  const txt = (path: string, label: string, opts: { hint?: string; type?: string; placeholder?: string; area?: boolean } = {}) => {
    const v = path.split(".").reduce((o: any, k) => o[k], p) ?? "";
    const id = `f-${path}`;
    return (<div><Label htmlFor={id} hint={opts.hint}>{label}</Label>{opts.area ? <Textarea id={id} rows={3} value={v} placeholder={opts.placeholder} onChange={(e) => up(path, e.target.value)} /> : <Input id={id} type={opts.type ?? "text"} value={v} placeholder={opts.placeholder} onChange={(e) => up(path, e.target.value)} />}</div>);
  };
  async function save() {
    setBusy(true);
    try { const r = await api("/profile", { method: "PUT", body: p }); setSaved(JSON.stringify(p)); toast("Profile saved. Jobs are being re-scored."); reload(); void r; }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }

  return (
    <div className="animate-in mx-auto max-w-4xl">
      <PageHeader title="Candidate profile" subtitle="Your profile and saved answers are used to fill applications. Keep your details, preferred start date, and reusable answers up to date here." />
      {data?.gaps?.length > 0 && <div className="mb-5"><Callout tone="warn" title="Still missing">{data.gaps.join(" · ")}</Callout></div>}
      <Tabs value={tab} onChange={setTab} items={TABS as any} />

      <div className="mt-5 space-y-4">
        {tab === "personal" && (<>
          <Card className="p-5"><div className="grid gap-4 sm:grid-cols-2">
            {txt("personal.first_name", "First name")}{txt("personal.last_name", "Last name")}
            {txt("personal.email", "Contact email", { type: "email", hint: "used on application forms" })}{txt("personal.phone", "Phone", { placeholder: "+212…" })}
            {txt("personal.city", "City")}{txt("personal.country", "Country of residence")}{txt("personal.citizenship", "Citizenship")}{txt("personal.headline", "Headline")}
            <div className="sm:col-span-2">{txt("personal.summary", "Short summary", { area: true, hint: "optional, in your own words" })}</div>
          </div></Card>
          <Card className="p-5"><h2 className="mb-3 text-[13px] font-semibold">Links</h2><div className="grid gap-4 sm:grid-cols-2">
            {txt("links.linkedin", "LinkedIn", { placeholder: "https://www.linkedin.com/in/…" })}{txt("links.github", "GitHub")}{txt("links.portfolio", "Portfolio")}
            <StrList label="Email accounts you apply from" values={p.email_accounts} onChange={(v) => up("email_accounts", v)} placeholder="name@example.com" />
          </div></Card>
          <Rows title="Languages" hint="Only languages listed here count as confirmed when a job requires one." items={p.languages} onChange={(v) => up("languages", v)} blank={{ language: "", level: "" }} fields={[["language", "Language"], ["level", "Level (e.g. native, fluent, B2)"]]} />
        </>)}

        {tab === "background" && (<>
          <Rows title="Education" hint="Describe credentials exactly as they are. The 42 Common Core is never presented as a bachelor's degree." items={p.education} onChange={(v) => up("education", v)} blank={{ school: "", program: "", credential: "", start: "", end: "", notes: "" }}
            fields={[["school", "School"], ["program", "Programme"], ["credential", "Credential (exact wording)"], ["start", "Start"], ["end", "End"], ["notes", "Notes", "area"]]} />
          <Rows title="Work experience" items={p.experience} onChange={(v) => up("experience", v)} blank={{ company: "", title: "", kind: "", start: "", end: "", location: "", description: "" }}
            fields={[["company", "Company"], ["title", "Title"], ["kind", "Type (internship, full-time…)"], ["location", "Location"], ["start", "Start"], ["end", "End"], ["description", "What you did (facts only)", "area"]]} />
        </>)}

        {tab === "skills" && (<>
          <Card className="space-y-5 p-5">
            <StrList label="Skills" hint="Technologies you can actually work with. These drive the fit score." values={p.skills} onChange={(v) => up("skills", v)} placeholder="e.g. Python" chips />
            <StrList label="Interests" hint="Areas you want to work in." values={p.interests} onChange={(v) => up("interests", v)} placeholder="e.g. AI agents" chips />
          </Card>
          <Rows title="Projects" hint="Describe only what is really implemented; set the status honestly." items={p.projects} onChange={(v) => up("projects", v)} blank={{ name: "", description: "", url: "", tech: [], status: "" }}
            fields={[["name", "Name"], ["status", "Status (in progress, shipped…)"], ["url", "URL"], ["tech", "Technologies (comma separated)", "list"], ["description", "Description", "area"]]} />
        </>)}

        {tab === "auth" && (<>
          <Card className="space-y-4 p-5">
            <h2 className="text-[13px] font-semibold">Work authorization</h2>
            <StrList label="Countries where you can already work" hint="Jobs elsewhere are treated as needing sponsorship." values={p.work_authorization.authorized_countries} onChange={(v) => up("work_authorization.authorized_countries", v)} placeholder="Country" chips />
            <div className="flex items-center justify-between gap-4 rounded-xl border border-line p-3.5"><div><p className="text-[13px] font-medium">I need employer sponsorship everywhere else</p><p className="text-xs text-ink-3">Used to answer “Will you require sponsorship?” truthfully.</p></div><Toggle label="Needs sponsorship elsewhere" checked={p.work_authorization.needs_sponsorship_elsewhere} onChange={(v) => up("work_authorization.needs_sponsorship_elsewhere", v)} /></div>
            {txt("work_authorization.notes", "Notes", { area: true })}
          </Card>
          <Card className="space-y-4 p-5">
            <h2 className="text-[13px] font-semibold">Preferences</h2>
            <StrList label="Target roles" values={p.preferences.target_roles} onChange={(v) => up("preferences.target_roles", v)} placeholder="Role title" chips />
            <StrList label="Preferred countries" hint="Leave empty to use the default regional priorities." values={p.preferences.countries} onChange={(v) => up("preferences.countries", v)} placeholder="Country" chips />
            <div className="grid gap-4 sm:grid-cols-3">
              <div><Label htmlFor="sal">Minimum salary (yearly)</Label><Input id="sal" type="number" min={0} value={p.preferences.salary_min ?? ""} onChange={(e) => up("preferences.salary_min", e.target.value === "" ? null : Number(e.target.value))} /></div>
              {txt("preferences.salary_currency", "Currency", { placeholder: "EUR" })}
              <div><Label htmlFor="yrs" hint="jobs asking more are filtered">Max years required</Label><Input id="yrs" type="number" min={0} max={10} step={0.5} value={p.preferences.max_years_experience} onChange={(e) => up("preferences.max_years_experience", Number(e.target.value))} /></div>
              <div><Label htmlFor="start" hint="your wish, not visa timing">Earliest start date</Label><Input id="start" type="date" value={p.preferences.earliest_start_date} onChange={(e) => up("preferences.earliest_start_date", e.target.value)} /></div>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-2.5"><span className="text-[13px]">Open to relocation</span><Toggle label="Open to relocation" checked={p.preferences.open_to_relocation} onChange={(v) => up("preferences.open_to_relocation", v)} /></div>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-2.5"><span className="text-[13px]">Open to remote</span><Toggle label="Open to remote" checked={p.preferences.open_to_remote} onChange={(v) => up("preferences.open_to_remote", v)} /></div>
            </div>
          </Card>
        </>)}

        {tab === "answers" && <>
          <Card className="space-y-3 p-5">
            <h2 className="text-[13px] font-semibold">Automatic motivation answer</h2>
            <p className="text-xs text-ink-3">Used for questions such as “Why us?” or “Why do you want to join?” even when AI is off. A matching standard answer below takes priority.</p>
            <div><Label htmlFor="motivation">Why this company?</Label><Textarea id="motivation" rows={5} value={p.preferences.motivation_answer ?? ""} onChange={(e) => up("preferences.motivation_answer", e.target.value)} /></div>
            <p className="text-xs text-ink-3">Start-date questions use your earliest start date in Work authorization & preferences. Saving your profile also fills answerable gaps in applications awaiting your input.</p>
          </Card>
          <Rows title="Standard application answers" hint="When a form asks a similar question, your saved answer is used word for word." items={p.standard_answers} onChange={(v) => up("standard_answers", v)} blank={{ question: "", answer: "" }}
            fields={[["question", "Question (e.g. How did you hear about us?)"], ["answer", "Your answer", "area"]]} wide />
        </>}

        {tab === "documents" && <Documents docs={docs.data} reload={docs.reload} />}
      </div>

      {dirty && tab !== "documents" && (
        <div className="sticky bottom-[70px] z-20 mt-6 md:bottom-4">
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-line-strong bg-raised/95 p-3 shadow-2xl shadow-black/60 backdrop-blur">
            <p className="px-1 text-[13px] text-ink-2">You have unsaved changes.</p>
            <div className="flex gap-2"><Button onClick={() => setP(JSON.parse(saved))}>Discard</Button><Button variant="primary" loading={busy} onClick={save}>Save profile</Button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function StrList({ label, hint, values, onChange, placeholder, chips }: { label: string; hint?: string; values: string[]; onChange: (v: string[]) => void; placeholder?: string; chips?: boolean }) {
  const [draft, setDraft] = useState("");
  const add = () => { const v = draft.trim(); if (v && !values.includes(v)) onChange([...values, v]); setDraft(""); };
  return (
    <div className={chips ? "" : "sm:col-span-2"}>
      <Label hint={hint}>{label}</Label>
      <div className="flex flex-wrap gap-1.5">
        {values.map((v) => <span key={v} className="inline-flex items-center gap-1 rounded-lg border border-line bg-raised py-1 pl-2.5 pr-1 text-[13px]">{v}<button onClick={() => onChange(values.filter((x) => x !== v))} aria-label={`Remove ${v}`} className="rounded p-0.5 text-ink-3 hover:bg-hover hover:text-bad"><Trash2 className="size-3" /></button></span>)}
        <span className="inline-flex gap-1.5"><Input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} placeholder={placeholder} aria-label={`Add to ${label}`} className="h-8 w-44 text-[13px]" /><Button size="sm" onClick={add} disabled={!draft.trim()} icon={<Plus className="size-3.5" />}>Add</Button></span>
      </div>
    </div>
  );
}

function Rows({ title, hint, items, onChange, blank, fields, wide }: { title: string; hint?: string; items: any[]; onChange: (v: any[]) => void; blank: any; fields: [string, string, string?][]; wide?: boolean }) {
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-start justify-between gap-3"><div><h2 className="text-[13px] font-semibold">{title}</h2>{hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}</div><Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => onChange([...items, structuredClone(blank)])}>Add</Button></div>
      {items.length === 0 && <p className="rounded-xl border border-dashed border-line py-6 text-center text-[13px] text-ink-3">Nothing added yet.</p>}
      <ul className="space-y-3">
        {items.map((it, i) => (
          <li key={i} className="rounded-xl border border-line bg-raised/40 p-3.5">
            <div className={cx("grid gap-3", wide ? "" : "sm:grid-cols-2")}>
              {fields.map(([k, l, kind]) => (
                <div key={k} className={kind === "area" ? "sm:col-span-2" : ""}>
                  <Label>{l}</Label>
                  {kind === "area" ? <Textarea rows={3} value={it[k] ?? ""} onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} aria-label={l} />
                    : kind === "list" ? <Input value={(it[k] ?? []).join(", ")} onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, [k]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x)))} aria-label={l} />
                      : <Input value={it[k] ?? ""} onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} aria-label={l} />}
                </div>
              ))}
            </div>
            <div className="mt-2.5 flex justify-end"><Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => onChange(items.filter((_, j) => j !== i))}>Remove</Button></div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Documents({ docs, reload }: { docs: any[] | null; reload: () => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState("cv");
  const [busy, setBusy] = useState(false);
  async function upload(file: File) {
    const form = new FormData(); form.append("file", file); form.append("kind", kind); form.append("label", file.name.replace(/\.[^.]+$/, ""));
    setBusy(true);
    try { await api("/documents", { form }); toast("Uploaded."); reload(); } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  }
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-[13px] font-semibold">CVs and documents</h2><p className="mt-0.5 text-xs text-ink-3">PDF, DOCX or TXT, up to 5 MB. Stored privately on this server and only uploaded to forms you approve.</p></div>
        <div className="flex items-center gap-2">
          <select aria-label="Document type" value={kind} onChange={(e) => setKind(e.target.value)} className="h-9 rounded-[10px] border border-line bg-raised px-2.5 text-[13px]"><option value="cv">CV</option><option value="cover_letter">Cover letter</option><option value="other">Other</option></select>
          <input ref={input} type="file" accept=".pdf,.docx,.txt" className="sr-only" id="doc-upload" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button variant="primary" loading={busy} icon={<FileUp className="size-4" />} onClick={() => input.current?.click()}>Upload</Button>
        </div>
      </div>
      {docs === null ? <Skeleton className="mt-4 h-20" /> : docs.length === 0 ? <Empty icon={<FileUp className="size-5" />} title="No documents yet">Upload at least one CV. Applications cannot be prepared for approval without it.</Empty> : (
        <ul className="mt-4 divide-y divide-line/70">
          {docs.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{d.label} {d.is_default && <Badge tone="accent" className="ml-1"><Star className="size-3 fill-accent" />Default</Badge>}</p><p className="truncate text-xs text-ink-3">{d.kind === "cv" ? "CV" : d.kind === "cover_letter" ? "Cover letter" : "Other"} · {d.filename} · {(d.size / 1024).toFixed(0)} KB · {fmtDate(d.created_at)}</p></div>
              <a href={`/api/documents/${d.id}/download`} className="text-xs font-medium text-ink-3 hover:text-accent">Download</a>
              {!d.is_default && <Button size="sm" onClick={() => api(`/documents/${d.id}`, { method: "PATCH", body: { is_default: true } }).then(reload).catch((e) => toast(e.message, "error"))}>Make default</Button>}
              <Button size="sm" variant="ghost" aria-label={`Delete ${d.label}`} icon={<Trash2 className="size-3.5" />} onClick={() => { if (confirm(`Delete “${d.label}”?`)) api(`/documents/${d.id}`, { method: "DELETE" }).then(() => { toast("Deleted."); reload(); }).catch((e) => toast(e.message, "error")); }} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
