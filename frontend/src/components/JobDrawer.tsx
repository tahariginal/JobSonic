"use client";
import { Bookmark, BookmarkCheck, ExternalLink, FileText, RefreshCw, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import { api, fmtDate, timeAgo, titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useShell } from "./Shell";
import { Badge, Button, cx, Drawer, EligibilityBadge, ErrorNote, Select, Skeleton, Stars, Textarea, useToast, VisaBadge } from "./ui";

const KIND: Record<string, [string, string]> = { verified: ["good", "Verified"], unverified: ["unknown", "Unverified"], ai: ["info", "AI interpretation"] };
const SEV: Record<string, string> = { reject: "bg-bad", review: "bg-warn", ok: "bg-good", info: "bg-ink-3" };

export function Evidence({ items }: { items: any[] }) {
  if (!items?.length) return <p className="text-[13px] text-ink-3">No evidence recorded.</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((e, i) => (
        <li key={i} className="rounded-xl border border-line bg-raised/60 p-3">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <Badge tone={KIND[e.kind]?.[0] ?? "neutral"}>{KIND[e.kind]?.[1] ?? e.kind}</Badge>
            {e.checked_at && <span className="text-[11px] text-ink-3">checked {fmtDate(e.checked_at)}</span>}
          </div>
          {e.quote && <blockquote className="border-l-2 border-accent/60 pl-3 text-[13px] italic leading-relaxed text-ink">“{e.quote}”</blockquote>}
          <p className={cx("text-[13px] leading-relaxed text-ink-2", e.quote && "mt-1.5")}>{e.explanation}</p>
          {e.source_url && <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-accent">Source: official posting<ExternalLink className="size-3" /></a>}
        </li>
      ))}
    </ul>
  );
}

export function Reasons({ items }: { items: any[] }) {
  return (
    <ul className="space-y-2">
      {(items ?? []).map((r, i) => (
        <li key={i} className="flex gap-2.5 text-[13px]">
          <span className={cx("mt-[7px] size-1.5 shrink-0 rounded-full", SEV[r.severity] ?? "bg-ink-3")} />
          <span className="min-w-0">
            <span className="text-ink">{r.text}</span>{" "}
            <Badge tone={KIND[r.kind]?.[0] ?? "neutral"} className="align-middle">{KIND[r.kind]?.[1] ?? r.kind}</Badge>
            {r.quote && <span className="mt-1 block border-l-2 border-line-strong pl-2.5 text-xs italic leading-relaxed text-ink-3">“{r.quote}”</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="border-t border-line px-5 py-4"><h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-3">{title}</h3>{children}</section>;
}

export function JobDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: j, error, reload, loading } = useApi<any>(id ? `/jobs/${id}` : null);
  const { bump } = useShell();
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [showDesc, setShowDesc] = useState(false);
  useEffect(() => { setShowDesc(false); setNote(""); }, [id]);

  async function act(name: string, fn: () => Promise<any>, ok?: string) {
    setBusy(name);
    try { await fn(); if (ok) toast(ok); await reload(); bump(); } catch (e: any) { toast(e.message, "error"); } finally { setBusy(""); }
  }
  const comp = j?.fit_breakdown?.components ?? {};
  const compLabel: Record<string, string> = { skills: "Skills overlap", interest: "Your interests", level: "Experience level", visa: "Visa feasibility", location: "Location", salary: "Salary" };

  return (
    <Drawer open={id !== null} onClose={onClose} title={j ? `${j.company} — ${j.title}` : "Job"} wide>
      {error && <div className="p-5"><ErrorNote>{error}</ErrorNote></div>}
      {loading && !j && <div className="space-y-3 p-5"><Skeleton className="h-7 w-2/3" /><Skeleton className="h-4 w-1/2" /><Skeleton className="h-28 w-full" /><Skeleton className="h-40 w-full" /></div>}
      {j && (
        <div className="animate-in">
          <div className="px-5 pb-4 pt-5">
            <p className="text-[13px] font-medium text-accent">{j.company}</p>
            <h2 className="mt-1 text-xl font-semibold leading-snug tracking-tight">{j.title}</h2>
            <p className="mt-1.5 text-[13px] text-ink-2">{j.location || "Location not stated"}{j.remote_mode !== "unknown" && ` · ${titleCase(j.remote_mode)}`}{j.salary_text && ` · ${j.salary_text}`}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Stars value={j.fit_stars} size={15} />
              <VisaBadge status={j.visa_status} label={j.visa_label} />
              <EligibilityBadge value={j.eligibility} />
              <Badge>{titleCase(j.stage)}</Badge>
              {!j.is_active && <Badge tone="bad">Closed</Badge>}
              {j.manual_override && <Badge tone="accent">Your override</Badge>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {j.application ? (
                <Button variant="primary" icon={<FileText className="size-4" />} onClick={() => { onClose(); router.push(`/application/?id=${j.application.id}`); }}>Open application</Button>
              ) : (
                <Button variant="primary" icon={<FileText className="size-4" />} loading={busy === "prepare"} disabled={!j.is_active}
                  onClick={() => act("prepare", () => api(`/jobs/${j.id}/prepare`, { method: "POST" }), "Preparing application…")}>Prepare application</Button>
              )}
              {["discovered", "verified"].includes(j.stage) && <Button loading={busy === "short"} onClick={() => act("short", () => api(`/jobs/${j.id}/stage`, { body: { to: "shortlisted" } }), "Shortlisted.")}>Shortlist</Button>}
              <Button icon={j.saved ? <BookmarkCheck className="size-4 text-accent" /> : <Bookmark className="size-4" />} onClick={() => act("save", () => api(`/jobs/${j.id}`, { method: "PATCH", body: { saved: !j.saved } }))}>{j.saved ? "Saved" : "Save"}</Button>
              <a href={j.apply_url} target="_blank" rel="noopener noreferrer" className="inline-flex h-9 items-center gap-2 rounded-[10px] border border-line bg-raised px-3.5 text-sm font-medium transition-colors hover:border-line-strong hover:bg-hover">Official posting<ExternalLink className="size-3.5 text-ink-3" /></a>
            </div>
          </div>

          <Section title="Why this rating">
            <p className="text-[13.5px] leading-relaxed text-ink">{j.fit_reason}</p>
            <p className="mt-1 text-xs text-ink-3">Personal relevance score {j.fit_score}/100 · {j.analysis_source === "ai" ? "refined by AI review" : "computed by rules, no AI"}</p>
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              {Object.keys(compLabel).filter((k) => k in comp).map((k) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between text-xs"><span className="text-ink-3">{compLabel[k]}</span><span className="tabular text-ink-2">{Math.round(comp[k] * 100)}%</span></div>
                  <div className="h-1.5 rounded-full bg-white/[.05]"><div className="h-full rounded-full bg-chart" style={{ width: `${comp[k] * 100}%` }} /></div>
                </div>
              ))}
            </div>
            {(j.fit_breakdown?.matched_skills?.length > 0 || j.fit_breakdown?.unmatched_technologies?.length > 0) && (
              <div className="mt-3 space-y-1.5 text-xs">
                {j.fit_breakdown.matched_skills?.length > 0 && <p className="text-ink-3">In your profile: {j.fit_breakdown.matched_skills.map((s: string) => <Badge key={s} tone="good" className="mr-1 mt-1">{s}</Badge>)}</p>}
                {j.fit_breakdown.unmatched_technologies?.length > 0 && <p className="text-ink-3">Mentioned, not in your profile: {j.fit_breakdown.unmatched_technologies.map((s: string) => <Badge key={s} className="mr-1 mt-1">{s}</Badge>)}</p>}
              </div>
            )}
            {j.ai_notes && <p className="mt-3 rounded-xl border border-info/25 bg-info/[.06] p-3 text-[13px] text-ink-2"><Badge tone="info" className="mr-2">AI interpretation</Badge>{j.ai_notes}</p>}
          </Section>

          <Section title="Visa & relocation evidence">
            <div className="mb-3 grid grid-cols-1 gap-2 text-[13px] sm:grid-cols-3">
              <div className="rounded-xl border border-line p-3"><p className="text-xs text-ink-3">Sponsorship</p><p className="mt-1"><VisaBadge status={j.visa_status} label={j.visa_label} /></p></div>
              <div className="rounded-xl border border-line p-3"><p className="text-xs text-ink-3">Relocation help</p><p className="mt-1 font-medium">{{ yes: "Mentioned", no: "Not offered", unverified: "Not mentioned" }[j.relocation as string] ?? j.relocation}</p></div>
              <div className="rounded-xl border border-line p-3"><p className="text-xs text-ink-3">Remote from Morocco</p><p className="mt-1 font-medium">{{ likely: "Possibly (worldwide)", no: "No", unverified: "Not verified", "n/a": "Not applicable" }[j.remote_from_morocco as string] ?? j.remote_from_morocco}</p></div>
            </div>
            <Evidence items={j.visa_evidence} />
            {j.relocation_evidence?.length > 0 && <div className="mt-2.5"><Evidence items={j.relocation_evidence.map((e: any) => ({ ...e, explanation: "Relocation support is mentioned. This alone does not prove visa sponsorship." }))} /></div>}
          </Section>

          <Section title="Eligibility analysis">
            <Reasons items={j.eligibility_reasons} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs text-ink-3">Disagree?</span>
              <Select aria-label="Override eligibility" value={j.manual_override ? j.eligibility : "auto"} className="h-8 w-44 text-[13px]"
                onChange={(e) => act("elig", () => api(`/jobs/${j.id}`, { method: "PATCH", body: { eligibility: e.target.value } }), "Eligibility updated.")}>
                <option value="auto">Automatic</option><option value="eligible">Mark eligible</option><option value="needs_review">Mark needs review</option><option value="rejected">Mark not eligible</option>
              </Select>
            </div>
          </Section>

          <Section title="What you'll do">
            <p className="text-[13.5px] leading-relaxed text-ink-2">{j.summary || "No summary could be extracted."}</p>
            <button onClick={() => setShowDesc((s) => !s)} className="mt-2 text-xs font-medium text-accent hover:underline">{showDesc ? "Hide full description" : "Show full description"}</button>
            {showDesc && <pre className="mt-3 max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-xl border border-line bg-raised/50 p-4 font-sans text-[13px] leading-relaxed text-ink-2">{j.description}</pre>}
          </Section>

          <Section title="Source & verification">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
              <dt className="text-ink-3">Source</dt><dd className="truncate">{titleCase(j.provider)} board “{j.board_token}” · job ID {j.external_id}</dd>
              <dt className="text-ink-3">Official URL</dt><dd className="truncate"><a className="hover:text-accent" href={j.canonical_url} target="_blank" rel="noopener noreferrer">{j.canonical_url}</a></dd>
              <dt className="text-ink-3">Discovered</dt><dd>{fmtDate(j.discovered_at)}</dd>
              <dt className="text-ink-3">Last verified</dt><dd>{fmtDate(j.last_verified_at)} <span className="text-ink-3">({timeAgo(j.last_verified_at)})</span></dd>
              {j.updated_content_at && <><dt className="text-ink-3">Content changed</dt><dd>{fmtDate(j.updated_content_at)}</dd></>}
              {j.closed_at && <><dt className="text-ink-3">Closed</dt><dd>{fmtDate(j.closed_at)}</dd></>}
              <dt className="text-ink-3">Fingerprint</dt><dd className="font-mono text-xs text-ink-3">{j.fingerprint}</dd>
            </dl>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={busy === "verify"} onClick={() => act("verify", async () => { const r = await api(`/jobs/${j.id}/verify`, { method: "POST" }); toast(r.live === null ? "Could not reach the source." : r.live ? "Still active on the official source." : "No longer listed.", r.live === false ? "error" : "ok"); })}>Verify now</Button>
              <Button size="sm" icon={<Sparkles className="size-3.5" />} loading={busy === "ai"} onClick={() => act("ai", () => api(`/jobs/${j.id}/ai-evaluate`, { method: "POST" }), "AI evaluation queued.")}>AI review</Button>
              {j.stage !== "archived" && !j.application && <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => act("arch", () => api(`/jobs/${j.id}/stage`, { body: { to: "archived", confirm: true } }), "Hidden from your lists.").then(onClose)}>Hide job</Button>}
            </div>
          </Section>

          <Section title="Notes">
            <div className="flex gap-2">
              <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a private note…" aria-label="New note" />
              <Button disabled={!note.trim()} loading={busy === "note"} onClick={() => act("note", async () => { await api(`/jobs/${j.id}/notes`, { body: { text: note } }); setNote(""); })}>Add</Button>
            </div>
            <ul className="mt-3 space-y-2">{j.notes.map((n: any) => <li key={n.id} className="rounded-xl border border-line bg-raised/50 p-3 text-[13px]"><p className="whitespace-pre-wrap text-ink-2">{n.text}</p><p className="mt-1 text-[11px] text-ink-3">{fmtDate(n.created_at)}</p></li>)}</ul>
          </Section>
          <div className="flex items-center gap-2 border-t border-line px-5 py-4 text-xs text-ink-3"><ShieldCheck className="size-4 shrink-0" />Nothing is submitted from here. Applications are only sent after you approve the exact final version.</div>
        </div>
      )}
    </Drawer>
  );
}
